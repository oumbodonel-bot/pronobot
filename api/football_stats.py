"""
API-Football (RapidAPI) - Stats reelles des equipes
Remplace football-data.org (plan gratuit = 100 req/jour, pas de blocage 403)
"""
import os
import httpx
import asyncio
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

API_FOOTBALL_KEY  = os.getenv("API_FOOTBALL_KEY", "")
API_FOOTBALL_BASE = "https://api-football-v1.p.rapidapi.com/v3"

HEADERS = {
    "X-RapidAPI-Key":  API_FOOTBALL_KEY,
    "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com",
}

_last_call = 0.0


async def _call(endpoint: str, params: dict) -> Optional[Dict]:
    """Appel avec rate limiting (2s minimum entre requetes)."""
    global _last_call
    import time
    elapsed = time.time() - _last_call
    if elapsed < 2.0:
        await asyncio.sleep(2.0 - elapsed)
    _last_call = time.time()

    url = f"{API_FOOTBALL_BASE}/{endpoint}"
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.get(url, headers=HEADERS, params=params)
            if r.status_code == 200:
                data = r.json()
                results = data.get("response", [])
                if results:
                    return data
                logger.warning(f"API-Football reponse vide: {endpoint} {params}")
            elif r.status_code == 429:
                logger.warning("Rate limit API-Football, attente 30s...")
                await asyncio.sleep(30)
            else:
                logger.warning(f"API-Football {r.status_code}: {endpoint}")
        except Exception as e:
            logger.error(f"API-Football error: {e}")
    return None


async def get_team_id_by_name(team_name: str) -> Optional[int]:
    """Cherche l'ID d'une equipe par son nom."""
    if not API_FOOTBALL_KEY:
        logger.error("API_FOOTBALL_KEY manquant!")
        return None

    data = await _call("teams", {"search": team_name})
    if not data:
        return None

    teams = data.get("response", [])
    if not teams:
        return None

    # Prendre le premier résultat le plus proche
    return teams[0]["team"]["id"]


async def get_team_form(team_id: int) -> Optional[Dict]:
    """
    Retourne les vraies stats de l'equipe via API-Football :
    forme recente, buts marques/encaisses, xG approche
    """
    if not team_id or not API_FOOTBALL_KEY:
        return None

    # Récupérer les 10 derniers matchs terminés
    data = await _call("fixtures", {
        "team":   team_id,
        "last":   10,
        "status": "FT",  # Full Time uniquement
    })

    if not data:
        return None

    fixtures = data.get("response", [])
    if not fixtures:
        return None

    goals_scored   = []
    goals_conceded = []
    form           = []

    for fixture in fixtures[-6:]:  # 6 derniers matchs
        teams = fixture.get("teams", {})
        goals = fixture.get("goals", {})

        is_home = teams.get("home", {}).get("id") == team_id

        if is_home:
            gs = goals.get("home")
            gc = goals.get("away")
        else:
            gs = goals.get("away")
            gc = goals.get("home")

        if gs is None or gc is None:
            continue

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
