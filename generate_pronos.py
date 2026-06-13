import os
import asyncio
import logging
import json
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from api.odds_api import get_all_leagues_odds
from api.claude_ai import get_claude_decision, generate_simple_analysis
from core.math_engine import full_analysis
from core.database import insert_prono, init_db, get_team_stats

# Configuration des logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def generate_daily_pronos():
    init_db()
    
    logger.info("============================================================")
    logger.info(f"  PRONOBOT — GENERATION CATEGORIES {datetime.now().strftime('%Y-%m-%d')}")
    logger.info("============================================================")

    # 1. Récupération des cotes
    all_matches = await get_all_leagues_odds()
    if not all_matches:
        logger.warning("Aucun match trouvé.")
        return

    # 2. Analyse Multi-Mode et Stockage
    stats = {
        "total_matches": len(all_matches),
        "validated": {"GRATUIT": 0, "VIP": 0, "MONTANTE": 0, "SCORE_EXACT": 0},
        "rejected": {"GRATUIT": 0, "VIP": 0, "MONTANTE": 0, "SCORE_EXACT": 0},
        "rejection_reasons": {"Claude": 0, "Cote": 0, "Confiance": 0, "Doublon": 0, "Metier": 0}
    }

    categories = {
        "free": {"mode": "GRATUIT", "matches": [], "min_cote": 1.40, "max_cote": 2.00, "min_confiance": 2},
        "vip": {"mode": "VIP", "matches": [], "min_cote": 1.40, "max_cote": 2.00, "min_confiance": 2},
        "montante": {"mode": "MONTANTE", "matches": [], "min_cote": 1.20, "max_cote": 1.50, "min_confiance": 3},
        "exact_score": {"mode": "SCORE_EXACT", "matches": [], "min_cote": 1.01, "max_cote": 100.0, "min_confiance": 1}
    }
    
    for match in all_matches:
        home, away = match["home_team"], match["away_team"]
        h_stats, a_stats = await get_team_stats(home, away)
        analysis = full_analysis(match, h_stats, a_stats)
        
        for cat_id, config in categories.items():
            mode_name = config["mode"]
            logger.info(f"[{mode_name}] Analyse: {home} vs {away}")
            
            # Appel Claude avec le mode spécifique
            claude = await get_claude_decision(home, away, match, analysis, mode=mode_name)
            
            # Logs détaillés demandés
            decision = claude.get("decision", "REJETE")
            pari = claude.get("marche_choisi", claude.get("pronostic", "N/A"))
            cote = claude.get("cote_choisie", 0)
            conf = claude.get("confiance", 0)
            
            # 1. Rejet par Claude
            if decision != "VALIDE":
                reason = claude.get('raison_rejet', 'Sans raison')
                logger.info(f"  ❌ DÉCISION : {decision} | RAISON : {reason}")
                stats["rejected"][mode_name] += 1
                stats["rejection_reasons"]["Claude"] += 1
                continue
                
            # Mapping pour compatibilité
            claude["pari"] = pari
            claude["cote"] = cote
            
            # 2. Rejet par filtre de cote
            if not (config["min_cote"] <= cote <= config["max_cote"]):
                logger.info(f"  ❌ REJET COTE : {cote} hors limites [{config['min_cote']}-{config['max_cote']}]")
                stats["rejected"][mode_name] += 1
                stats["rejection_reasons"]["Cote"] += 1
                continue
                
            # 3. Rejet par filtre de confiance
            if conf < config["min_confiance"]:
                logger.info(f"  ❌ REJET CONFIANCE : {conf} < {config['min_confiance']}")
                stats["rejected"][mode_name] += 1
                stats["rejection_reasons"]["Confiance"] += 1
                continue
                
            # Match validé pour cette catégorie
            config["matches"].append({
                "match": match,
                "analysis": analysis,
                "claude": claude,
                "type": pari
            })
            stats["validated"][mode_name] += 1
            logger.info(f"  ✅ VALIDE | Marché: {pari} | Cote: {cote} | Confiance: {conf}")
            
        await asyncio.sleep(0.2)

    # 3. Sélection Finale par Catégorie
    
    # A. Prono Gratuit (Le meilleur des candidats free)
    free_prono = None
    if categories["free"]["matches"]:
        # Tri par confiance puis value
        categories["free"]["matches"].sort(key=lambda x: (x["claude"]["confiance"], x["claude"].get("value_pct", 0)), reverse=True)
        free_prono = categories["free"]["matches"][0]
    
    # B. Pronos VIP (Top 5 des candidats VIP)
    vip_pronos = []
    if categories["vip"]["matches"]:
        categories["vip"]["matches"].sort(key=lambda x: (x["claude"]["confiance"], x["claude"].get("value_pct", 0)), reverse=True)
        seen_matches = set()
        for p in categories["vip"]["matches"]:
            m_id = f"{p['match']['home_team']}-{p['match']['away_team']}"
            if m_id not in seen_matches and len(vip_pronos) < 5:
                vip_pronos.append(p)
                seen_matches.add(m_id)
            elif m_id in seen_matches:
                logger.info(f"  ❌ REJET DOUBLON VIP : {m_id}")
    
    # C. Combiné (3 matchs parmi VIP ou Free pour assurer la cote 2.00-4.00)
    combo_pronos = []
    all_valid = categories["vip"]["matches"] + categories["free"]["matches"]
    if len(all_valid) >= 3:
        for _ in range(100):
            sample = random.sample(all_valid, 3)
            # Éviter doublons de matchs dans le combiné
            if len(set(f"{m['match']['home_team']}-{m['match']['away_team']}" for m in sample)) < 3:
                continue
            total_odds = 1.0
            for s in sample:
                total_odds *= s["claude"]["cote"]
            if 2.00 <= total_odds <= 4.00:
                combo_pronos = sample
                break
        if not combo_pronos:
            logger.info("  ❌ REJET METIER COMBINE : Aucune combinaison de cote 2.00-4.00 trouvée")
            stats["rejection_reasons"]["Metier"] += 1
    
    # D. Montante (Sécurité absolue)
    montante_prono = None
    if categories["montante"]["matches"]:
        categories["montante"]["matches"].sort(key=lambda x: x["claude"]["confiance"], reverse=True)
        montante_prono = categories["montante"]["matches"][0]
    
    # E. Score Exact
    exact_score_prono = None
    if categories["exact_score"]["matches"]:
        # Le plus probable selon Poisson
        exact_score_prono = max(categories["exact_score"]["matches"], key=lambda x: x["analysis"]["matrix"]["top_scores"][0]["prob"])

    # 4. Insertion avec labels compatibles Handlers
    
    async def process_and_insert(p, prono_type, plan):
        ana_fr, ana_en = await generate_simple_analysis(p["type"], p["claude"])
        
        # UTC Time handling for consistency
        match_dt = p["match"]["match_datetime"]
        if match_dt.tzinfo is None:
            match_dt = match_dt.replace(tzinfo=timedelta(hours=0))
            
        revealed_at = match_dt - timedelta(hours=1)

        # Correction pour le Score Exact : utiliser la cote estimée par Poisson
        odds = p["claude"]["cote"]
        if prono_type == "exact_score":
            odds = p["analysis"]["matrix"].get("best_score_odds", 7.0)
            prediction = p["analysis"]["matrix"].get("best_score", "1-1")
        else:
            prediction = p["claude"]["pari"]

        value_bet = p["analysis"].get("value", 0)

        insert_prono({
            "match_id": f"{p['match'].get('id', random.randint(1000,9999))}_{prono_type}_{datetime.now().strftime('%H%M%S')}",
            "home_team": p["match"]["home_team"],
            "away_team": p["match"]["away_team"],
            "league": p["match"]["league"],
            "match_date": match_dt.date(),
            "match_time": match_dt.strftime("%H:%M:%S"),
            "revealed_at": revealed_at,
            "prono_type": prono_type,
            "prediction": prediction,
            "confidence": p["claude"]["confiance"],
            "odds": odds,
            "kelly_stake": 3.0,
            "value_bet": value_bet,
            "analysis_fr": ana_fr["analysis"],
            "analysis_en": ana_en["analysis"],
            "exact_score": json.dumps(p["analysis"]["matrix"]["top_scores"]),
            "plan_required": plan
        })

    # Logique d'insertion par section
    # Gratuit
    if free_prono:
        await process_and_insert(free_prono, "free", "free")
        logger.info(f"✅ Section Gratuit : {free_prono['match']['home_team']}")
    else:
        logger.info("❌ Section Gratuit : Section indisponible aujourd'hui")

    # VIP (On insère les VIP pronos avec plan 'vip')
    # On évite d'insérer des doublons de matchs dans la section VIP elle-même
    seen_vip = set()
    vip_count = 0
    for p in vip_pronos:
        m_id = f"{p['match']['home_team']}_{p['match']['away_team']}"
        if m_id not in seen_vip:
            await process_and_insert(p, "vip", "vip")
            seen_vip.add(m_id)
            vip_count += 1
    if vip_count > 0:
        logger.info(f"✅ Section VIP : {vip_count} matchs")
    else:
        logger.info("❌ Section VIP : Section indisponible aujourd'hui")

    # Combiné
    # On marque spécifiquement les matchs du combiné pour que le handler les retrouve sans ambiguïté
    if combo_pronos:
        for p in combo_pronos:
            await process_and_insert(p, "combined", "vip")
        logger.info(f"✅ Section Combiné : 3 matchs insérés")
    else:
        logger.info("❌ Section Combiné : Section indisponible aujourd'hui")

    # Montante
    if montante_prono:
        await process_and_insert(montante_prono, "montante", "vip")
        logger.info(f"✅ Section Montante : {montante_prono['match']['home_team']}")
    else:
        logger.info("❌ Section Montante : Section indisponible aujourd'hui")

    # Score Exact
    if exact_score_prono:
        await process_and_insert(exact_score_prono, "exact_score", "vip")
        logger.info(f"✅ Section Score Exact : {exact_score_prono['match']['home_team']}")
    else:
        logger.info("❌ Section Score Exact : Section indisponible aujourd'hui")

    logger.info("============================================================")
    logger.info("📊 RÉSUMÉ GLOBAL DE LA GÉNÉRATION")
    logger.info(f"Total matchs analysés : {stats['total_matches']}")
    logger.info("------------------------------------------------------------")
    for mode, count in stats["validated"].items():
        rej = stats["rejected"][mode]
        logger.info(f"Mode {mode:12} : ✅ {count} validés | ❌ {rej} rejetés")
    logger.info("------------------------------------------------------------")
    logger.info("Détail des rejets :")
    for reason, count in stats["rejection_reasons"].items():
        logger.info(f" - {reason:10} : {count}")
    logger.info("============================================================")
    logger.info("GENERATION TERMINEE")

if __name__ == "__main__":
    asyncio.run(generate_daily_pronos())
