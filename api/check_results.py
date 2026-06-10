"""
Vérification automatique des résultats
Utilise football-data.org UNIQUEMENT pour les scores finaux
Plan gratuit : résultats retardés OK, 10 req/min max
"""
import os
import httpx
import asyncio
import logging
from datetime import date, timedelta
from core.database import get_conn

logger = logging.getLogger(__name__)

FOOTBALL_DATA_KEY  = os.getenv("FOOTBALL_DATA_API_KEY", "")
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

LEAGUE_MAP = {
    "FIFA World Cup":         2000,
    "Premier League":         2021,
    "La Liga":                2014,
    "Serie A":                2019,
    "Ligue 1":                2015,
    "Bundesliga":             2002,
    "Campeonato Brasileiro":  2013,
    "Brazil Série B":         2016,
}


async def _fetch_score(home: str, away: str, match_date: date) -> dict:
    """Cherche le score final d'un match sur football-data.org"""
    if not FOOTBALL_DATA_KEY:
        return {}

    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    date_from = match_date.isoformat()
    date_to   = (match_date + timedelta(days=1)).isoformat()

    async with httpx.AsyncClient(timeout=15) as client:
        for league_name, league_id in LEAGUE_MAP.items():
            await asyncio.sleep(6)  # Rate limit 10 req/min
            try:
                url = f"{FOOTBALL_DATA_BASE}/competitions/{league_id}/matches"
                r = await client.get(url, headers=headers, params={
                    "dateFrom": date_from,
                    "dateTo":   date_to,
                    "status":   "FINISHED",
                })
                if r.status_code != 200:
                    continue

                for match in r.json().get("matches", []):
                    h = match["homeTeam"]["name"].lower()
                    a = match["awayTeam"]["name"].lower()
                    if home.lower() in h or h in home.lower():
                        if away.lower() in a or a in away.lower():
                            score = match["score"]["fullTime"]
                            return {
                                "home_score": score["home"],
                                "away_score": score["away"],
                                "result": f"{score['home']}-{score['away']}"
                            }
            except Exception as e:
                logger.error(f"Score fetch error: {e}")
                continue
    return {}


def _is_prono_correct(prediction: str, prono_type: str,
                      home_score: int, away_score: int,
                      home_team: str, away_team: str) -> bool:
    """Détermine si le prono est correct selon le résultat réel."""
    pred = prediction.lower()

    # 1X2
    if "victoire" in pred and home_team.lower() in pred:
        return home_score > away_score
    if "victoire" in pred and away_team.lower() in pred:
        return away_score > home_score
    if "nul" in pred or "draw" in pred:
        return home_score == away_score

    # Over/Under
    total = home_score + away_score
    if "over" in pred:
        try:
            line = float(pred.split("over")[1].strip().split()[0])
            return total > line
        except: pass
    if "under" in pred:
        try:
            line = float(pred.split("under")[1].strip().split()[0])
            return total < line
        except: pass

    # Score exact
    if prono_type == "exact_score":
        return prediction.strip() == f"{home_score}-{away_score}"

    return False


async def update_results():
    """
    Script principal : vérifie les pronos d'hier sans résultat
    et met à jour is_correct + result en base.
    """
    logger.info("🔍 Vérification des résultats...")
    yesterday = date.today() - timedelta(days=1)

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        SELECT id, home_team, away_team, league, match_date,
               prediction, prono_type, odds
        FROM pronos
        WHERE match_date = %s
          AND result IS NULL
          AND prono_type NOT IN ('combined')
    """, (yesterday,))
    pronos = cur.fetchall()
    cur.close()
    conn.close()

    if not pronos:
        logger.info("Aucun prono à vérifier.")
        return

    logger.info(f"{len(pronos)} prono(s) à vérifier...")

    correct = 0
    wrong   = 0

    for prono in pronos:
        score_data = await _fetch_score(
            prono["home_team"],
            prono["away_team"],
            prono["match_date"]
        )
        if not score_data:
            logger.warning(f"Score introuvable : {prono['home_team']} vs {prono['away_team']}")
            continue

        is_correct = _is_prono_correct(
            prono["prediction"],
            prono["prono_type"],
            score_data["home_score"],
            score_data["away_score"],
            prono["home_team"],
            prono["away_team"],
        )

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
            UPDATE pronos
            SET result     = %s,
                is_correct = %s
            WHERE id = %s
        """, (score_data["result"], is_correct, prono["id"]))
        conn.commit()
        cur.close()
        conn.close()

        status = "✅" if is_correct else "❌"
        logger.info(f"  {status} {prono['home_team']} vs {prono['away_team']} "
                    f"→ {score_data['result']} | {prono['prediction']}")

        if is_correct: correct += 1
        else: wrong += 1

    # Mettre à jour la table performance
    _update_performance(yesterday, correct, wrong)
    logger.info(f"✅ Résultats : {correct} corrects / {wrong} incorrects")


def _update_performance(period: date, correct: int, wrong: int):
    """Met à jour la table performance."""
    total = correct + wrong
    if total == 0:
        return

    win_rate = round(correct / total * 100, 1)

    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO performance (period, total_pronos, correct_pronos, win_rate)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (period) DO UPDATE
        SET total_pronos   = performance.total_pronos + EXCLUDED.total_pronos,
            correct_pronos = performance.correct_pronos + EXCLUDED.correct_pronos,
            win_rate       = EXCLUDED.win_rate
    """, (period, total, correct, win_rate))
    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    asyncio.run(update_results())
