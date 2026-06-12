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
#    (commune aux deux modes)
# ════════════════════════════════════════════════════

def build_score_matrix(lh: float, la: float, over_line: float = 2.5) -> Dict:
    """
    Matrice NxN avec MAX_GOALS=12.
    Calcule : 1X2, Over/Under, BTTS Oui/Non, Score Exact.
    """
    matrix  = {}
    p_home  = p_draw = p_away = 0.0
    p_over  = p_btts = 0.0
    total_mass = 0.0  # pour vérifier la perte de masse probabiliste

    for i in range(MAX_GOALS):
        for j in range(MAX_GOALS):
            p = poisson_prob(lh, i) * poisson_prob(la, j)
            matrix[f"{i}-{j}"] = p
            total_mass += p

            if i > j:   p_home += p
            elif i == j: p_draw += p
            else:        p_away += p

            if i + j > over_line:
                p_over += p
            if i > 0 and j > 0:
                p_btts += p

    # ── Amélioration 1 : prob_no_btts ──
    p_no_btts = 1.0 - p_btts

    # Masse probabiliste capturée (doit être > 99.5% avec MAX_GOALS=12)
    mass_pct = round(total_mass * 100, 3)
    if mass_pct < 99.0:
        logger.warning(f"    ⚠️ Masse probabiliste capturée : {mass_pct}% (λh={lh}, λa={la})")

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
        "prob_over":      round(p_over,    4),
        "prob_under":     round(1.0 - p_over, 4),
        "prob_btts":      round(p_btts,    4),   # ← BTTS Oui
        "prob_no_btts":   round(p_no_btts, 4),   # ← Amélioration 1 : BTTS Non
        "top_scores":     top_scores,
        "best_score":     top_scores[0]["score"] if top_scores else "1-0",
        "score_matrix":   {k: round(v, 5) for k, v in matrix.items()},
        "mass_captured":  mass_pct,
    }


# ════════════════════════════════════════════════════
# 3. CALIBRATION LAMBDAS DEPUIS LES COTES (Mode B)
# ════════════════════════════════════════════════════

def _score_matrix_probs(lh: float, la: float, line: float = 2.5) -> Tuple[float, float, float, float]:
    """P(home), P(draw), P(away), P(over line) depuis deux lambdas."""
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
    """
    Trouve (λh, λa) minimisant l'erreur quadratique
    entre Poisson et probabilités vraies du marché.
    Grid search + raffinement itératif.
    """
    est_total = over_line + (2 * true_prob_over - 1) * 1.0
    est_total = max(1.5, min(est_total, 6.0))

    ratio = (true_prob_home / true_prob_away) ** 0.6 if true_prob_away > 0 else 1.2
    ratio = max(0.3, min(ratio, 4.0))

    lh_init = est_total * ratio / (1 + ratio)
    la_init = est_total         / (1 + ratio)

    best_lh    = lh_init
    best_la    = la_init
    best_error = float("inf")

    # Grid search grossier
    for lh_mult in [0.5, 0.65, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5]:
        for la_mult in [0.5, 0.65, 0.8, 0.9, 1.0, 1.1, 1.2, 1.35, 1.5]:
            lh = max(0.3, lh_init * lh_mult)
            la = max(0.3, la_init * la_mult)
            ph, pd, pa, po = _score_matrix_probs(lh, la, over_line)
            error = (
                (ph - true_prob_home) ** 2 +
                (pd - true_prob_draw) ** 2 +
                (pa - true_prob_away) ** 2 +
                (po - true_prob_over) ** 2 * 2  # O/U a plus de poids
            )
            if error < best_error:
                best_error = error
                best_lh    = lh
                best_la    = la

    # Raffinement fin
    for i in range(40):
        step     = 0.10 * (0.72 ** i)
        improved = False
        for dlh in [-step, 0, step]:
            for dla in [-step, 0, step]:
                if dlh == 0 and dla == 0:
                    continue
                lh = max(0.3, best_lh + dlh)
                la = max(0.3, best_la + dla)
                ph, pd, pa, po = _score_matrix_probs(lh, la, over_line)
                error = (
                    (ph - true_prob_home) ** 2 +
                    (pd - true_prob_draw) ** 2 +
                    (pa - true_prob_away) ** 2 +
                    (po - true_prob_over) ** 2 * 2
                )
                if error < best_error:
                    best_error = error
                    best_lh    = lh
                    best_la    = la
                    improved   = True
        if not improved:
            break

    logger.debug(
        f"  Lambdas calibrés: λh={round(best_lh,3)} "
        f"λa={round(best_la,3)} err={round(best_error,6)}"
    )
    return round(best_lh, 4), round(best_la, 4)


# ════════════════════════════════════════════════════
# 4. MARKET ALIGNMENT SCORE (Amélioration 3)
# ════════════════════════════════════════════════════

def compute_market_alignment_score(
    poisson_probs: Dict,
    market_probs:  Dict,
) -> Dict:
    """
    Mesure la cohérence entre les probabilités Poisson reconstruites
    et les probabilités implicites du marché.

    Score 0-100 :
    - 90-100 : Poisson parfaitement aligné avec le marché
    - 70-89  : Bonne cohérence — projection fiable
    - 50-69  : Cohérence modérée — utiliser avec précaution
    - < 50   : Faible cohérence — signal d'alerte

    Utilisé UNIQUEMENT comme indicateur de qualité du moteur de projection.
    NE PAS utiliser pour détecter des value bets en Mode B.
    """
    diffs = {
        "home": abs(poisson_probs["prob_home"] - market_probs["prob_home"]),
        "draw": abs(poisson_probs["prob_draw"] - market_probs["prob_draw"]),
        "away": abs(poisson_probs["prob_away"] - market_probs["prob_away"]),
        "over": abs(poisson_probs["prob_over"] - market_probs["prob_over"]),
    }

    # Erreur absolue moyenne pondérée
    # Over/Under pèse plus car contrainte principale du Mode B
    weighted_error = (
        diffs["home"] * 1.0 +
        diffs["draw"] * 0.8 +
        diffs["away"] * 1.0 +
        diffs["over"] * 1.2
    ) / 4.0

    # Conversion en score 0-100
    # Erreur 0%   → score 100
    # Erreur 2%   → score 90
    # Erreur 5%   → score 70
    # Erreur 10%  → score 50
    # Erreur 20%+ → score ~0
    score = max(0.0, 100.0 - weighted_error * 500.0)
    score = round(score, 1)

    if score >= 90:
        quality = "EXCELLENT"
    elif score >= 70:
        quality = "BON"
    elif score >= 50:
        quality = "MODERE"
    else:
        quality = "FAIBLE"

    return {
        "market_alignment_score": score,
        "alignment_quality":      quality,
        "diffs": {
            "home_diff": round(diffs["home"] * 100, 2),
            "draw_diff": round(diffs["draw"] * 100, 2),
            "away_diff": round(diffs["away"] * 100, 2),
            "over_diff": round(diffs["over"] * 100, 2),
        },
        "interpretation": (
            "Projection fiable (scores, BTTS, O/U)"
            if score >= 70 else
            "Projection indicative — Pinnacle requis pour valider"
        ),
    }


# ════════════════════════════════════════════════════
# 5. MODE A — Dixon-Coles (stats réelles)
# ════════════════════════════════════════════════════

def lambdas_from_real_stats(
    home_stats: Dict,
    away_stats: Dict,
) -> Optional[Tuple[float, float]]:
    """
    Lambdas Dixon-Coles depuis stats réelles.
    Retourne None si données invalides ou manquantes.
    """
    h_scored   = home_stats.get("avg_scored")
    h_conceded = home_stats.get("avg_conceded")
    a_scored   = away_stats.get("avg_scored")
    a_conceded = away_stats.get("avg_conceded")

    if any(v is None for v in [h_scored, h_conceded, a_scored, a_conceded]):
        return None
    if any(v <= 0 for v in [h_scored, h_conceded, a_scored, a_conceded]):
        return None

    lh = (h_scored   / LEAGUE_AVG_HOME) * (a_conceded / LEAGUE_AVG_AWAY) * LEAGUE_AVG_HOME
    la = (a_scored   / LEAGUE_AVG_AWAY) * (h_conceded / LEAGUE_AVG_HOME) * LEAGUE_AVG_AWAY

    lh = max(0.3, min(lh, 6.0))
    la = max(0.3, min(la, 6.0))

    return round(lh, 4), round(la, 4)


# ════════════════════════════════════════════════════
# 6. PINNACLE SIGNAL
# ════════════════════════════════════════════════════

def pinnacle_signal(odds_data: Dict) -> Dict:
    result = {
        "has_pinnacle":  False,
        "pinnacle_edge": 0.0,
        "signal":        "NEUTRE",
        "favored":       None,
    }
    p_home = odds_data.get("pinnacle_home")
    m_home = odds_data.get("odds_home")
    if not p_home or not m_home:
        return result

    result["has_pinnacle"] = True
    p_draw = odds_data.get("pinnacle_draw") or odds_data.get("odds_draw") or 3.3
    p_away = odds_data.get("pinnacle_away") or odds_data.get("odds_away") or 3.5
    m_draw = odds_data.get("odds_draw") or 3.3
    m_away = odds_data.get("odds_away") or 3.5

    pin_h, pin_d, pin_a = remove_margin(
        odds_to_prob(p_home), odds_to_prob(p_draw), odds_to_prob(p_away)
    )
    mkt_h, mkt_d, mkt_a = remove_margin(
        odds_to_prob(m_home), odds_to_prob(m_draw), odds_to_prob(m_away)
    )

    edge_h = (pin_h - mkt_h) * 100
    edge_a = (pin_a - mkt_a) * 100

    if abs(edge_h) >= abs(edge_a):
        result["pinnacle_edge"] = round(edge_h, 2)
        result["favored"]       = "HOME" if edge_h > 0 else "AWAY"
    else:
        result["pinnacle_edge"] = round(edge_a, 2)
        result["favored"]       = "AWAY" if edge_a > 0 else "HOME"

    edge = abs(result["pinnacle_edge"])
    result["signal"] = (
        "FORT"   if edge >= 5 else
        "MODERE" if edge >= 3 else
        "FAIBLE" if edge >= 1 else
        "NEUTRE"
    )
    return result


# ════════════════════════════════════════════════════
# 7. VALUE BET (Mode A uniquement pour la détection)
# ════════════════════════════════════════════════════

def compute_value_bet(
    our_prob:        float,
    market_odds:     float,
    has_pinnacle:    bool = False,
    pin_signal:      str  = "NEUTRE",
    bookmaker_count: int  = 5,
    mode:            str  = "A",
) -> Dict:
    """
    Mode A : comparaison probs Poisson (stats) vs cotes marché.
    Mode B : value bet désactivé — utiliser market_alignment_score
             et signal Pinnacle à la place.
    """
    if not market_odds or market_odds <= 1.0:
        return {"value_pct": 0, "has_value": False, "threshold_used": "N/A"}

    implied   = 1.0 / market_odds
    edge      = our_prob - implied
    value_pct = round(edge * 100, 2)

    if mode == "B":
        # Mode B = moteur de projection, pas de détection value
        # Seul le signal Pinnacle peut valider une opportunité
        has_value = (
            has_pinnacle and
            pin_signal in ("FORT", "MODERE") and
            edge > 0
        )
        return {
            "value_pct":      value_pct,
            "has_value":      has_value,
            "threshold_used": "Pinnacle uniquement (Mode B)",
            "note":           "Mode B = projection. Value bet via Pinnacle seulement.",
        }

    # Mode A : seuils adaptatifs
    if has_pinnacle and pin_signal == "FORT":
        threshold = 0.015
    elif has_pinnacle and pin_signal == "MODERE":
        threshold = 0.025
    elif bookmaker_count >= 10:
        threshold = 0.030
    else:
        threshold = 0.040

    return {
        "value_pct":      value_pct,
        "has_value":      edge >= threshold,
        "threshold_used": round(threshold * 100, 1),
        "implied_prob":   round(implied  * 100, 1),
        "our_prob":       round(our_prob * 100, 1),
    }


def kelly_stake(prob: float, odds: float) -> float:
    if not odds or odds <= 1.0 or prob <= 0:
        return 0.0
    b = odds - 1.0
    k = (b * prob - (1 - prob)) / b
    return round(max(0.0, k) * KELLY_FRAC * 100, 2)


# ════════════════════════════════════════════════════
# 8. ANALYSE COMPLÈTE — POINT D'ENTRÉE
# ════════════════════════════════════════════════════

def full_analysis(
    odds_data:  Dict,
    home_stats: Optional[Dict] = None,
    away_stats: Optional[Dict] = None,
) -> Dict:
    """
    Analyse complète hybride.

    Mode A : stats réelles → Dixon-Coles → Poisson → matrice
             Value bet activé.

    Mode B : pas de stats → calibration depuis cotes → Poisson → matrice
             Value bet désactivé.
             market_alignment_score disponible comme indicateur qualité.
             Score Exact / BTTS / Over/Under toujours calculés.
    """
    over_line  = odds_data.get("over_line", 2.5)
    mkt        = market_true_probs(odds_data)
    pin        = pinnacle_signal(odds_data)
    bookmakers = odds_data.get("bookmaker_count", 5)

    # ── Choix du mode ──
    lh = la = None
    mode = "B"

    if home_stats and away_stats:
        lambdas = lambdas_from_real_stats(home_stats, away_stats)
        if lambdas:
            lh, la = lambdas
            mode   = "A"
            logger.info(f"    Mode A (Dixon-Coles): λh={lh} λa={la}")

    if mode == "B":
        lh, la = calibrate_lambdas_from_odds(
            true_prob_home = mkt["prob_home"],
            true_prob_draw = mkt["prob_draw"],
            true_prob_away = mkt["prob_away"],
            true_prob_over = mkt["prob_over"],
            over_line      = over_line,
        )
        logger.info(f"    Mode B (calibré cotes): λh={lh} λa={la}")

    # ── Matrice de scores (MAX_GOALS=12) ──
    matrix = build_score_matrix(lh, la, over_line)

    final_probs = {
        "prob_home":    matrix["prob_home"],
        "prob_draw":    matrix["prob_draw"],
        "prob_away":    matrix["prob_away"],
        "prob_over":    matrix["prob_over"],
        "prob_under":   matrix["prob_under"],
        "prob_btts":    matrix["prob_btts"],
        "prob_no_btts": matrix["prob_no_btts"],  # ← Amélioration 1
    }

    # ── Market Alignment Score (Amélioration 3) ──
    alignment = compute_market_alignment_score(final_probs, mkt)
    if mode == "B":
        logger.info(
            f"    Alignement marché : {alignment['market_alignment_score']}/100 "
            f"({alignment['alignment_quality']}) — {alignment['interpretation']}"
        )

    # ── Opportunités dans la plage métier (1.40-2.00) ──
    opportunities = []
    checks = [
        ("1",                   "prob_home",  "odds_home",  "1X2"),
        ("X",                   "prob_draw",  "odds_draw",  "1X2"),
        ("2",                   "prob_away",  "odds_away",  "1X2"),
        (f"Over {over_line}",   "prob_over",  "over_odds",  "OU"),
        (f"Under {over_line}",  "prob_under", "under_odds", "OU"),
    ]
    for label, prob_key, odds_key, market in checks:
        odds_val = odds_data.get(odds_key)
        if not odds_val or not (1.40 <= odds_val <= 2.00):
            continue
        prob_val = final_probs.get(prob_key, 0)
        vb       = compute_value_bet(
            our_prob        = prob_val,
            market_odds     = odds_val,
            has_pinnacle    = pin["has_pinnacle"],
            pin_signal      = pin["signal"],
            bookmaker_count = bookmakers,
            mode            = mode,
        )
        opportunities.append({
            "outcome":   label,
            "odds":      odds_val,
            "prob":      round(prob_val, 4),
            "value_bet": vb["value_pct"],
            "has_value": vb["has_value"],
            "kelly":     kelly_stake(prob_val, odds_val),
            "market":    market,
        })

    valued   = [o for o in opportunities if o["has_value"]]
    best_opp = (
        max(valued,       key=lambda x: x["value_bet"]) if valued else
        max(opportunities, key=lambda x: x["prob"])      if opportunities else None
    )

    return {
        # Mode
        "mode":           mode,
        "prob_source":    "dixon_coles+stats_reelles" if mode == "A" else "poisson_calibre_cotes",
        "has_real_stats": mode == "A",

        # Lambdas
        "lambda_home":    lh,
        "lambda_away":    la,

        # Probabilités finales
        "prob_home":      final_probs["prob_home"],
        "prob_draw":      final_probs["prob_draw"],
        "prob_away":      final_probs["prob_away"],
        "prob_over":      final_probs["prob_over"],
        "prob_under":     final_probs["prob_under"],
        "prob_btts":      final_probs["prob_btts"],
        "prob_no_btts":   final_probs["prob_no_btts"],   # ← Amélioration 1

        # Score exact (toujours disponible — Mode A et B)
        "top_scores":     matrix["top_scores"],
        "best_score":     matrix["best_score"],
        "score_matrix":   matrix["score_matrix"],
        "mass_captured":  matrix["mass_captured"],

        # Marché
        "mkt_probs":       mkt,
        "pinnacle":        pin,
        "bookmaker_count": bookmakers,

        # Market Alignment Score (Amélioration 3)
        "alignment":       alignment,                             # ← Amélioration 3
        "market_alignment_score": alignment["market_alignment_score"],

        # Opportunités
        "opportunities":   opportunities,
        "best_opportunity": best_opp,

        # Compatibilité generate_pronos.py
        "value_bet":   best_opp["value_bet"] if best_opp else 0,
        "kelly_stake": best_opp["kelly"]     if best_opp else 3.0,
        "stars":       3 if mode == "A" else 2,
    }
