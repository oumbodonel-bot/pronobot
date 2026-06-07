"""
Moteur Mathematique PronoBot
Poisson, Dixon-Coles, xG, Elo, Value Bet, Kelly
"""
import math
from typing import Dict, Tuple, List


def poisson_prob(lam: float, k: int) -> float:
    if lam <= 0 or k < 0:
        return 0.0
    return (math.exp(-lam) * (lam ** k)) / math.factorial(k)


def dixon_coles_correction(h: int, a: int, lh: float, la: float, rho: float = -0.13) -> float:
    if h == 0 and a == 0:
        return 1 - lh * la * rho
    elif h == 1 and a == 0:
        return 1 + la * rho
    elif h == 0 and a == 1:
        return 1 + lh * rho
    elif h == 1 and a == 1:
        return 1 - rho
    return 1.0


def score_matrix(lh: float, la: float, max_g: int = 7) -> Dict:
    raw = {}
    for h in range(max_g + 1):
        for a in range(max_g + 1):
            raw[(h, a)] = poisson_prob(lh, h) * poisson_prob(la, a)

    # Correction Dixon-Coles
    corrected = {}
    total = 0.0
    for (h, a), p in raw.items():
        tau = dixon_coles_correction(h, a, lh, la)
        corrected[(h, a)] = p * tau
        total += p * tau

    # Renormalisation
    for k in corrected:
        corrected[k] /= total if total > 0 else 1

    return corrected


def compute_lambdas(
    home_avg_scored:   float,
    home_avg_conceded: float,
    away_avg_scored:   float,
    away_avg_conceded: float,
    home_xg:           float,
    away_xg:           float,
    league_avg:        float = 2.65,
    home_advantage:    float = 1.12,
) -> Tuple[float, float]:
    """Calcule les lambdas (buts attendus) ajustes par xG."""
    # Force attaque/defense
    ha = home_avg_scored   / (league_avg / 2) if league_avg > 0 else 1.0
    hd = home_avg_conceded / (league_avg / 2) if league_avg > 0 else 1.0
    aa = away_avg_scored   / (league_avg / 2) if league_avg > 0 else 1.0
    ad = away_avg_conceded / (league_avg / 2) if league_avg > 0 else 1.0

    lh_base = ha * ad * (league_avg / 2) * home_advantage
    la_base = aa * hd * (league_avg / 2)

    # Ajustement xG (70% base + 30% xG)
    lh = lh_base * 0.70 + home_xg * 0.30 if home_xg else lh_base
    la = la_base * 0.70 + away_xg * 0.30 if away_xg else la_base

    return round(max(lh, 0.1), 3), round(max(la, 0.1), 3)


def elo_win_prob(elo_a: float, elo_b: float) -> float:
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))


def value_bet(prob: float, odds: float) -> float:
    return round((prob * odds) - 1, 4)


def kelly(prob: float, odds: float, fraction: float = 0.25) -> float:
    if odds <= 1 or prob <= 0:
        return 0.0
    k = (odds * prob - 1) / (odds - 1)
    return round(min(max(k * fraction, 0.0), 0.10), 4)


def full_analysis(
    home_stats: Dict,
    away_stats: Dict,
    odds_home: float,
    odds_draw: float,
    odds_away: float,
) -> Dict:
    """
    Analyse complete d'un match.
    Entree : vraies stats des equipes + vraies cotes bookmakers.
    """
    lh, la = compute_lambdas(
        home_avg_scored   = home_stats.get("avg_scored",   1.3),
        home_avg_conceded = home_stats.get("avg_conceded", 1.1),
        away_avg_scored   = away_stats.get("avg_scored",   1.1),
        away_avg_conceded = away_stats.get("avg_conceded", 1.3),
        home_xg           = home_stats.get("xg", 0),
        away_xg           = away_stats.get("xg", 0),
    )

    matrix = score_matrix(lh, la)

    # Probabilites 1X2
    p1 = sum(p for (h, a), p in matrix.items() if h > a)
    px = sum(p for (h, a), p in matrix.items() if h == a)
    p2 = sum(p for (h, a), p in matrix.items() if h < a)

    # Over/Under + BTTS
    p_over25  = sum(p for (h, a), p in matrix.items() if h + a > 2)
    p_btts    = sum(p for (h, a), p in matrix.items() if h > 0 and a > 0)

    # Top scores
    top = sorted(matrix.items(), key=lambda x: x[1], reverse=True)[:5]
    best_score = f"{top[0][0][0]}-{top[0][0][1]}"

    # Elo approche depuis la forme
    elo_h = 1500 + home_stats.get("form_score", 0.5) * 300
    elo_a = 1500 + away_stats.get("form_score", 0.5) * 300
    elo_p1 = elo_win_prob(elo_h, elo_a)

    # Value Bet sur chaque issue
    vb1 = value_bet(p1, odds_home)
    vbx = value_bet(px, odds_draw) if odds_draw else -1
    vb2 = value_bet(p2, odds_away)

    # Confiance globale
    form_diff  = home_stats.get("form_score", 0.5) - away_stats.get("form_score", 0.5)
    conf_score = min(max(0.5 + form_diff * 0.5 + (p1 - 0.33) * 0.5, 0.0), 1.0)
    stars      = max(1, min(5, int(conf_score * 5) + 1))

    # Kelly pour le meilleur pari
    if vb1 >= max(vbx, vb2):
        best_prob = p1
        best_odds = odds_home
        best_bet  = "1"
        best_vb   = vb1
    elif vb2 >= max(vb1, vbx):
        best_prob = p2
        best_odds = odds_away
        best_bet  = "2"
        best_vb   = vb2
    else:
        best_prob = px
        best_odds = odds_draw if odds_draw else odds_home
        best_bet  = "X"
        best_vb   = vbx

    kelly_stake = kelly(best_prob, best_odds)

    return {
        "lambda_home":    lh,
        "lambda_away":    la,
        "prob_home_win":  round(p1 * 100, 1),
        "prob_draw":      round(px * 100, 1),
        "prob_away_win":  round(p2 * 100, 1),
        "prob_over25":    round(p_over25 * 100, 1),
        "prob_btts":      round(p_btts * 100, 1),
        "best_score":     best_score,
        "top_scores":     [{"score": f"{h}-{a}", "prob": round(p * 100, 1)} for (h, a), p in top],
        "elo_home_win":   round(elo_p1 * 100, 1),
        "stars":          stars,
        "best_bet":       best_bet,
        "best_prob":      round(best_prob * 100, 1),
        "best_odds":      best_odds,
        "value_bet":      round(best_vb * 100, 2),
        "has_value":      best_vb > 0,
        "kelly_stake":    round(kelly_stake * 100, 1),
    }
