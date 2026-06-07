"""
Generateur de Pronostics Quotidiens - VERSION FINALE
=====================================================
- The Odds API : vraies cotes bookmakers
- football-data.org : vraies stats equipes
- Claude sonnet-4-6 : vraies analyses
- ZERO valeurs par defaut
- Si pas de match sur -> "Pas de prono aujourd'hui"

REGLES STRICTES :
- Prono individuel  : cote 1.30 - 2.20
- Montante          : 1 seul match, cote 1.20 - 1.50
- Combine           : 3 matchs, cote totale MAX 3.00
- Selection         : uniquement les matchs les plus surs
"""

import asyncio
import os
import sys
import json
import logging
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database    import init_db, insert_prono
from core.math_engine import full_analysis
from api.odds_api     import get_todays_odds, get_best_individual_bet, get_montante_bet
from api.football_stats import get_team_form, get_team_id_by_name
from api.claude_ai    import (
    generate_match_analysis,
    generate_montante_analysis,
    generate_combined_analysis,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ── Criteres de selection ──
MIN_STARS          = 3     # Confiance minimum (sur 5)
MAX_FREE_PRONOS    = 1
MAX_VIP_PRONOS     = 5
COMBO_MAX_ODDS     = 3.00  # Cote max du combine
COMBO_COUNT        = 3     # Nombre de matchs dans le combine


async def get_team_stats(home_team: str, away_team: str):
    """Recupere les vraies stats des deux equipes."""
    home_stats = None
    away_stats = None

    try:
        home_id = await get_team_id_by_name(home_team)
        if home_id:
            home_stats = await get_team_form(home_id)
            logger.info(f"    Stats {home_team}: {home_stats.get('form_string','?') if home_stats else 'non trouvees'}")
    except Exception as e:
        logger.warning(f"    Stats {home_team} indisponibles: {e}")

    try:
        away_id = await get_team_id_by_name(away_team)
        if away_id:
            away_stats = await get_team_form(away_id)
            logger.info(f"    Stats {away_team}: {away_stats.get('form_string','?') if away_stats else 'non trouvees'}")
    except Exception as e:
        logger.warning(f"    Stats {away_team} indisponibles: {e}")

    return home_stats, away_stats


def score_match(match: Dict, math: Dict) -> float:
    """
    Score de selection d'un match (plus c'est eleve, plus c'est sur).
    Basé sur : value bet + confiance + forme + cote dans la plage
    """
    score = 0.0

    # Value Bet positif = bonus majeur
    if math.get("has_value"):
        score += 3.0
    score += math.get("value_bet", 0) * 0.1

    # Etoiles de confiance
    score += math.get("stars", 0)

    # Probabilite du meilleur pari
    score += math.get("best_prob", 0) * 0.05

    # Cote dans la plage ideale (1.30-1.80 = tres sur)
    odds = match.get("best_odds", 0)
    if 1.30 <= odds <= 1.80:
        score += 2.0
    elif 1.80 < odds <= 2.20:
        score += 1.0

    return round(score, 3)


async def process_match(match: Dict) -> Optional[Dict]:
    """
    Traite un match complet :
    1. Determine le meilleur pari (cote 1.30-2.20)
    2. Recupere les vraies stats
    3. Calcule les probabilites mathematiques
    4. Valide les criteres de selection
    Retourne les donnees du prono ou None si non selectionne.
    """
    home = match["home_team"]
    away = match["away_team"]

    # 1. Verifier que le pari est dans la plage valide
    prediction, odds, is_valid = get_best_individual_bet(
        match.get("odds_home"),
        match.get("odds_draw"),
        match.get("odds_away"),
    )

    if not is_valid:
        return None

    match["best_prediction"] = prediction
    match["best_odds"]       = odds

    # 2. Recuperer les vraies stats
    home_stats, away_stats = await get_team_stats(home, away)

    # Stats minimales disponibles ?
    # Si aucune stat dispo -> on peut quand meme faire un prono
    # mais on baisse la confiance
    _home = home_stats or {"avg_scored": 0, "avg_conceded": 0, "form_score": 0.5, "xg": 0}
    _away = away_stats or {"avg_scored": 0, "avg_conceded": 0, "form_score": 0.5, "xg": 0}

    # 3. Calculs mathematiques
    math = full_analysis(
        home_stats = _home,
        away_stats = _away,
        odds_home  = match.get("odds_home", odds),
        odds_draw  = match.get("odds_draw"),
        odds_away  = match.get("odds_away", odds),
    )

    # 4. Criteres de selection
    if math["stars"] < MIN_STARS:
        logger.info(f"    {home} vs {away} : confiance insuffisante ({math['stars']}/5)")
        return None

    # Score de selection
    selection_score = score_match(match, math)
    logger.info(
        f"    {home} vs {away} : "
        f"prediction={prediction} @ {odds} | "
        f"stars={math['stars']}/5 | "
        f"value={math['value_bet']}% | "
        f"score={selection_score}"
    )

    return {
        "match":       match,
        "home_stats":  home_stats,
        "away_stats":  away_stats,
        "math":        math,
        "prediction":  prediction,
        "odds":        odds,
        "score":       selection_score,
    }


async def build_prono_record(
    processed: Dict,
    plan_required: str,
    prono_type: str,
) -> Dict:
    """
    Construit le dictionnaire complet pour insertion en base.
    Appelle Claude pour l'analyse narrative.
    """
    match      = processed["match"]
    math       = processed["math"]
    home_stats = processed["home_stats"]
    away_stats = processed["away_stats"]
    prediction = processed["prediction"]
    odds       = processed["odds"]

    # Analyse Claude reelle
    analysis_fr, analysis_en = await generate_match_analysis(
        home_team  = match["home_team"],
        away_team  = match["away_team"],
        league     = match["league"],
        home_stats = home_stats,
        away_stats = away_stats,
        math_results = math,
        prediction = prediction,
        odds       = odds,
    )

    # revealed_at = 1h avant le match
    match_datetime = match.get("match_datetime")
    if match_datetime:
        if match_datetime.tzinfo is None:
            match_datetime = match_datetime.replace(tzinfo=timezone.utc)
        revealed_at = match_datetime - timedelta(hours=1)
    else:
        revealed_at = datetime.now(timezone.utc)

    return {
        "match_id":      str(match.get("id", "")),
        "home_team":     match["home_team"],
        "away_team":     match["away_team"],
        "league":        match["league"],
        "match_date":    date.today(),
        "match_time":    match.get("match_time"),
        "revealed_at":   revealed_at,
        "prono_type":    prono_type,
        "prediction":    prediction,
        "confidence":    math["stars"],
        "odds":          odds,
        "kelly_stake":   math["kelly_stake"],
        "value_bet":     math["value_bet"],
        "analysis_fr":   json.dumps(analysis_fr, ensure_ascii=False),
        "analysis_en":   json.dumps(analysis_en, ensure_ascii=False),
        "exact_score":   json.dumps(math["top_scores"], ensure_ascii=False),
        "plan_required": plan_required,
    }


async def generate_daily_pronos():
    """Script principal - lance chaque jour a 09h00 UTC."""
    init_db()
    today = date.today()

    logger.info(f"\n{'='*55}")
    logger.info(f"  GENERATION PRONOS — {today}")
    logger.info(f"{'='*55}\n")

    # ════════════════════════════════════════════════════
    # ETAPE 1 : Recuperer les vraies cotes du jour
    # ════════════════════════════════════════════════════
    logger.info("ETAPE 1 : Recuperation des vraies cotes (The Odds API)...")
    all_matches = await get_todays_odds()

    if not all_matches:
        logger.warning("\n❌ AUCUN MATCH TROUVE AUJOURD'HUI.")
        logger.warning("Pas de prono genere. Rendez-vous demain!")
        return

    logger.info(f"✅ {len(all_matches)} matchs avec cotes reelles trouves\n")

    # ════════════════════════════════════════════════════
    # ETAPE 2 : Filtrer et scorer chaque match
    # ════════════════════════════════════════════════════
    logger.info("ETAPE 2 : Analyse et selection des matchs...")
    processed_matches = []

    for match in all_matches:
        logger.info(f"\n  Traitement: {match['home_team']} vs {match['away_team']} ({match['league']})")
        try:
            result = await process_match(match)
            if result:
                processed_matches.append(result)
        except Exception as e:
            logger.error(f"  Erreur: {e}")
            continue

    if not processed_matches:
        logger.warning("\n❌ AUCUN MATCH NE REPOND AUX CRITERES AUJOURD'HUI.")
        logger.warning("Confiance insuffisante ou cotes hors plage (1.30-2.20).")
        logger.warning("Pas de prono genere. La qualite prime sur la quantite!")
        return

    # Trier par score de selection (meilleur en premier)
    processed_matches.sort(key=lambda x: x["score"], reverse=True)
    logger.info(f"\n✅ {len(processed_matches)} matchs selectionnes (sur {len(all_matches)})\n")

    # ════════════════════════════════════════════════════
    # ETAPE 3 : Generer les pronos
    # ════════════════════════════════════════════════════
    logger.info("ETAPE 3 : Generation des pronos...\n")

    free_count = 0
    vip_count  = 0
    vip_records = []  # Pour combiné et montante

    for processed in processed_matches:
        if free_count >= MAX_FREE_PRONOS and vip_count >= MAX_VIP_PRONOS:
            break

        if free_count < MAX_FREE_PRONOS:
            plan   = "free"
            ptype  = "free"
        elif vip_count < MAX_VIP_PRONOS:
            plan   = "vip"
            ptype  = "vip"
        else:
            break

        try:
            logger.info(f"  [{plan.upper()}] {processed['match']['home_team']} vs {processed['match']['away_team']}")
            record = await build_prono_record(processed, plan, ptype)
            prono_id = insert_prono(record)
            logger.info(f"  ✅ Insere en base (ID: {prono_id})")

            if plan == "free":
                free_count += 1
            else:
                vip_count  += 1
                vip_records.append({**processed, "record": record})

        except Exception as e:
            logger.error(f"  ❌ Erreur insertion: {e}")
            continue

    # ════════════════════════════════════════════════════
    # ETAPE 4 : Score exact (meilleur match VIP)
    # ════════════════════════════════════════════════════
    if vip_records:
        best_vip = vip_records[0]
        math     = best_vip["math"]
        match    = best_vip["match"]
        logger.info(f"\n  🎰 Score exact : {math['best_score']} (match: {match['home_team']} vs {match['away_team']})")

        exact_record = {**best_vip["record"]}
        exact_record["prono_type"]    = "exact_score"
        exact_record["prediction"]    = math["best_score"]
        exact_record["plan_required"] = "vip"
        exact_record["match_id"]      = str(match.get("id","")) + "_exact"
        insert_prono(exact_record)
        logger.info(f"  ✅ Score exact insere : {math['best_score']}")

    # ════════════════════════════════════════════════════
    # ETAPE 5 : Combine du jour (3 matchs, cote max 3.00)
    # ════════════════════════════════════════════════════
    if len(vip_records) >= COMBO_COUNT:
        logger.info(f"\n  🎯 Generation du combine ({COMBO_COUNT} matchs, cote max {COMBO_MAX_ODDS})...")

        combo_candidates = vip_records[:COMBO_COUNT]
        total_odds = 1.0
        for c in combo_candidates:
            total_odds *= c["odds"]
        total_odds = round(total_odds, 2)

        if total_odds <= COMBO_MAX_ODDS:
            combo_matches = [{
                "home_team":  c["match"]["home_team"],
                "away_team":  c["match"]["away_team"],
                "prediction": c["prediction"],
                "odds":       c["odds"],
            } for c in combo_candidates]

            analysis_fr, analysis_en = await generate_combined_analysis(combo_matches, total_odds)

            # Revealed_at = 1h avant le premier match du combine
            first_dt = min(
                (c["match"]["match_datetime"] for c in combo_candidates if c["match"].get("match_datetime")),
                default=None
            )
            if first_dt:
                if first_dt.tzinfo is None:
                    first_dt = first_dt.replace(tzinfo=timezone.utc)
                revealed_at = first_dt - timedelta(hours=1)
            else:
                revealed_at = datetime.now(timezone.utc)

            lines = [f"{m['home_team']} vs {m['away_team']} → {m['prediction']} @ {m['odds']}"
                     for m in combo_matches]

            insert_prono({
                "match_id":      f"combined_{today}",
                "home_team":     "Combine du Jour",
                "away_team":     f"{COMBO_COUNT} matchs selectiones",
                "league":        "Multi-ligues",
                "match_date":    today,
                "match_time":    first_dt.strftime("%H:%M") if first_dt else None,
                "revealed_at":   revealed_at,
                "prono_type":    "combined",
                "prediction":    " | ".join(lines),
                "confidence":    4,
                "odds":          total_odds,
                "kelly_stake":   3.0,
                "value_bet":     0.0,
                "analysis_fr":   json.dumps(analysis_fr, ensure_ascii=False),
                "analysis_en":   json.dumps(analysis_en, ensure_ascii=False),
                "exact_score":   None,
                "plan_required": "vip",
            })
            logger.info(f"  ✅ Combine insere — Cote totale : {total_odds}")
        else:
            logger.warning(f"  ⚠️ Cote combine trop elevee ({total_odds} > {COMBO_MAX_ODDS}), non genere")

    # ════════════════════════════════════════════════════
    # ETAPE 6 : Montante (1 seul match, cote 1.20-1.50)
    # ════════════════════════════════════════════════════
    logger.info("\n  📈 Generation de la montante (1 match, cote 1.20-1.50)...")
    montante_done = False

    for match in all_matches:
        pred, odds, valid = get_montante_bet(
            match.get("odds_home"),
            match.get("odds_draw"),
            match.get("odds_away"),
        )

        if not valid:
            continue

        home_stats, away_stats = await get_team_stats(match["home_team"], match["away_team"])
        _home = home_stats or {"avg_scored": 0, "avg_conceded": 0, "form_score": 0.5, "xg": 0}
        _away = away_stats or {"avg_scored": 0, "avg_conceded": 0, "form_score": 0.5, "xg": 0}

        math = full_analysis(
            home_stats = _home,
            away_stats = _away,
            odds_home  = match.get("odds_home", odds),
            odds_draw  = match.get("odds_draw"),
            odds_away  = match.get("odds_away", odds),
        )

        montante_info = {
            "home_team":  match["home_team"],
            "away_team":  match["away_team"],
            "league":     match["league"],
            "prediction": pred,
            "odds":       odds,
            "prob":       math["best_prob"],
            "stars":      math["stars"],
        }

        analysis_fr, analysis_en = await generate_montante_analysis(montante_info)

        match_datetime = match.get("match_datetime")
        if match_datetime:
            if match_datetime.tzinfo is None:
                match_datetime = match_datetime.replace(tzinfo=timezone.utc)
            revealed_at = match_datetime - timedelta(hours=1)
        else:
            revealed_at = datetime.now(timezone.utc)

        insert_prono({
            "match_id":      str(match.get("id","")) + "_montante",
            "home_team":     match["home_team"],
            "away_team":     match["away_team"],
            "league":        match["league"],
            "match_date":    today,
            "match_time":    match.get("match_time"),
            "revealed_at":   revealed_at,
            "prono_type":    "montante",
            "prediction":    pred,
            "confidence":    math["stars"],
            "odds":          odds,
            "kelly_stake":   5.0,
            "value_bet":     math["value_bet"],
            "analysis_fr":   json.dumps(analysis_fr, ensure_ascii=False),
            "analysis_en":   json.dumps(analysis_en, ensure_ascii=False),
            "exact_score":   None,
            "plan_required": "vip",
        })
        logger.info(f"  ✅ Montante : {match['home_team']} vs {match['away_team']} → {pred} @ {odds}")
        montante_done = True
        break  # UN SEUL match pour la montante

    if not montante_done:
        logger.warning("  ⚠️ Aucun match avec cote 1.20-1.50 disponible aujourd'hui pour la montante")

    # ════════════════════════════════════════════════════
    # RESUME FINAL
    # ════════════════════════════════════════════════════
    logger.info(f"\n{'='*55}")
    logger.info(f"  GENERATION TERMINEE")
    logger.info(f"  Pronos gratuits : {free_count}/{MAX_FREE_PRONOS}")
    logger.info(f"  Pronos VIP      : {vip_count}/{MAX_VIP_PRONOS}")
    logger.info(f"  Score exact     : {'✅' if vip_records else '❌'}")
    logger.info(f"  Combine         : {'✅' if len(vip_records) >= COMBO_COUNT else '❌'}")
    logger.info(f"  Montante        : {'✅' if montante_done else '❌'}")
    logger.info(f"{'='*55}\n")


from typing import Optional, Dict

if __name__ == "__main__":
    asyncio.run(generate_daily_pronos())
