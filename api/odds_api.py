"""
The Odds API - Vraies cotes bookmakers
Marches : h2h (1X2), spreads (handicap), totals (Over/Under)
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
    """
    Recupere les vraies cotes du jour pour 3 marches :
    - h2h     : 1X2
    - spreads : Handicap
    - totals  : Over/Under
    """
    all_matches = []
    if not ODDS_API_KEY:
        logger.error("ODDS_API_KEY manquant!")
        return []

    async with httpx.AsyncClient(timeout=20) as client:
        for sport in SPORTS:
            try:
                url = f"{ODDS_API_BASE}/sports/{sport}/odds"
                params = {
                    "apiKey":     ODDS_API_KEY,
                    "regions":    "eu",
                    "markets":    "h2h,spreads,totals",
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

                        h2h     = _extract_h2h(event)
                        spreads = _extract_spreads(event)
                        totals  = _extract_totals(event)

                        if not h2h.get("home"):
                            continue

                        all_matches.append({
                            "id":             event.get("id"),
                            "sport":          sport,
                            "home_team":      event.get("home_team"),
                            "away_team":      event.get("away_team"),
                            "league":         event.get("sport_title"),
                            "match_datetime": match_dt,
                            "match_time":     match_dt.strftime("%H:%M"),
                            "odds_home":      h2h.get("home"),
                            "odds_draw":      h2h.get("draw"),
                            "odds_away":      h2h.get("away"),
                            "handicap_home":      spreads.get("home_odds"),
                            "handicap_home_line": spreads.get("home_line"),
                            "handicap_away":      spreads.get("away_odds"),
                            "handicap_away_line": spreads.get("away_line"),
                            "over_odds":  totals.get("over_odds"),
                            "over_line":  totals.get("line"),
                            "under_odds": totals.get("under_odds"),
                        })
                        count += 1
                    logger.info(f"  => {count} matchs aujourd'hui")

                elif r.status_code == 401:
                    logger.error("CLE API ODDS INVALIDE!")
                    return []
                elif r.status_code == 422:
                    logger.info(f"  [{sport}] pas de saison active")
                elif r.status_code == 429:
                    logger.warning("QUOTA MENSUEL ATTEINT!")
                    break

            except Exception as e:
                logger.error(f"Erreur [{sport}]: {e}")
                continue

    logger.info(f"TOTAL matchs : {len(all_matches)}")
    return all_matches


def _extract_h2h(event):
    home_team = event.get("home_team", "")
    away_team = event.get("away_team", "")
    h, d, a = [], [], []
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != "h2h":
                continue
            for o in market.get("outcomes", []):
                p = float(o.get("price", 0))
                if p <= 1.0: continue
                if o["name"] == home_team: h.append(p)
                elif o["name"] == away_team: a.append(p)
                elif o["name"] == "Draw": d.append(p)
    return {
        "home": round(sum(h)/len(h), 2) if h else None,
        "draw": round(sum(d)/len(d), 2) if d else None,
        "away": round(sum(a)/len(a), 2) if a else None,
    }


def _extract_spreads(event):
    home_team = event.get("home_team", "")
    away_team = event.get("away_team", "")
    ho, hl, ao, al = [], [], [], []
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != "spreads": continue
            for o in market.get("outcomes", []):
                p = float(o.get("price", 0))
                pt = o.get("point", 0)
                if p <= 1.0: continue
                if o["name"] == home_team: ho.append(p); hl.append(pt)
                elif o["name"] == away_team: ao.append(p); al.append(pt)
    return {
        "home_odds": round(sum(ho)/len(ho), 2) if ho else None,
        "home_line": round(sum(hl)/len(hl), 2) if hl else None,
        "away_odds": round(sum(ao)/len(ao), 2) if ao else None,
        "away_line": round(sum(al)/len(al), 2) if al else None,
    }


def _extract_totals(event):
    ov, un, li = [], [], []
    for bm in event.get("bookmakers", []):
        for market in bm.get("markets", []):
            if market.get("key") != "totals": continue
            for o in market.get("outcomes", []):
                p = float(o.get("price", 0))
                pt = o.get("point", 2.5)
                if p <= 1.0: continue
                if o["name"] == "Over": ov.append(p); li.append(pt)
                elif o["name"] == "Under": un.append(p)
    return {
        "over_odds":  round(sum(ov)/len(ov), 2) if ov else None,
        "under_odds": round(sum(un)/len(un), 2) if un else None,
        "line":       round(sum(li)/len(li), 2) if li else None,
    }


def is_valid_individual_odds(odds):
    return odds is not None and 1.30 <= odds <= 2.20

def is_valid_montante_odds(odds):
    return odds is not None and 1.20 <= odds <= 1.50
