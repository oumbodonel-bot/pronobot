"""
Football Data API - Stats reelles des equipes
football-data.org (plan gratuit)
"""
import os
import httpx
import asyncio
import logging
from datetime import date
from typing import Dict, Optional

logger = logging.getLogger(__name__)

FOOTBALL_DATA_KEY  = os.getenv("FOOTBALL_DATA_API_KEY", "")
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

_last_call = 0.0


async def _call(endpoint: str) -> Optional[Dict]:
    """Appel avec rate limiting (6s minimum entre requetes)."""
    global _last_call
    import time
    elapsed = time.time() - _last_call
    if elapsed < 6.0:
        await asyncio.sleep(6.0 - elapsed)
    _last_call = time.time()

    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    url = f"{FOOTBALL_DATA_BASE}/{endpoint}"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(url, headers=headers)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 429:
                logger.warning("Rate limit football-data.org, attente 60s...")
                await asyncio.sleep(60)
            else:
                logger.warning(f"football-data {r.status_code}: {endpoint}")
        except Exception as e:
            logger.error(f"football-data error: {e}")
    return None


async def get_team_form(team_id: int) -> Optional[Dict]:
    """
    Retourne les vraies stats de l'equipe :
    forme recente, buts marques/encaisses, xG approche
    """
    if not team_id:
        return None

    data = await _call(f"teams/{team_id}/matches?limit=10&status=FINISHED")
    if not data:
        return None

    matches = data.get("matches", [])
    if not matches:
        return None

    goals_scored    = []
    goals_conceded  = []
    form            = []

    for m in matches[-6:]:  # 6 derniers matchs
        score = m.get("score", {}).get("fullTime", {})
        hs    = score.get("home")
        as_   = score.get("away")
        if hs is None or as_ is None:
            continue

        is_home = m["homeTeam"]["id"] == team_id
        gs  = hs if is_home else as_
        gc  = as_ if is_home else hs

        goals_scored.append(gs)
        goals_conceded.append(gc)

        if gs > gc:
            form.append("W")
        elif gs == gc:
            form.append("D")
        else:
            form.append("L")

    if not goals_scored:
        return None

    avg_scored   = round(sum(goals_scored)   / len(goals_scored),   2)
    avg_conceded = round(sum(goals_conceded) / len(goals_conceded), 2)
    form_score   = round(
        (form.count("W") * 1.0 + form.count("D") * 0.4) / len(form), 3
    )

    return {
        "avg_scored":   avg_scored,
        "avg_conceded": avg_conceded,
        "form":         form,
        "form_string":  "".join(form),
        "form_score":   form_score,
        "xg":           round(avg_scored * 0.92, 2),
    }


async def get_team_id_by_name(team_name: str) -> Optional[int]:
    """Cherche l'ID d'une equipe par son nom."""
    data = await _call(f"teams?name={team_name}")
    if not data:
        return None
    teams = data.get("teams", [])
    return teams[0]["id"] if teams else None
