"""
Generateur de Pronostics Quotidiens - VERSION CLAUDE JUDGE
==========================================================
- The Odds API : vraies cotes (1X2 + Handicap + Over/Under)
- football-data.org : vraies stats equipes
- Claude : seul juge qui valide ou rejette chaque match
- ZERO filtre rigide en amont
- Regles fixes : cote 1.40-2.00, montante 1.20-1.50, combine max 4.00
"""

import asyncio
import os
import sys
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.database      import init_db, insert_prono
from core.math_engine   import full_analysis
from api.odds_api       import get_todays_odds, is_valid_montante_odds
from api.football_stats import get_team_form, get_team_id_by_name
from api.claude_ai      import (
    evaluate_match,
    generate_montante_analysis,
    generate_combined_analysis,
)

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

MAX_FREE_PRONOS = 1
MAX_VIP_PRONOS  = 5
COMBO_MAX_ODDS  = 4.00
COMBO_COUNT     = 3


async def get_team_stats(home_team: str, away_team: str):
    """Recupere les vraies stats des deux equipes via football-data.org."""
    home_stats = None
    away_stats = None

    try:
        home_id = await get_team_id_by_name(home_team)
        if home_id:
            home_stats = await get_team_form(home_id)
            logger.info(f"    Stats {home_team}: {home_stats.get('form_string','?') if home_stats else 'N/A'}")
    except Exception as e:
        logger.warning(f"    Stats {home_team} indisponibles: {e}")

    try:
        away_id = await get_team_id_by_name(away_team)
        if away_id:
            away_stats = await get_team_form(away_id)
            logger.info(f"    Stats {away_team}: {away_stats.get('form_string','?') if away_stats else 'N/A'}")
    except Exception as e:
        logger.warning(f"    Stats {away_team} indisponibles: {e}")

    return home_stats, away_stats


def build_revealed_at(match_datetime) -> datetime:
    """Calcule revealed_at = 1h avant le match."""
    if not match_datetime:
        return datetime.now(timezone.utc)
    if match_datetime.tzinfo is None:
        match_datetime = match_datetime.replace(tzinfo=timezone.utc)
    return match_datetime - timedelta(hours=1)


async def process_match_with_claude(match: Dict) -> Optional[Dict]:
    """
    Traitement complet d'un match :
    1. Recupere les stats reelles
    2. Calcule les probabilites mathematiques
    3. Envoie TOUT a Claude sans filtre
    4. Claude decide : VALIDE ou REJETE
    Retourne les donnees du prono ou None si rejete.
    """
    home = match["home_team"]
    away = match["away_team"]
    logger.info(f"\n  Traitement: {home} vs {away} ({match['league']})")

    # 1. Stats reelles
    home_stats, away_stats = await get_team_stats(home, away)

   math = full_analysis(odds_data=match, home_stats=home_stats, away_stats=away_stats)

    # 2. Calculs mathematiques Poisson + Dixon-Coles
    math = full_analysis(
    odds_data  = match,           # ← dict complet du match
    home_stats = home_stats,      # ← None si indispo, c'est normal
    away_stats = away_stats,
)

    # 3. Envoyer TOUT a Claude - il decide seul
    claude_result = await evaluate_match(
        home_team    = home,
        away_team    = away,
        league       = match["league"],
        home_stats   = home_stats,
        away_stats   = away_stats,
        odds_data    = match,
        math_results = math,
    )

    # 4. Verifier la decision de Claude
    if claude_result.get("decision") != "VALIDE":
        raison = claude_result.get("raison_rejet", "Non specifie")
        logger.info(f"  REJETE par Claude : {raison}")
        return None

    # Verifier que la cote choisie respecte les regles (1.40-2.00)
    cote = claude_result.get("cote_choisie")
    if not cote or not (1.40 <= cote <= 2.00):
        logger.info(f"  REJETE : cote {cote} hors plage 1.40-2.00")
        return None

    logger.info(f"  VALIDE : {claude_result.get('pronostic')} @ {cote} (confiance {claude_result.get('confiance')}/5)")

    # 5. Construire l'analyse FR/EN
    analysis_fr = {
        "analysis":   claude_result.get("analyse_fr", ""),
        "key_points": claude_result.get("points_cles_fr", []),
        "verdict":    claude_result.get("verdict_fr", ""),
    }
    analysis_en = {
        "analysis":   claude_result.get("analyse_en", ""),
        "key_points": claude_result.get("points_cles_en", []),
        "verdict":    claude_result.get("verdict_en", ""),
    }

    revealed_at = build_revealed_at(match.get("match_datetime"))

    return {
        "match_id":      str(match.get("id", "")),
        "home_team":     home,
        "away_team":     away,
        "league":        match["league"],
        "match_date":    date.today(),
        "match_time":    match.get("match_time"),
        "revealed_at":   revealed_at,
        "prono_type":    "free",
        "prediction":    claude_result.get("pronostic", ""),
        "confidence":    claude_result.get("confiance", 3),
        "odds":          cote,
        "kelly_stake":   math.get("kelly_stake", 3.0),
        "value_bet":     math.get("value_bet", 0),
        "analysis_fr":   json.dumps(analysis_fr, ensure_ascii=False),
        "analysis_en":   json.dumps(analysis_en, ensure_ascii=False),
        "exact_score":   json.dumps(math.get("top_scores", []), ensure_ascii=False),
        "plan_required": "free",
        "_marche":       claude_result.get("marche_choisi", "1X2"),
        "_confiance":    claude_result.get("confiance", 3),
        "_math":         math,
    }


async def generate_daily_pronos():
    """Script principal - 09h00 UTC chaque jour."""
    init_db()
    today = date.today()

    logger.info(f"\n{'='*60}")
    logger.info(f"  PRONOBOT — GENERATION PRONOS {today}")
    logger.info(f"  MODE : Claude est le seul juge")
    logger.info(f"{'='*60}\n")

    # ════════════════════════════════════════
    # ETAPE 1 : Vraies cotes (3 marches)
    # ════════════════════════════════════════
    logger.info("ETAPE 1 : Recuperation cotes (1X2 + Handicap + Over/Under)...")
    all_matches = await get_todays_odds()

    if not all_matches:
        logger.warning("❌ Aucun match trouve aujourd'hui!")
        return

    logger.info(f"✅ {len(all_matches)} matchs avec cotes reelles\n")

    # ════════════════════════════════════════
    # ETAPE 2 : Claude evalue chaque match
    # ════════════════════════════════════════
    logger.info("ETAPE 2 : Evaluation par Claude (sans filtre rigide)...")

    validated_matches = []
    for match in all_matches:
        try:
            result = await process_match_with_claude(match)
            if result:
                result["_match"] = match
                validated_matches.append(result)
        except Exception as e:
            logger.error(f"  Erreur: {e}")
            continue

    if not validated_matches:
        logger.warning("\n❌ Aucun match valide par Claude aujourd'hui!")
        logger.warning("Pas de prono genere. Rendez-vous demain!")
        return

    # Trier par confiance Claude (decroissant)
    validated_matches.sort(key=lambda x: x.get("_confiance", 0), reverse=True)
    logger.info(f"\n✅ {len(validated_matches)} matchs valides par Claude\n")

    # ════════════════════════════════════════
    # ETAPE 3 : Inserer les pronos en base
    # ════════════════════════════════════════
    logger.info("ETAPE 3 : Insertion des pronos...")

    free_count  = 0
    vip_count   = 0
    vip_records = []

    for processed in validated_matches:
        if free_count >= MAX_FREE_PRONOS and vip_count >= MAX_VIP_PRONOS:
            break

        if free_count < MAX_FREE_PRONOS:
            plan  = "free"
            ptype = "free"
        elif vip_count < MAX_VIP_PRONOS:
            plan  = "vip"
            ptype = "vip"
        else:
            break

        try:
            math  = processed.pop("_math", {})
            match = processed.pop("_match", {})
            processed.pop("_marche",    None)
            processed.pop("_confiance", None)

            processed["plan_required"] = plan
            processed["prono_type"]    = ptype

            prono_id = insert_prono(processed)
            logger.info(f"  [{plan.upper()}] {processed['home_team']} vs {processed['away_team']} → {processed['prediction']} @ {processed['odds']} (ID:{prono_id})")

            if plan == "free":
                free_count += 1
            else:
                vip_count  += 1
                vip_records.append({
                    "home_team":      processed["home_team"],
                    "away_team":      processed["away_team"],
                    "league":         processed["league"],
                    "prediction":     processed["prediction"],
                    "odds":           processed["odds"],
                    "match_datetime": match.get("match_datetime"),
                    "math":           math,
                    "record":         processed,
                })

        except Exception as e:
            logger.error(f"  Erreur insertion: {e}")
            if plan == "free": free_count -= 1
            else: vip_count -= 1
            continue

    # ════════════════════════════════════════
    # ETAPE 4 : Score exact
    # ════════════════════════════════════════
    exact_done = False
    if vip_records:
        best     = vip_records[0]
        math     = best["math"]
        record   = best["record"]
        best_score = math.get("best_score", "1-0")

        exact_record = {**record}
        exact_record["prono_type"]    = "exact_score"
        exact_record["prediction"]    = best_score
        exact_record["plan_required"] = "vip"
        exact_record["match_id"]      = str(record.get("match_id","")) + "_exact"
        insert_prono(exact_record)
        logger.info(f"\n  Score exact insere : {best_score}")
        exact_done = True

    # ════════════════════════════════════════
    # ETAPE 5 : Combine (3 matchs, max 4.00)
    # ════════════════════════════════════════
    combo_done = False
    if len(vip_records) >= COMBO_COUNT:
        logger.info(f"\nETAPE 5 : Generation combine...")
        candidates = vip_records[:COMBO_COUNT]
        total_odds = 1.0
        for c in candidates:
            total_odds *= c["odds"]
        total_odds = round(total_odds, 2)

        if total_odds <= COMBO_MAX_ODDS:
            combo_matches = [{
                "home_team":  c["home_team"],
                "away_team":  c["away_team"],
                "prediction": c["prediction"],
                "odds":       c["odds"],
            } for c in candidates]

            analysis_fr, analysis_en = await generate_combined_analysis(combo_matches, total_odds)

            first_dt = min(
                (c["match_datetime"] for c in candidates if c.get("match_datetime")),
                default=None
            )
            revealed_at = build_revealed_at(first_dt)

            lines = [
                f"{m['home_team']} vs {m['away_team']} → {m['prediction']} @ {m['odds']}"
                for m in combo_matches
            ]

            insert_prono({
                "match_id":      f"combined_{today}",
                "home_team":     "Combine du Jour",
                "away_team":     f"{COMBO_COUNT} matchs selectionnes par Claude",
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
            logger.info(f"  Combine insere — Cote : {total_odds}")
            combo_done = True
        else:
            logger.warning(f"  Combine rejete : cote {total_odds} > {COMBO_MAX_ODDS}")

    # ════════════════════════════════════════
    # ETAPE 6 : Montante (1 match, 1.20-1.50)
    # ════════════════════════════════════════
    montante_done = False
    logger.info("\nETAPE 6 : Recherche match pour montante (cote 1.20-1.50)...")

    for match in all_matches:
        # Trouver la meilleure cote dans la plage 1.20-1.50
        candidates = []
        if match.get("odds_home") and is_valid_montante_odds(match["odds_home"]):
            candidates.append((f"Victoire {match['home_team']} (1)", match["odds_home"]))
        if match.get("odds_away") and is_valid_montante_odds(match["odds_away"]):
            candidates.append((f"Victoire {match['away_team']} (2)", match["odds_away"]))
        if match.get("under_odds") and is_valid_montante_odds(match["under_odds"]):
            candidates.append((f"Under {match.get('under_line',2.5)} buts", match["under_odds"]))
        if match.get("over_odds") and is_valid_montante_odds(match["over_odds"]):
            candidates.append((f"Over {match.get('over_line',2.5)} buts", match["over_odds"]))

        if not candidates:
            continue

        best_pred, best_odds = max(candidates, key=lambda x: x[1])

        # Stats pour la montante
        home_stats, away_stats = await get_team_stats(match["home_team"], match["away_team"])
        _home = home_stats or {"avg_scored": 0, "avg_conceded": 0, "form_score": 0.5, "xg": 0}
        _away = away_stats or {"avg_scored": 0, "avg_conceded": 0, "form_score": 0.5, "xg": 0}
        math  = full_analysis(_home, _away,
                              match.get("odds_home", 2.0),
                              match.get("odds_draw",  3.3),
                              match.get("odds_away",  3.5))

        montante_info = {
            "home_team":  match["home_team"],
            "away_team":  match["away_team"],
            "league":     match["league"],
            "prediction": best_pred,
            "odds":       best_odds,
            "prob":       math.get("best_prob", "?"),
            "confiance":  math.get("stars", 3),
        }

        analysis_fr, analysis_en = await generate_montante_analysis(montante_info)
        revealed_at = build_revealed_at(match.get("match_datetime"))

        insert_prono({
            "match_id":      str(match.get("id","")) + "_montante",
            "home_team":     match["home_team"],
            "away_team":     match["away_team"],
            "league":        match["league"],
            "match_date":    today,
            "match_time":    match.get("match_time"),
            "revealed_at":   revealed_at,
            "prono_type":    "montante",
            "prediction":    best_pred,
            "confidence":    math.get("stars", 3),
            "odds":          best_odds,
            "kelly_stake":   5.0,
            "value_bet":     math.get("value_bet", 0),
            "analysis_fr":   json.dumps(analysis_fr, ensure_ascii=False),
            "analysis_en":   json.dumps(analysis_en, ensure_ascii=False),
            "exact_score":   None,
            "plan_required": "vip",
        })
        logger.info(f"  Montante : {match['home_team']} vs {match['away_team']} → {best_pred} @ {best_odds}")
        montante_done = True
        break

    if not montante_done:
        logger.warning("  Aucun match avec cote 1.20-1.50 aujourd'hui")

    # ════════════════════════════════════════
    # RESUME FINAL
    # ════════════════════════════════════════
    logger.info(f"\n{'='*60}")
    logger.info(f"  GENERATION TERMINEE")
    logger.info(f"  Matches evalues    : {len(all_matches)}")
    logger.info(f"  Valides par Claude : {len(validated_matches)}")
    logger.info(f"  Pronos gratuits    : {free_count}/{MAX_FREE_PRONOS}")
    logger.info(f"  Pronos VIP         : {vip_count}/{MAX_VIP_PRONOS}")
    logger.info(f"  Score exact        : {'✅' if exact_done else '❌'}")
    logger.info(f"  Combine            : {'✅' if combo_done else '❌'}")
    logger.info(f"  Montante           : {'✅' if montante_done else '❌'}")
    logger.info(f"{'='*60}\n")


if __name__ == "__main__":
    asyncio.run(generate_daily_pronos())
