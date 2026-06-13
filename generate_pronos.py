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
from core.database import insert_prono, init_db

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
        "validated": {"GRATUIT": 0, "VIP": 0, "MONTANTE": 0, "SCORE_EXACT": 0, "COMBINE": 0},
        "rejected": {"GRATUIT": 0, "VIP": 0, "MONTANTE": 0, "SCORE_EXACT": 0, "COMBINE": 0},
        "rejection_reasons": {"Claude": 0, "Cote": 0, "Confiance": 0, "Doublon": 0, "Metier": 0}
    }

    categories = {
        "GRATUIT": {"matches": [], "min_cote": 1.40, "max_cote": 2.00, "min_confiance": 2},
        "VIP": {"matches": [], "min_cote": 1.40, "max_cote": 2.00, "min_confiance": 2},
        "MONTANTE": {"matches": [], "min_cote": 1.20, "max_cote": 1.50, "min_confiance": 3},
        "SCORE_EXACT": {"matches": [], "min_cote": 1.01, "max_cote": 100.0, "min_confiance": 1}
    }
    
    all_claude_decisions = {}

    for match in all_matches:
        home, away = match["home_team"], match["away_team"]
        logger.info(f"Analyse globale du match: {home} vs {away}")
        analysis = full_analysis(match, None, None)
        
        # Appel Claude unique pour toutes les catégories
        claude_response = await get_claude_decision(home, away, match, analysis)
        all_claude_decisions[f"{home}-{away}"] = claude_response
        
        quality_score = claude_response.get("global_quality_score", 0)
        logger.info(f"  Score de qualité global: {quality_score}/100")

        for mode_name, config in categories.items():
            claude_decision_for_mode = claude_response.get(mode_name, {})
            
            decision = claude_decision_for_mode.get("decision", "REJETE")
            pari = claude_decision_for_mode.get("marche_choisi", claude_decision_for_mode.get("pronostic", "N/A"))
            cote = claude_decision_for_mode.get("cote_choisie", 0)
            conf = claude_decision_for_mode.get("confiance", 0)
            value_pct = claude_decision_for_mode.get("value_pct", 0)
            raison_rejet = claude_decision_for_mode.get("raison_rejet", "Sans raison")

            # 1. Rejet par Claude
            if decision != "VALIDE":
                logger.info(f"  ❌ {mode_name} - DÉCISION : {decision} | RAISON : {raison_rejet}")
                stats["rejected"][mode_name] += 1
                stats["rejection_reasons"]["Claude"] += 1
                continue
                
            # Mapping pour compatibilité
            claude_decision_for_mode["pari"] = pari
            claude_decision_for_mode["cote"] = cote
            
            # 2. Rejet par filtre de cote
            if not (config["min_cote"] <= cote <= config["max_cote"]):
                logger.info(f"  ❌ {mode_name} - REJET COTE : {cote} hors limites [{config['min_cote']}-{config['max_cote']}]")
                stats["rejected"][mode_name] += 1
                stats["rejection_reasons"]["Cote"] += 1
                continue
                
            # 3. Rejet par filtre de confiance
            if conf < config["min_confiance"]:
                logger.info(f"  ❌ {mode_name} - REJET CONFIANCE : {conf} < {config['min_confiance']}")
                stats["rejected"][mode_name] += 1
                stats["rejection_reasons"]["Confiance"] += 1
                continue
            
            # Match validé pour cette catégorie
            categories[mode_name]["matches"].append({
                "match": match,
                "analysis": analysis,
                "claude": claude_decision_for_mode,
                "type": pari,
                "quality_score": quality_score
            })
            stats["validated"][mode_name] += 1
            logger.info(f"  ✅ {mode_name} - VALIDE | Marché: {pari} | Cote: {cote} | Confiance: {conf} | Value: {value_pct}%")
            
        await asyncio.sleep(0.1)

    # 3. Sélection Finale par Catégorie
    
    # A. Prono Gratuit (Le meilleur des candidats free)
    free_prono = None
    if categories["GRATUIT"]["matches"]:
        # Tri par score de qualité, puis confiance, puis value
        categories["GRATUIT"]["matches"].sort(key=lambda x: (x["quality_score"], x["claude"]["confiance"], x["claude"].get("value_pct", 0)), reverse=True)
        free_prono = categories["GRATUIT"]["matches"][0]
    
    # B. Pronos VIP (Top 5 des candidats VIP)
    vip_pronos = []
    if categories["VIP"]["matches"]:
        categories["VIP"]["matches"].sort(key=lambda x: (x["quality_score"], x["claude"]["confiance"], x["claude"].get("value_pct", 0)), reverse=True)
        seen_matches = set()
        for p in categories["VIP"]["matches"]:
            m_id = f"{p['match']['home_team']}-{p['match']['away_team']}"
            if m_id not in seen_matches and len(vip_pronos) < 5:
                vip_pronos.append(p)
                seen_matches.add(m_id)
            elif m_id in seen_matches:
                logger.info(f"  ❌ REJET DOUBLON VIP : {m_id}")
    
    # C. Combiné (3 matchs parmi VIP ou Free pour assurer la cote 2.00-4.00)
    combo_pronos = []
    # On prend tous les matchs validés VIP et GRATUIT
    all_valid_for_combo = categories["VIP"]["matches"] + categories["GRATUIT"]["matches"]
    
    # Supprimer les doublons de matchs (un même match peut être dans VIP et GRATUIT)
    unique_matches_for_combo = {}
    for p in all_valid_for_combo:
        m_id = f"{p['match']['home_team']}-{p['match']['away_team']}"
        if m_id not in unique_matches_for_combo or p["quality_score"] > unique_matches_for_combo[m_id]["quality_score"]:
            unique_matches_for_combo[m_id] = p
    
    candidate_list = list(unique_matches_for_combo.values())
    
    if len(candidate_list) >= 3:
        # Essayer de trouver une combinaison optimale
        for _ in range(200):
            sample = random.sample(candidate_list, 3)
            total_odds = 1.0
            for s in sample:
                total_odds *= s["claude"]["cote"]
            if 2.00 <= total_odds <= 4.00:
                combo_pronos = sample
                stats["validated"]["COMBINE"] += 1
                break
        
        # Si pas trouvé par hasard, on prend les 3 meilleurs par score de qualité et on espère que la cote passe
        if not combo_pronos:
            candidate_list.sort(key=lambda x: x["quality_score"], reverse=True)
            sample = candidate_list[:3]
            total_odds = 1.0
            for s in sample:
                total_odds *= s["claude"]["cote"]
            if 1.8 <= total_odds <= 5.0: # Plus large si pas de combo parfait
                combo_pronos = sample
                stats["validated"]["COMBINE"] += 1
                logger.info(f"  ⚠️ Combiné forcé avec cote {total_odds:.2f}")

        if not combo_pronos:
            logger.info("  ❌ REJET METIER COMBINE : Aucune combinaison de cote acceptable trouvée")
            stats["rejected"]["COMBINE"] += 1
            stats["rejection_reasons"]["Metier"] += 1
    
    # D. Montante (Sécurité absolue)
    montante_prono = None
    if categories["MONTANTE"]["matches"]:
        categories["MONTANTE"]["matches"].sort(key=lambda x: (x["claude"]["confiance"], x["quality_score"]), reverse=True)
        montante_prono = categories["MONTANTE"]["matches"][0]
    
    # E. Score Exact
    exact_score_prono = None
    if categories["SCORE_EXACT"]["matches"]:
        # Le plus probable selon Poisson ou meilleur score de qualité
        categories["SCORE_EXACT"]["matches"].sort(key=lambda x: (x["analysis"]["matrix"]["top_scores"][0]["prob"], x["quality_score"]), reverse=True)
        exact_score_prono = categories["SCORE_EXACT"]["matches"][0]

    # 4. Insertion avec labels compatibles Handlers
    
    async def process_and_insert(p, prono_type, plan):
        match_key = f"{p['match']['home_team']}-{p['match']['away_team']}"
        claude_full_decision = all_claude_decisions.get(match_key, {})
        # Pour le combiné, on utilise la décision VIP ou GRATUIT associée au match choisi
        mode_for_analysis = prono_type if prono_type != "COMBINE" else ("VIP" if p in categories["VIP"]["matches"] else "GRATUIT")
        claude_specific_decision = claude_full_decision.get(mode_for_analysis, {})

        ana_fr, ana_en = await generate_simple_analysis(p["type"], claude_specific_decision)
        
        match_dt = p["match"]["match_datetime"]
        if match_dt.tzinfo is None:
            match_dt = match_dt.replace(tzinfo=timedelta(hours=0))
            
        revealed_at = match_dt - timedelta(hours=1)

        odds = p["claude"]["cote"]
        if prono_type == "SCORE_EXACT":
            odds = p["analysis"]["matrix"].get("best_score_odds", 7.0)
            prediction = p["analysis"]["matrix"].get("best_score", "1-1")
        else:
            prediction = p["claude"]["pari"]

        value_bet = p["claude"].get("value_pct", 0)

        insert_prono({
            "match_id": f"{p['match'].get('id', random.randint(1000,9999))}_{prono_type}_{datetime.now().strftime('%H%M%S')}",
            "home_team": p["match"]["home_team"],
            "away_team": p["match"]["away_team"],
            "league": p["match"]["league"],
            "match_date": match_dt.date(),
            "match_time": match_dt.strftime("%H:%M:%S"),
            "revealed_at": revealed_at,
            "prono_type": prono_type.lower() if prono_type != "COMBINE" else "combined",
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
    if free_prono:
        await process_and_insert(free_prono, "GRATUIT", "free")
        logger.info(f"✅ Section Gratuit : {free_prono['match']['home_team']} vs {free_prono['match']['away_team']}")
    else:
        logger.info("❌ Section Gratuit : Section indisponible aujourd'hui")

    seen_vip = set()
    vip_count = 0
    for p in vip_pronos:
        m_id = f"{p['match']['home_team']}_{p['match']['away_team']}"
        if m_id not in seen_vip:
            await process_and_insert(p, "VIP", "vip")
            seen_vip.add(m_id)
            vip_count += 1
    if vip_count > 0:
        logger.info(f"✅ Section VIP : {vip_count} matchs")
    else:
        logger.info("❌ Section VIP : Section indisponible aujourd'hui")

    if combo_pronos:
        for p in combo_pronos:
            await process_and_insert(p, "COMBINE", "vip")
        logger.info(f"✅ Section Combiné : {len(combo_pronos)} matchs insérés")
    else:
        logger.info("❌ Section Combiné : Section indisponible aujourd'hui")

    if montante_prono:
        await process_and_insert(montante_prono, "MONTANTE", "vip")
        logger.info(f"✅ Section Montante : {montante_prono['match']['home_team']} vs {montante_prono['match']['away_team']}")
    else:
        logger.info("❌ Section Montante : Section indisponible aujourd'hui")

    if exact_score_prono:
        await process_and_insert(exact_score_prono, "SCORE_EXACT", "vip")
        logger.info(f"✅ Section Score Exact : {exact_score_prono['match']['home_team']} vs {exact_score_prono['match']['away_team']}")
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
