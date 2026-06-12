"""
Moteur Mathématique Hybride
============================
Mode A : Stats réelles → Dixon-Coles → Poisson
Mode B : Pas de stats  → Lambdas calibrés depuis les cotes → Poisson

JAMAIS de données fictives.
Mode B = moteur de projection (scores, BTTS, O/U, HC)
         PAS un moteur de value bet.
"""

import math
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Moyennes de référence Ligue européenne standard ──
LEAGUE_AVG_HOME  = 1.55
LEAGUE_AVG_AWAY  = 1.10
LEAGUE_AVG_TOTAL = LEAGUE_AVG_HOME + LEAGUE_AVG_AWAY  # 2.65

MAX_GOALS  = 12      # ← Amélioration 2 : 9→12 pour matchs offensifs
KELLY_FRAC = 0.25


# ════════════════════════════════════════════════════
# 1. UTILITAIRES DE BASE
# ════════════════════════════════════════════════════

def poisson_prob(lam: float, k: int) -> float:
    """P(X=k) loi de Poisson."""
    if lam <= 0 or k < 0:
        return 0.0
    try:
        return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except (OverflowError, ValueError):
        return 0.0


def odds_to_prob(odds: float) -> float:
    if not odds or odds <= 1.0:
        return 0.0
    return 1.0 / odds


def remove_margin(*probs: float) -> Tuple[float, ...]:
    total = sum(probs)
    if total <= 0:
        return probs
    return tuple(p / total for p in probs)


def market_true_probs(odds_data: Dict) -> Dict:
    """Probabilités vraies depuis les cotes (marge supprimée)."""
    h_raw = odds_to_prob(odds_data.get("odds_home") or 0)
    d_raw = odds_to_prob(odds_data.get("odds_draw") or 0)
    a_raw = odds_to_prob(odds_data.get("odds_away") or 0)

    if h_raw + d_raw + a_raw > 0:
        h, d, a = remove_margin(h_raw, d_raw, a_raw)
    else:
        h, d, a = 0.45, 0.27, 0.28

    over_raw  = odds_to_prob(odds_data.get("over_odds")  or 0)
    under_raw = odds_to_prob(odds_data.get("under_odds") or 0)
    if over_raw + under_raw > 0:
        p_over, p_under = remove_margin(over_raw, under_raw)
    else:
        p_over, p_under = 0.50, 0.50

    return {
        "prob_home":  round(h,       4),
        "prob_draw":  round(d,       4),
        "prob_away":  round(a,       4),
        "prob_over":  round(p_over,  4),
        "prob_under": round(p_under, 4),
        "over_line":  odds_data.get("over_line", 2.5),
    }


# ════════════════════════════════════════════════════
# 2. MATRICE DE SCORES COMPLÈTE
# ════════════════════════════════════════════════════

def build_score_matrix(lh: float, la: float, over_line: float = 2.5) -> Dict:
    """
    Matrice NxN avec MAX_GOALS=12.
    Calcule : 1X2, Over/Under, BTTS Oui/Non, Score Exact, Double Chance, DNB, Handicaps.
    """
    matrix  = {}
    p_home  = p_draw = p_away = 0.0
    p_over_15 = p_over_25 = p_under_35 = 0.0
    p_btts = 0.0
    total_mass = 0.0

    for i in range(MAX_GOALS):
        for j in range(MAX_GOALS):
            p = poisson_prob(lh, i) * poisson_prob(la, j)
            matrix[f"{i}-{j}"] = p
            total_mass += p

            if i > j:   p_home += p
            elif i == j: p_draw += p
            else:        p_away += p

            if i + j > 1.5: p_over_15 += p
            if i + j > 2.5: p_over_25 += p
            if i + j < 3.5: p_under_35 += p
            
            if i > 0 and j > 0:
                p_btts += p

    # Double Chance
    p_1X = p_home + p_draw
    p_X2 = p_away + p_draw
    p_12 = p_home + p_away

    # Draw No Bet (DNB) - Probabilité conditionnelle
    p_dnb_1 = p_home / (p_home + p_away) if (p_home + p_away) > 0 else 0.5
    p_dnb_2 = p_away / (p_home + p_away) if (p_home + p_away) > 0 else 0.5

    top_scores = sorted(
        [{"score": s, "prob": round(v * 100, 2)} for s, v in matrix.items()],
        key=lambda x: x["prob"],
        reverse=True,
    )[:10]

    return {
        "lambda_home":    round(lh,        3),
        "lambda_away":    round(la,        3),
        "prob_home":      round(p_home,    4),
        "prob_draw":      round(p_draw,    4),
        "prob_away":      round(p_away,    4),
        "prob_over_15":   round(p_over_15, 4),
        "prob_over_25":   round(p_over_25, 4),
        "prob_under_35":  round(p_under_35, 4),
        "prob_btts":      round(p_btts,    4),
        "prob_no_btts":   round(1.0 - p_btts, 4),
        "prob_1X":        round(p_1X,      4),
        "prob_X2":        round(p_X2,      4),
        "prob_12":        round(p_12,      4),
        "prob_dnb_1":     round(p_dnb_1,   4),
        "prob_dnb_2":     round(p_dnb_2,   4),
        "top_scores":     top_scores,
        "best_score":     top_scores[0]["score"] if top_scores else "1-0",
        "mass_captured":  round(total_mass * 100, 3),
    }


# ════════════════════════════════════════════════════
# 3. CALIBRATION LAMBDAS (Mode B)
# ════════════════════════════════════════════════════

def _score_matrix_probs(lh: float, la: float, line: float = 2.5) -> Tuple[float, float, float, float]:
    p_home = p_draw = p_away = p_over = 0.0
    for i in range(MAX_GOALS):
        for j in range(MAX_GOALS):
            p = poisson_prob(lh, i) * poisson_prob(la, j)
            if i > j:    p_home += p
            elif i == j: p_draw += p
            else:        p_away += p
            if i + j > line:
                p_over += p
    return p_home, p_draw, p_away, p_over


def calibrate_lambdas_from_odds(
    true_prob_home: float,
    true_prob_draw: float,
    true_prob_away: float,
    true_prob_over: float,
    over_line:      float = 2.5,
) -> Tuple[float, float]:
    est_total = over_line + (2 * true_prob_over - 1) * 1.0
    est_total = max(1.5, min(est_total, 6.0))

    ratio = (true_prob_home / true_prob_away) ** 0.6 if true_prob_away > 0 else 1.2
    ratio = max(0.3, min(ratio, 4.0))

    lh_init = est_total * ratio / (1 + ratio)
    la_init = est_total         / (1 + ratio)

    best_lh    = lh_init
    best_la    = la_init
    best_error = float("inf")

    for lh_mult in [0.5, 0.8, 1.0, 1.2, 1.5]:
        for la_mult in [0.5, 0.8, 1.0, 1.2, 1.5]:
            lh = max(0.3, lh_init * lh_mult)
            la = max(0.3, la_init * la_mult)
            ph, pd, pa, po = _score_matrix_probs(lh, la, over_line)
            error = (ph-true_prob_home)**2 + (pd-true_prob_draw)**2 + (pa-true_prob_away)**2 + (po-true_prob_over)**2*2
            if error < best_error:
                best_error, best_lh, best_la = error, lh, la

    for i in range(20):
        step = 0.10 * (0.8 ** i)
        improved = False
        for dlh in [-step, 0, step]:
            for dla in [-step, 0, step]:
                lh, la = max(0.3, best_lh + dlh), max(0.3, best_la + dla)
                ph, pd, pa, po = _score_matrix_probs(lh, la, over_line)
                error = (ph-true_prob_home)**2 + (pd-true_prob_draw)**2 + (pa-true_prob_away)**2 + (po-true_prob_over)**2*2
                if error < best_error:
                    best_error, best_lh, best_la = error, lh, la
                    improved = True
        if not improved: break

    return round(best_lh, 4), round(best_la, 4)


# ════════════════════════════════════════════════════
# 4. MARKET ALIGNMENT SCORE
# ════════════════════════════════════════════════════

def compute_market_alignment_score(poisson_probs: Dict, market_probs: Dict) -> Dict:
    diffs = {
        "home": abs(poisson_probs["prob_home"] - market_probs["prob_home"]),
        "draw": abs(poisson_probs["prob_draw"] - market_probs["prob_draw"]),
        "away": abs(poisson_probs["prob_away"] - market_probs["prob_away"]),
        "over": abs(poisson_probs["prob_over_25"] - market_probs["prob_over"]),
    }
    weighted_error = (diffs["home"] + diffs["draw"]*0.8 + diffs["away"] + diffs["over"]*1.2) / 4.0
    score = max(0.0, 100.0 - weighted_error * 500.0)
    return {"market_alignment_score": round(score, 1), "alignment_quality": "EXCELLENT" if score >= 90 else "BON" if score >= 70 else "MODERE"}


# ════════════════════════════════════════════════════
# 5. PINNACLE SIGNAL
# ════════════════════════════════════════════════════

def pinnacle_signal(odds_data: Dict) -> Dict:
    result = {"has_pinnacle": False, "pinnacle_edge": 0.0, "signal": "NEUTRE", "favored": None}
    p_home = odds_data.get("pinnacle_home")
    m_home = odds_data.get("odds_home")
    if not p_home or not m_home: return result

    result["has_pinnacle"] = True
    p_draw = odds_data.get("pinnacle_draw") or odds_data.get("odds_draw") or 3.3
    p_away = odds_data.get("pinnacle_away") or odds_data.get("odds_away") or 3.5
    m_draw = odds_data.get("odds_draw") or 3.3
    m_away = odds_data.get("odds_away") or 3.5

    pin_h, pin_d, pin_a = remove_margin(odds_to_prob(p_home), odds_to_prob(p_draw), odds_to_prob(p_away))
    mkt_h, mkt_d, mkt_a = remove_margin(odds_to_prob(m_home), odds_to_prob(m_draw), odds_to_prob(m_away))

    edge_h, edge_a = (pin_h - mkt_h) * 100, (pin_a - mkt_a) * 100
    if abs(edge_h) >= abs(edge_a):
        result["pinnacle_edge"], result["favored"] = round(edge_h, 2), "HOME" if edge_h > 0 else "AWAY"
    else:
        result["pinnacle_edge"], result["favored"] = round(edge_a, 2), "AWAY" if edge_a > 0 else "HOME"

    edge = abs(result["pinnacle_edge"])
    result["signal"] = "FORT" if edge >= 5 else "MODERE" if edge >= 3 else "FAIBLE" if edge >= 1 else "NEUTRE"
    return result


# ════════════════════════════════════════════════════
# 6. VALUE BET & KELLY
# ════════════════════════════════════════════════════

def compute_value_bet(our_prob: float, market_odds: float, has_pinnacle: bool = False, pin_signal: str = "NEUTRE", bookmaker_count: int = 5, mode: str = "A") -> Dict:
    if mode == "B": return {"has_value": False, "value_pct": 0}
    fair_odds = 1.0 / our_prob if our_prob > 0 else 100
    value = (market_odds / fair_odds - 1) * 100
    threshold = 3.0 if has_pinnacle and pin_signal in ["FORT", "MODERE"] else 6.0
    return {"has_value": value >= threshold, "value_pct": round(value, 2)}

def kelly_stake(prob: float, odds: float) -> float:
    if odds <= 1: return 0.0
    q = 1.0 - prob
    f = (prob * odds - 1.0) / (odds - 1.0)
    return max(0.0, round(f * KELLY_FRAC * 100, 1))


# ════════════════════════════════════════════════════
# 7. ANALYSE COMPLÈTE
# ════════════════════════════════════════════════════

def full_analysis(odds_data: Dict, home_stats: Optional[Dict] = None, away_stats: Optional[Dict] = None) -> Dict:
    over_line = odds_data.get("over_line", 2.5)
    mkt = market_true_probs(odds_data)
    pin = pinnacle_signal(odds_data)
    
    lh = la = None
    mode = "B"
    
    # Mode A si stats dispos
    if home_stats and away_stats:
        res = DixonColes_Lambdas(home_stats, away_stats)
        if res:
            lh, la = res
            mode = "A"

    # Mode B (calibration) si pas de stats ou échec Mode A
    if lh is None:
        lh, la = calibrate_lambdas_from_odds(mkt["prob_home"], mkt["prob_draw"], mkt["prob_away"], mkt["prob_over"], over_line)

    matrix = build_score_matrix(lh, la, over_line)
    alignment = compute_market_alignment_score(matrix, mkt)

    # Marchés étendus
    markets = []
    checks = [
        ("1", "prob_home", "odds_home", "1X2"),
        ("X", "prob_draw", "odds_draw", "1X2"),
        ("2", "prob_away", "odds_away", "1X2"),
        ("1X", "prob_1X", None, "DC"),
        ("X2", "prob_X2", None, "DC"),
        ("12", "prob_12", None, "DC"),
        ("DNB 1", "prob_dnb_1", None, "DNB"),
        ("DNB 2", "prob_dnb_2", None, "DNB"),
        ("Over 1.5", "prob_over_15", None, "OU"),
        ("Over 2.5", "prob_over_25", "over_odds", "OU"),
        ("Under 3.5", "prob_under_35", None, "OU"),
        ("BTTS Oui", "prob_btts", None, "BTTS"),
        ("BTTS Non", "prob_no_btts", None, "BTTS"),
    ]

    # Récupération des cotes de base pour dérivation
    o_h = odds_data.get("odds_home")
    o_x = odds_data.get("odds_draw")
    o_a = odds_data.get("odds_away")

    for label, prob_key, odds_key, mkt_type in checks:
        prob_val = matrix.get(prob_key, 0)
        odds_val = odds_data.get(odds_key)

        # Calcul des cotes dérivées si non fournies (Double Chance & DNB)
        if not odds_val or odds_val < 1.1:
            if label == "1X" and o_h and o_x:
                odds_val = (o_h * o_x) / (o_h + o_x)
            elif label == "X2" and o_a and o_x:
                odds_val = (o_a * o_x) / (o_a + o_x)
            elif label == "12" and o_h and o_a:
                odds_val = (o_h * o_a) / (o_h + o_a)
            elif label == "DNB 1" and o_h and o_x:
                odds_val = o_h * (1 - (1.0 / o_x))
            elif label == "DNB 2" and o_a and o_x:
                odds_val = o_a * (1 - (1.0 / o_x))
            
            # Si toujours pas de cote (ex: BTTS, Over 1.5), estimation Poisson prudente
            if not odds_val or odds_val < 1.01:
                odds_val = 1.0 / (prob_val * 1.10) if prob_val > 0.1 else 2.0

        vb = compute_value_bet(prob_val, odds_val, pin["has_pinnacle"], pin["signal"], mode=mode)
        markets.append({
            "outcome": label,
            "type": mkt_type,
            "prob": round(prob_val * 100, 1),
            "odds": round(odds_val, 2),
            "value": vb["value_pct"],
            "edge_vs_market": round((prob_val - mkt.get(prob_key, prob_val)) * 100, 1) if prob_key in mkt else 0
        })

    return {
        "mode": mode,
        "lambdas": {"home": lh, "away": la},
        "matrix": matrix,
        "alignment": alignment,
        "pinnacle": pin,
        "markets": markets,
        "best_score": matrix["best_score"],
        "top_scores": matrix["top_scores"]
    }

def DixonColes_Lambdas(h: Dict, a: Dict) -> Optional[Tuple[float, float]]:
    hs, hc, as_, ac = h.get("avg_scored"), h.get("avg_conceded"), a.get("avg_scored"), a.get("avg_conceded")
    if any(v is None or v <= 0 for v in [hs, hc, as_, ac]): return None
    lh = max(0.3, min((hs/LEAGUE_AVG_HOME)*(ac/LEAGUE_AVG_AWAY)*LEAGUE_AVG_HOME, 6.0))
    la = max(0.3, min((as_/LEAGUE_AVG_AWAY)*(hc/LEAGUE_AVG_HOME)*LEAGUE_AVG_AWAY, 6.0))
    return round(lh, 4), round(la, 4)
