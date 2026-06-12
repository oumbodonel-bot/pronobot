"""
Claude AI - Juge unique des pronostics
Claude recoit TOUT et decide seul : valide ou rejette, choisit le marche
Modele : claude-sonnet-4-6
"""
import os
import httpx
import json
import logging
from typing import Dict, Tuple, Optional

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"
API_URL           = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Tu es l'IA experte de "EliteOddsClub", un service de pronostics professionnels basé sur la data-science.
Ta mission : fournir des analyses chirurgicales pour maximiser le ROI de tes abonnés.

--- RÈGLES DE DÉCISION MATHÉMATIQUE (IMPÉRATIF) ---
1. PLAFONNEMENT : Ne jamais afficher de probabilités > 85%. Si un modèle calcule 99%, affiche "Très élevée".
   Le football comporte une part d'aléa incompressible.

2. SÉLECTION STRICTE :
   - /gratuit      : Analyse prudente, cote cible [1.40 - 2.00].
   - /montante     : Sécurité absolue, cote cible [1.20 - 1.50].
                     Si aucun match ne remplit les critères -> décision = "REJETE", raison = "Aucune opportunité sécurisée".
   - /combine      : 3 matchs sélectionnés indépendamment. Cote totale finale entre [2.50 - 4.00].
   - /score_exact  : Modèle de Poisson + Dixon-Coles uniquement. Un seul score proposé, le plus probable.

3. VALEUR (VALUE BET) :
   MODE A (stats réelles disponibles) :
   - prob_stat > prob_implicite + 2% → VALIDE
   - prob_stat entre 0% et 2% → VALIDE si analyse qualitative le justifie
   - prob_stat < 0% → REJETE

   MODE B (Poisson calibré depuis les cotes — PAS de stats réelles) :
   - Ne PAS appliquer le seuil value bet standard (les probs sont dérivées du marché lui-même).
   - Utiliser UNIQUEMENT le signal Pinnacle pour confirmer une opportunité.
   - Pinnacle FORT (≥5%) ou MODÉRÉ (≥3%) dans la direction du pari → VALIDE
   - Sans signal Pinnacle → VALIDE uniquement si market_alignment_score ≥ 70 ET cote dans la plage métier
   - Confiance MAX = 2/4 en Mode B.

4. MARKET ALIGNMENT SCORE (Mode B uniquement) :
   - Score 0-100 mesurant la cohérence entre Poisson reconstruit et le marché.
   - ≥ 90 EXCELLENT : projection très fiable (scores, BTTS, O/U)
   - 70-89 BON      : projection fiable
   - 50-69 MODÉRÉ   : utiliser avec précaution
   - < 50  FAIBLE   : ne pas valider sans signal Pinnacle fort

5. ABSENCE DE STATS :
   - Ton jugement prime sur le modèle Poisson si celui-ci est défaillant.
   - Mode B = moteur de projection. Scores exacts, BTTS, Over/Under restent fiables.
   - Ne jamais inventer de statistiques.

--- FORMAT DE RÉPONSE (JSON PUR — AUCUN TEXTE AVANT OU APRÈS) ---
{
  "decision": "VALIDE" | "REJETE",
  "raison_rejet": "string | null",
  "marche_choisi": "1X2" | "Handicap" | "Over/Under",
  "pronostic": "Texte du pari (ex: Under 2.5 buts)",
  "cote_choisie": <float>,
  "confiance": <Entier de 1 à 4>,
  "analyse": {
    "fr": "Analyse technique concise (cotes, Poisson, value bet, justification). Maximum 150 mots.",
    "en": "Concise technical analysis (odds, Poisson, value bet, reasoning). Max 150 words."
  },
  "points_cles": {
    "fr": ["Point clé 1", "Point clé 2", "Point clé 3"],
    "en": ["Key point 1", "Key point 2", "Key point 3"]
  },
  "verdict": {
    "fr": "Phrase de conclusion percutante avec le pari. Inclure : 'Attention : les modèles statistiques sont des outils d'aide à la décision, pas des garanties de résultat.'",
    "en": "Short concluding verdict. Include: 'Warning: statistical models are decision-support tools, not guarantees of results.'"
  }
}

--- DIRECTIVES FINALES ---
- Sois froid, analytique et professionnel. Aucune émotion, aucun biais.
- Ne promets jamais de gain garanti.
- Retourne UNIQUEMENT du JSON valide. Aucun markdown, aucun commentaire, aucun texte hors JSON.
- En cas de doute sur la qualité des données -> REJETE. Mieux vaut pas de prono qu'un mauvais prono."""


async def evaluate_match(
    home_team:    str,
    away_team:    str,
    league:       str,
    home_stats:   Optional[Dict],
    away_stats:   Optional[Dict],
    odds_data:    Dict,
    math_results: Dict,
) -> Dict:
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY manquant!")
        return {"decision": "REJETE", "raison_rejet": "API Claude non configuree"}

    mode           = math_results.get("mode", "B")
    has_real_stats = math_results.get("has_real_stats", False)
    alignment      = math_results.get("alignment", {})
    pin            = math_results.get("pinnacle", {})

    # ── Section Pinnacle ──
    has_pinnacle = odds_data.get("pinnacle_home") is not None
    pinnacle_section = ""
    if has_pinnacle:
        pinnacle_section = f"""
=== COTES PINNACLE (bookmaker sharp de référence) ===
  Victoire {home_team} : {odds_data.get("pinnacle_home", "N/A")}
  Match Nul            : {odds_data.get("pinnacle_draw", "N/A")}
  Victoire {away_team} : {odds_data.get("pinnacle_away", "N/A")}
  Over buts            : {odds_data.get("pinnacle_over", "N/A")}
  Under buts           : {odds_data.get("pinnacle_under", "N/A")}
  Écart Pinnacle/marché : {pin.get("pinnacle_edge", "N/A")}%
  Signal Pinnacle       : {pin.get("signal", "N/A")}
  Favori Pinnacle       : {pin.get("favored", "N/A")}
⚠️ Signal FORT (≥5%) ou MODÉRÉ (≥3%) = confirmation value bet forte.
"""

    # ── Section moteur de projection (NOUVEAU) ──
    prob_btts    = math_results.get("prob_btts",    0)
    prob_no_btts = math_results.get("prob_no_btts", 0)
    prob_over    = math_results.get("prob_over",    0)
    prob_under   = math_results.get("prob_under",   0)
    prob_home    = math_results.get("prob_home",    0)
    prob_draw    = math_results.get("prob_draw",    0)
    prob_away    = math_results.get("prob_away",    0)
    mass         = math_results.get("mass_captured", 0)

    if mode == "A":
        mode_label   = "A — Dixon-Coles (stats réelles)"
        value_method = "Comparaison prob Poisson vs prob implicite marché."
        alignment_section = ""
    else:
        mode_label   = "B — Poisson calibré depuis les cotes (pas de stats réelles)"
        value_method = (
            "⚠️ Mode B : les probs Poisson sont dérivées du marché.\n"
            "  → Ne PAS comparer nos probs aux cotes du même marché.\n"
            "  → Value bet uniquement via signal Pinnacle.\n"
            "  → Ce moteur est un moteur de PROJECTION (scores, BTTS, O/U)."
        )
        score = alignment.get("market_alignment_score", 0)
        quality = alignment.get("alignment_quality", "?")
        interp  = alignment.get("interpretation", "")
        diffs   = alignment.get("diffs", {})
        alignment_section = f"""
=== MARKET ALIGNMENT SCORE (qualité de la projection) ===
  Score       : {score}/100 — {quality}
  Interprétation : {interp}
  Écarts Poisson vs Marché :
    - {home_team} : {diffs.get("home_diff", "?")}%
    - Nul         : {diffs.get("draw_diff", "?")}%
    - {away_team} : {diffs.get("away_diff", "?")}%
    - Over/Under  : {diffs.get("over_diff", "?")}%
"""

    projection_section = f"""
=== MOTEUR DE PROJECTION POISSON ===
Mode          : {mode_label}
λ {home_team} : {math_results.get("lambda_home", "?")}
λ {away_team} : {math_results.get("lambda_away", "?")}
Masse probabiliste capturée : {mass}%

Probabilités reconstruites (matrice 12x12) :
  Victoire {home_team} : {round(prob_home * 100, 1)}%
  Match nul            : {round(prob_draw * 100, 1)}%
  Victoire {away_team} : {round(prob_away * 100, 1)}%
  Over {odds_data.get("over_line", 2.5)} buts  : {round(prob_over  * 100, 1)}%
  Under {odds_data.get("over_line", 2.5)} buts : {round(prob_under * 100, 1)}%
  BTTS Oui             : {round(prob_btts    * 100, 1)}%
  BTTS Non             : {round(prob_no_btts * 100, 1)}%

Score le plus probable : {math_results.get("best_score", "?")}
Top 5 scores :
{_format_top_scores(math_results.get("top_scores", [])[:5])}

Méthode value bet : {value_method}
{alignment_section}"""

    # ── Prompt complet ──
    prompt = f"""Evalue ce match et decide si c'est un bon pari.

=== MATCH ===
{home_team} vs {away_team}
Competition : {league}
Bookmakers disponibles : {odds_data.get("bookmaker_count", 0)} ({", ".join(odds_data.get("bookmaker_names", [])[:5])})
{"✅ Stats réelles disponibles" if has_real_stats else "❌ Pas de stats réelles — Mode B actif"}
{projection_section}
{pinnacle_section}
=== COTES MARCHÉ MOYEN ===

MARCHÉ 1X2 :
  Victoire {home_team} : {odds_data.get("odds_home", "N/A")}
  Match Nul            : {odds_data.get("odds_draw", "N/A")}
  Victoire {away_team} : {odds_data.get("odds_away", "N/A")}

MARCHÉ HANDICAP :
  {home_team} ({odds_data.get("handicap_home_line", "N/A")}) : {odds_data.get("handicap_home", "N/A")}
  {away_team} ({odds_data.get("handicap_away_line", "N/A")}) : {odds_data.get("handicap_away", "N/A")}

MARCHÉ OVER/UNDER :
  Over {odds_data.get("over_line", 2.5)} buts  : {odds_data.get("over_odds",  "N/A")}
  Under {odds_data.get("under_line", 2.5)} buts : {odds_data.get("under_odds", "N/A")}

=== TA MISSION ===
1. Mode {mode} actif — applique les règles value bet correspondantes
2. La cote finale DOIT être entre 1.40 et 2.00
3. Confiance MAX = {"4/4" if has_real_stats else "2/4"}
4. Si aucune opportunité → REJETE
5. Utilise le market_alignment_score pour juger la fiabilité de la projection
6. Recherche sur le web :
   - blessures importantes
   - suspensions
   - forme récente
   - confrontations directes récentes
   - informations terrain pertinentes

7. Si les informations web contredisent fortement le modèle,
   privilégie les informations terrain.

Reponds UNIQUEMENT en JSON pur (pas de markdown, pas de texte avant/apres)."""

    headers = {
        "Content-Type":      "application/json",
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
   payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 2000,
        "system":     SYSTEM_PROMPT,
        "tools": [
            {
                "type": "web_search_20250305",
                "name": "web_search"
            }
        ],
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.post(API_URL, headers=headers, json=payload)
            if r.status_code == 200:
                text = r.json()["content"][0]["text"].strip()
                text = text.replace("```json", "").replace("```", "").strip()
                result = json.loads(text)

                # Rétrocompatibilité ancien format plat
                if "analyse_fr" in result and "analyse" not in result:
                    result["analyse"] = {
                        "fr": result.pop("analyse_fr", ""),
                        "en": result.pop("analyse_en", ""),
                    }
                if "points_cles_fr" in result and "points_cles" not in result:
                    result["points_cles"] = {
                        "fr": result.pop("points_cles_fr", []),
                        "en": result.pop("points_cles_en", []),
                    }
                if "verdict_fr" in result and "verdict" not in result:
                    result["verdict"] = {
                        "fr": result.pop("verdict_fr", ""),
                        "en": result.pop("verdict_en", ""),
                    }

                logger.info(
                    f"  Claude decision : {result.get('decision')} | "
                    f"Marche : {result.get('marche_choisi')} | "
                    f"Cote : {result.get('cote_choisie')} | "
                    f"Confiance : {result.get('confiance')}/4 | "
                    f"Mode : {mode} | "
                    f"Alignment : {alignment.get('market_alignment_score', 'N/A')}/100"
                )
                return result
            else:
                logger.error(f"Claude API erreur {r.status_code}: {r.text[:300]}")
        except json.JSONDecodeError as e:
            logger.error(f"Claude JSON parse error: {e}")
        except Exception as e:
            logger.error(f"Claude error: {e}")

    return {"decision": "REJETE", "raison_rejet": "Erreur API Claude"}


def _format_top_scores(top_scores: list) -> str:
    """Formate les top scores pour le prompt."""
    if not top_scores:
        return "  Aucun score disponible"
    lines = []
    for s in top_scores:
        lines.append(f"  {s['score']} → {s['prob']}%")
    return "\n".join(lines)


async def generate_montante_analysis(match: Dict) -> Tuple[Dict, Dict]:
    """Analyse pour la montante."""
    if not ANTHROPIC_API_KEY:
        return _empty_fr(match), _empty_en(match)

    prompt = f"""Analyse cette montante (1 match tres sur, cote 1.20-1.50) :

Match : {match["home_team"]} vs {match["away_team"]}
Ligue : {match["league"]}
Pronostic : {match["prediction"]} @ {match["odds"]}
Probabilite estimee : {match.get("prob", "?")}%
Confiance : {match.get("confiance", "?")}/4

Explique pourquoi ce match est sur pour une montante.
Reponds en JSON : {{"fr": {{"analysis":"...", "key_points":[], "verdict":""}}, "en": {{"analysis":"...", "key_points":[], "verdict":""}}}}"""

    headers = {
        "Content-Type":      "application/json",
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 800,
        "system":     "Tu es expert en paris sportifs. Reponds uniquement en JSON pur, aucun markdown.",
        "messages":   [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(API_URL, headers=headers, json=payload)
            if r.status_code == 200:
                text = r.json()["content"][0]["text"].strip()
                text = text.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(text)
                return parsed["fr"], parsed["en"]
        except Exception as e:
            logger.error(f"Montante analysis error: {e}")

    return _empty_fr(match), _empty_en(match)


async def generate_combined_analysis(matches: list, total_odds: float) -> Tuple[Dict, Dict]:
    """Analyse pour le combine (3 matchs, cote totale 2.50-4.00)."""
    if not ANTHROPIC_API_KEY:
        return {"analysis": "Combine selectionne.", "key_points": [], "verdict": ""}, \
               {"analysis": "Combo selected.",      "key_points": [], "verdict": ""}

    lines = "\n".join([
        f"{i+1}. {m['home_team']} vs {m['away_team']} -> {m['prediction']} @ {m['odds']}"
        for i, m in enumerate(matches)
    ])

    prompt = f"""Analyse ce combine de 3 matchs (cote totale : {total_odds}) :
{lines}

Explique la strategie et conseille la mise.
Reponds en JSON : {{"fr": {{"analysis":"...", "key_points":[], "verdict":""}}, "en": {{"analysis":"...", "key_points":[], "verdict":""}}}}"""

    headers = {
        "Content-Type":      "application/json",
        "x-api-key":         ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model":      CLAUDE_MODEL,
        "max_tokens": 800,
        "system":     "Tu es expert en paris sportifs. Reponds uniquement en JSON pur, aucun markdown.",
        "messages":   [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(API_URL, headers=headers, json=payload)
            if r.status_code == 200:
                text = r.json()["content"][0]["text"].strip()
                text = text.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(text)
                return parsed["fr"], parsed["en"]
        except Exception as e:
            logger.error(f"Combined error: {e}")

    return {"analysis": "Combine selectionne.", "key_points": [], "verdict": ""}, \
           {"analysis": "Combo selected.",      "key_points": [], "verdict": ""}


def _empty_fr(match):
    return {"analysis": f"Analyse {match.get('home_team','?')} vs {match.get('away_team','?')}.", "key_points": [], "verdict": ""}

def _empty_en(match):
    return {"analysis": f"Analysis {match.get('home_team','?')} vs {match.get('away_team','?')}.", "key_points": [], "verdict": ""}
