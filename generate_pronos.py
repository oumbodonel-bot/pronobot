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

# Seuils et Config
CONFIDENCE_THRESHOLD = 2
DIVERSITY_LIMIT = 0.5  # Max 50% du même type de pari

async def generate_daily_pronos():
    init_db()
    
    logger.info("============================================================")
    logger.info(f"  PRONOBOT — GENERATION OPTIMISEE {datetime.now().strftime('%Y-%m-%d')}")
    logger.info("============================================================")

    # 1. Récupération des cotes
    all_matches = await get_all_leagues_odds()
    if not all_matches:
        logger.warning("Aucun match trouvé.")
        return

    # 2. Analyse et Sélection
    valid_pronos = []
    market_counts = {} # Pour la diversité
    
    for match in all_matches:
        home, away = match["home_team"], match["away_team"]
        logger.info(f"Traitement: {home} vs {away}")

        # Stats et Analyse Mathématique étendue
        h_stats, a_stats = await get_team_stats(home, away)
        analysis = full_analysis(match, h_stats, a_stats)
        
        # Pause anti-rate-limit
        await asyncio.sleep(1)

        # Appel Claude avec données étendues
        claude = await get_claude_decision(home, away, match, analysis)
        
        if claude.get("decision") == "VALIDE":
            pari_type = claude.get("pari", "Autre")
            
            # Vérification Diversité
            current_ratio = market_counts.get(pari_type, 0) / (len(valid_pronos) + 1)
            if current_ratio > DIVERSITY_LIMIT and len(valid_pronos) >= 3:
                logger.info(f"  REJETE : Trop de paris de type {pari_type} (Diversité)")
                continue

            # Validation Confiance
            if claude.get("confiance", 0) < CONFIDENCE_THRESHOLD:
                logger.info(f"  REJETE : Confiance trop faible ({claude.get('confiance')})")
                continue

            # Ajout du prono
            prono = {
                "match": match,
                "analysis": analysis,
                "claude": claude,
                "type": pari_type
            }
            valid_pronos.append(prono)
            market_counts[pari_type] = market_counts.get(pari_type, 0) + 1
            logger.info(f"  VALIDE : {pari_type} @ {claude.get('cote')} (Confiance {claude.get('confiance')}/5)")

    # 3. Insertion et Rapports
    if not valid_pronos:
        logger.warning("Aucun prono validé aujourd'hui.")
    else:
        # Attribution FREE/VIP (Le premier est FREE, les autres VIP)
        for i, p in enumerate(valid_pronos):
            is_free = (i == 0)
            label = "FREE" if is_free else "VIP"
            
            # Analyse textuelle
            ana_fr, ana_en = await generate_simple_analysis(p["type"], p["claude"])
            
            insert_prono({
                "match_id": f"{p['match'].get('id', random.randint(1000,9999))}_{label}",
                "home_team": p["match"]["home_team"],
                "away_team": p["match"]["away_team"],
                "league": p["match"]["league"],
                "match_date": datetime.now().date(),
                "match_time": p["match"].get("match_time"),
                "revealed_at": datetime.now(),
                "prono_type": p["type"],
                "prediction": p["claude"]["pari"],
                "confidence": p["claude"]["confiance"],
                "odds": p["claude"]["cote"],
                "kelly_stake": 3.0,
                "value_bet": p["claude"].get("value", 0),
                "analysis_fr": ana_fr["analysis"],
                "analysis_en": ana_en["analysis"],
                "exact_score": p["analysis"]["matrix"]["best_score"],
                "plan_required": "free" if is_free else "vip"
            })
            logger.info(f"  [{label}] {p['match']['home_team']} vs {p['match']['away_team']} inséré.")

    # 4. Score Exact Détaillé
    if all_matches:
        m = all_matches[0]
        h_stats, a_stats = await get_team_stats(m["home_team"], m["away_team"])
        res = full_analysis(m, h_stats, a_stats)
        best_score = res["matrix"]["best_score"]
        
        # Estimation cote score exact (très simplifiée)
        prob = res["matrix"]["top_scores"][0]["prob"]
        est_odds = round(100 / prob, 2) if prob > 0 else 10.0
        
        logger.info(f"Score exact : {best_score} @ {est_odds} (Prob: {prob}%, Confiance: 2/5)")

    # 5. Rapport de Répartition
    logger.info("============================================================")
    logger.info("REPARTITION DES PARIS :")
    for m_type, count in market_counts.items():
        logger.info(f" - {m_type} : {count}")
    logger.info("============================================================")
    logger.info("GENERATION TERMINEE")

if __name__ == "__main__":
    asyncio.run(generate_daily_pronos())
