import os
import asyncio
import logging
import json
import random
import importlib.util
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from api.odds_api import get_all_leagues_odds
from api.claude_ai import get_claude_decision, generate_simple_analysis
from core.math_engine import full_analysis
from core.database import insert_prono, init_db
from core.manual_data_fusion import get_manual_data_for_match, fuse_data

# Configuration des logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_manual_data():
    """Charge dynamiquement le dictionnaire 'data' depuis analyse.py s'il existe."""
    path = "analyse.py"
    if not os.path.exists(path):
        logger.warning("Fichier analyse.py non trouvé. Génération sans données manuelles.")
        return {}
    
    try:
        spec = importlib.util.spec_from_file_location("analyse", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return getattr(module, "data", {})
    except Exception as e:
        logger.error(f"Erreur lors du chargement de analyse.py : {e}")
        return {}

async def generate_daily_pronos():
    init_db()
    
    logger.info("============================================================")
    logger.info(f"  PRONOBOT — GENERATION CATEGORIES {datetime.now().strftime('%Y-%m-%d')}")
    logger.info("============================================================")

    # Chargement des données manuelles
    manual_data_dict = load_manual_data()
    if manual_data_dict:
        logger.info(f"📚 {len(manual_data_dict)} analyses manuelles chargées depuis analyse.py")

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
        
        # 1. Analyse statistique (API)
        analysis = full_analysis(match, None, None)
        
        # 2. Recherche et fusion des données manuelles
        manual_content = get_manual_data_for_match(home, away, manual_data_dict)
        enriched_analysis = fuse_data(analysis, manual_content)
        
        # 3. Appel Claude unique avec données enrichies
        claude_response = await get_claude_decision(home, away, match, enriched_analysis)
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
                "analysis": enriched_analysis,
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
    
    # C. Combiné
    combo_pronos = []
    all_valid_for_combo = categories["VIP"]["matches"] + categories["GRATUIT"]["matches"]
    unique_matches_for_combo = {}
    for p in all_valid_for_combo:
        m_id = f"{p['match']['home_team']}-{p['match']['away_team']}"
        if m_id not in unique_matches_for_combo or p["quality_score"] > unique_matches_for_combo[m_id]["quality_score"]:
            unique_matches_for_combo[m_id] = p
    
    candidate_list = list(unique_matches_for_combo.values())
    if len(candidate_list) >= 3:
        for _ in range(200):
            sample = random.sample(candidate_list, 3)
            total_odds = 1.0
            for s in sample:
                total_odds *= s["claude"]["cote"]
            if 2.00 <= total_odds <= 4.00:
                combo_pronos = sample
                stats["validated"]["COMBINE"] += 1
                break
    
    # D. Montante
    montante_prono = None
    if categories["MONTANTE"]["matches"]:
        categories["MONTANTE"]["matches"].sort(key=lambda x: (x["claude"]["confiance"], x["quality_score"]), reverse=True)
        montante_prono = categories["MONTANTE"]["matches"][0]
    
    # E. Score Exact
    exact_score_prono = None
    if categories["SCORE_EXACT"]["matches"]:
        categories["SCORE_EXACT"]["matches"].sort(key=lambda x: (x["analysis"]["matrix"]["top_scores"][0]["prob"], x["quality_score"]), reverse=True)
        exact_score_prono = categories["SCORE_EXACT"]["matches"][0]

    # 4. Insertion
    async def process_and_insert(p, prono_type, plan):
        match_key = f"{p['match']['home_team']}-{p['match']['away_team']}"
        claude_full_decision = all_claude_decisions.get(match_key, {})
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
            "value_bet": p["claude"].get("value_pct", 0),
            "analysis_fr": ana_fr["analysis"],
            "analysis_en": ana_en["analysis"],
            "exact_score": json.dumps(p["analysis"]["matrix"]["top_scores"]),
            "plan_required": plan
        })

    # Logique d'insertion par section
    if free_prono:
        await process_and_insert(free_prono, "GRATUIT", "free")
    if vip_pronos:
        for p in vip_pronos:
            await process_and_insert(p, "VIP", "vip")
    if combo_pronos:
        for p in combo_pronos:
            await process_and_insert(p, "COMBINE", "vip")
    if montante_prono:
        await process_and_insert(montante_prono, "MONTANTE", "vip")
    if exact_score_prono:
        await process_and_insert(exact_score_prono, "SCORE_EXACT", "vip")

    logger.info("============================================================")
    logger.info("📊 RÉSUMÉ GLOBAL DE LA GÉNÉRATION")
    logger.info(f"Total matchs analysés : {stats['total_matches']}")
    for mode, count in stats["validated"].items():
        logger.info(f"Mode {mode:12} : ✅ {count} validés")
    logger.info("============================================================")
    logger.info("GENERATION TERMINEE")

if __name__ == "__main__":
    asyncio.run(generate_daily_pronos())
