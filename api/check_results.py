import os
import httpx
import asyncio
import logging
from datetime import date, timedelta
from core.database import get_conn
from core.manual_data_fusion import normalize_name, TEAM_TRANSLATIONS

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

async def fetch_all_finished_matches(target_date: date) -> dict:
    """Récupère tous les matchs terminés pour les ligues majeures en une fois."""
    if not FOOTBALL_DATA_KEY:
        logger.error("FOOTBALL_DATA_API_KEY non configurée.")
        return {}

    results = {}
    headers = {"X-Auth-Token": FOOTBALL_DATA_KEY}
    date_str = target_date.isoformat()

    async with httpx.AsyncClient(timeout=20) as client:
        for league_name, league_id in LEAGUE_MAP.items():
            try:
                # Utilisation de l'endpoint global matches pour cette ligue
                url = f"{FOOTBALL_DATA_BASE}/competitions/{league_id}/matches"
                r = await client.get(url, headers=headers, params={
                    "dateFrom": date_str,
                    "dateTo":   date_str,
                    "status":   "FINISHED",
                })
                
                if r.status_code == 200:
                    matches = r.json().get("matches", [])
                    for m in matches:
                        h = normalize_name(m["homeTeam"]["name"])
                        a = normalize_name(m["awayTeam"]["name"])
                        # On stocke avec une clé normalisée
                        key = f"{h} vs {a}"
                        results[key] = {
                            "home_score": m["score"]["fullTime"]["home"],
                            "away_score": m["score"]["fullTime"]["away"],
                            "result": f"{m['score']['fullTime']['home']}-{m['score']['fullTime']['away']}"
                        }
                elif r.status_code == 429:
                    logger.warning(f"Rate limit atteint pour {league_name}, pause...")
                    await asyncio.sleep(60)
                
                # Petite pause pour respecter le plan gratuit (10 req/min)
                await asyncio.sleep(6)
                
            except Exception as e:
                logger.error(f"Error fetching {league_name}: {e}")
                continue
                
    return results

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
            line = float(re.findall(r"\d+\.\d+", pred)[0])
            return total > line
        except: 
            if "2.5" in pred: return total > 2.5
    if "under" in pred:
        try:
            line = float(re.findall(r"\d+\.\d+", pred)[0])
            return total < line
        except:
            if "2.5" in pred: return total < 2.5

    # Score exact
    if prono_type == "exact_score" or "score exact" in pred:
        clean_pred = re.sub(r'[^0-9-]', '', prediction)
        return clean_pred == f"{home_score}-{away_score}"

    return False

async def update_results():
    logger.info("🔍 Vérification des résultats (Mode Optimisé)...")
    
    # On vérifie les 3 derniers jours pour être sûr de ne rien rater
    for days_back in range(1, 4):
        target_date = date.today() - timedelta(days=days_back)
        logger.info(f"📅 Vérification pour le {target_date}...")

        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
            SELECT id, home_team, away_team, league, match_date,
                   prediction, prono_type, odds
            FROM pronos
            WHERE match_date = %s
              AND result IS NULL
              AND prono_type NOT IN ('combined')
        """, (target_date,))
        pronos = cur.fetchall()
        cur.close()
        conn.close()

        if not pronos:
            logger.info(f"Aucun prono en attente pour le {target_date}.")
            continue

        # Récupération de tous les scores du jour
        daily_scores = await fetch_all_finished_matches(target_date)
        
        correct_count = 0
        wrong_count = 0

        for prono in pronos:
            h_norm = normalize_name(prono["home_team"])
            a_norm = normalize_name(prono["away_team"])
            
            # Tentative de matching avec traduction
            h_trans = TEAM_TRANSLATIONS.get(h_norm, h_norm)
            a_trans = TEAM_TRANSLATIONS.get(a_norm, a_norm)
            
            score_data = None
            # On cherche dans les scores récupérés
            for key, data in daily_scores.items():
                if (h_norm in key or h_trans in key) and (a_norm in key or a_trans in key):
                    score_data = data
                    break
            
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
            logger.info(f"  {status} {prono['home_team']} vs {prono['away_team']} → {score_data['result']}")
            
            if is_correct: correct_count += 1
            else: wrong_count += 1

        if correct_count + wrong_count > 0:
            _update_performance(target_date, correct_count, wrong_count)

def _update_performance(period: date, correct: int, wrong: int):
    total = correct + wrong
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
    import re
    asyncio.run(update_results())
