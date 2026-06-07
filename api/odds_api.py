"""
The Odds API - Vraies cotes bookmakers
Plan gratuit : 500 requetes/mois
"""
import os
import httpx
import logging
from datetime import date, datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

ODDS_API_KEY  = os.getenv("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

SPORTS = [
    "soccer_fifa_world_cup",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_france_ligue_one",
    "soccer_germany_bundesliga",
    "soccer_brazil_campeonato",
    "soccer_finland_veikkausliiga",
    "soccer_league_of_ireland",
    "soccer_brazil_serie_b",
]


async def get_todays_odds() -> List[Dict]:
    """Recupere les vraies cotes du jour via The Odds API."""
    all_matches = []

    if not ODDS_API_KEY:
        logger.error("ODDS_API_KEY manquant dans les variables d'environnement!")
        return []

    async with httpx.AsyncClient(timeout=15) as client:
        for sport in SPORTS:
            try:
                url = f"{ODDS_API_BASE}/sports/{sport}/odds"
                params = {
                    "apiKey":     ODDS_API_KEY,
                    "regions":    "eu",
                    "markets":    "h2h",
                    "oddsFormat": "decimal",
                    "dateFormat": "iso",
                }
                r = await client.get(url, params=params)
                remaining = r.headers.get("x-requests-remaining", "?")
                logger.info(f"  [{sport}] status={r.status_code} remaining={remaining}")

                if r.status_code == 200:
                    events = r.json()
                    count = 0
                    for event in events:
                        commence_time = event.get("commence_time", "")
                        if not commence_time:
                            continue
                        try:
                            match_dt = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
                            if match_dt.date() != date.today():
                                continue
                        except:
                            continue

                        home_odds, draw_odds, away_odds = _extract_odds(event)
                        if not home_odds:
                            continue

                        all_matches.append({
                            "id":             event.get("id"),
                            "sport":          sport,
                            "home_team":      event.get("home_team"),
                            "away_team":      event.get("away_team"),
                            "league":         event.get("sport_title"),
                            "match_datetime": match_dt,
                            "match_time":     match_dt.strftime("%H:%M"),
                            "odds_home":      home_odds,
                            "odds_draw":      draw_odds,
                            "odds_away":      away_odds,
                        })
                        count += 1
                    logger.info(f"  => {count} matchs aujourd'hui")

                elif r.status_code == 401:
                    logger.error("CLE API ODDS INVALIDE! Verifier ODDS_API_KEY dans Railway")
                    return []
                elif r.status_code == 422:
                    logger.info(f"  [{sport}] pas de saison active")
                elif r.status_code == 429:
                    logger.warning("QUOTA MENSUEL ODDS API ATTEINT!")
                    break
                else:
                    logger.warning(f"  [{sport}] erreur {r.status_code}")

            except Exception as e:
                logger.error(f"Erreur [{sport}]: {e}")
                continue

    logger.info(f"TOTAL matchs avec vraies cotes : {len(all_matches)}")
    return all_matches


def _extract_odds(event: dict) -> tuple:
    """Extrait la moyenne des cotes de tous les bookmakers."""
    home_team = event.get("home_team", "")
    away_team = event.get("away_team", "")
    h, d, a   = [], [], []

    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes", []):
                name  = outcome.get("name", "")
                price = float(outcome.get("price", 0))
                if price <= 1.0:
                    continue
                if name == home_team:
                    h.append(price)
                elif name == away_team:
                    a.append(price)
                elif name == "Draw":
                    d.append(price)

    home = round(sum(h) / len(h), 2) if h else None
    draw = round(sum(d) / len(d), 2) if d else None
    away = round(sum(a) / len(a), 2) if a else None
    return home, draw, away


def get_best_individual_bet(home_odds, draw_odds, away_odds) -> tuple:
    """
    Meilleur pari individuel : cote entre 1.30 et 2.20 UNIQUEMENT.
    Retourne (label, odds, est_valide)
    """
    candidates = []
    if home_odds and 1.30 <= home_odds <= 2.20:
        candidates.append(("Victoire domicile (1)", home_odds))
    if away_odds and 1.30 <= away_odds <= 2.20:
        candidates.append(("Victoire exterieur (2)", away_odds))
    if draw_odds and 1.30 <= draw_odds <= 2.20:
        candidates.append(("Match nul (X)", draw_odds))

    if not candidates:
        return None, None, False

    # Meilleure cote dans la plage
    best = max(candidates, key=lambda x: x[1])
    return best[0], best[1], True


def get_montante_bet(home_odds, draw_odds, away_odds) -> tuple:
    """
    Pari montante : cote entre 1.20 et 1.50 UNIQUEMENT.
    Retourne (label, odds, est_valide)
    """
    candidates = []
    if home_odds and 1.20 <= home_odds <= 1.50:
        candidates.append(("Victoire domicile (1)", home_odds))
    if away_odds and 1.20 <= away_odds <= 1.50:
        candidates.append(("Victoire exterieur (2)", away_odds))
    if draw_odds and 1.20 <= draw_odds <= 1.50:
        candidates.append(("Match nul (X)", draw_odds))

    if not candidates:
        return None, None, False

    best = max(candidates, key=lambda x: x[1])
    return best[0], best[1], True
