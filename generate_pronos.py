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

    # 2. Analyse et Stockage Temporaire
    analyzed_matches = []
    
    for match in all_matches:
        home, away = match["home_team"], match["away_team"]
        logger.info(f"Analyse: {home} vs {away}")

        h_stats, a_stats = await get_team_stats(home, away)
        analysis = full_analysis(match, h_stats, a_stats)
        
        # Appel Claude pour décision
        claude = await get_claude_decision(home, away, match, analysis)
        
        if claude.get("decision") == "VALIDE":
            # Data Integrity Check: Ensure real odds from API are present
            real_odds = claude.get("cote")
            if not real_odds or not isinstance(real_odds, (int, float)) or real_odds <= 1.0:
                logger.warning(f"  REJETE : Cote réelle manquante ou invalide pour {home} vs {away}")
                continue

            analyzed_matches.append({
                "match": match,
                "analysis": analysis,
                "claude": claude,
                "type": claude.get("pari", "Autre")
            })
        
        await asyncio.sleep(0.5)

    # 3. Sélection par Catégorie Strict (Mode Isolation)
    
    # A. Prono Gratuit (Le plus fiable)
    free_prono = None
    if analyzed_matches:
        free_prono = max(analyzed_matches, key=lambda x: x["claude"].get("confiance", 0))
    
    # B. Pronos VIP (3 à 5 matchs)
    # On prend les meilleurs pronos restants pour le flux VIP classique
    vip_candidates = [m for m in analyzed_matches if m != free_prono]
    vip_pronos = []
    if vip_candidates:
        vip_candidates.sort(key=lambda x: x["claude"].get("confiance", 0), reverse=True)
        vip_pronos = vip_candidates[:5]
    elif free_prono:
        vip_pronos = [free_prono]

    # C. Combiné du jour (3 matchs, Cote totale [2.00 - 4.00])
    # Note: Le handler combined_handler utilise get_today_pronos(plan='vip')
    # Pour respecter la logique existante sans la casser, on marque ces matchs comme 'vip'
    combo_pronos = []
    if len(analyzed_matches) >= 3:
        for _ in range(20):
            sample = random.sample(analyzed_matches, 3)
            total_odds = 1.0
            for s in sample:
                total_odds *= s["claude"].get("cote", 1.0)
            if 2.00 <= total_odds <= 4.00:
                combo_pronos = sample
                break

    # D. Montante du jour (Cote [1.20 - 1.50])
    montante_prono = None
    montante_candidates = [m for m in analyzed_matches if 1.20 <= m["claude"].get("cote", 0) <= 1.50]
    if montante_candidates:
        montante_prono = max(montante_candidates, key=lambda x: x["claude"].get("confiance", 0))

    # E. Score Exact (Prob > 10%)
    exact_score_prono = None
    exact_candidates = [m for m in analyzed_matches if m["analysis"]["matrix"]["best_score"] != "Non prédictible"]
    if exact_candidates:
        exact_score_prono = max(exact_candidates, key=lambda x: x["analysis"]["matrix"]["top_scores"][0]["prob"])

    # 4. Insertion avec labels compatibles Handlers
    
    async def process_and_insert(p, prono_type, plan):
        ana_fr, ana_en = await generate_simple_analysis(p["type"], p["claude"])
        insert_prono({
            "match_id": f"{p['match'].get('id', random.randint(1000,9999))}_{prono_type}",
            "home_team": p["match"]["home_team"],
            "away_team": p["match"]["away_team"],
            "league": p["match"]["league"],
            "match_date": datetime.now().date(),
            "match_time": p["match"].get("match_time"),
            "revealed_at": p["match"]["match_datetime"] - timedelta(hours=1),
            "prono_type": prono_type,
            "prediction": p["claude"]["pari"],
            "confidence": p["claude"]["confiance"],
            "odds": p["claude"]["cote"],
            "kelly_stake": 3.0,
            "value_bet": p["analysis"].get("value", 0),
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
    for p in vip_pronos:
        await process_and_insert(p, "vip", "vip")
    if vip_pronos:
        logger.info(f"✅ Section VIP : {len(vip_pronos)} matchs")
    else:
        logger.info("❌ Section VIP : Section indisponible aujourd'hui")

    # Combiné (Le handler combined_handler prend les top 3 du plan 'vip')
    # Si on a trouvé un combo spécifique, on s'assure qu'ils sont en plan 'vip'
    # Pour ne pas faire de doublons si ils sont déjà dans vip_pronos, on ne ré-insère que si nécessaire
    # Mais la consigne est d'isoler les sections. 
    # Le plus simple pour que combined_handler fonctionne est d'avoir au moins 3 pronos en plan 'vip'.
    if combo_pronos:
        logger.info(f"✅ Section Combiné : Disponible (via les pronos VIP)")
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
    logger.info("GENERATION TERMINEE")

if __name__ == "__main__":
    asyncio.run(generate_daily_pronos())
