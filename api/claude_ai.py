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

3. VALEUR (VALUE BET) : Un pari n'est VALIDE que si la probabilité statistique (Poisson)
   dépasse la probabilité implicite de la cote bookmaker d'au moins +5%.
   Formule : prob_implicite = 1 / cote. Si prob_stat < prob_implicite + 0.05 -> REJETE.

4. DONNÉES MANQUANTES :
   - Si les cotes bookmaker sont absentes -> décision = "REJETE", raison = "Données de cotes indisponibles".
   - Si les stats réelles sont absentes -> confiance plafonnée à 2/4. Le pari reste validable sur value bet.
   - Ne jamais estimer, inventer ou extrapoler des statistiques manquantes.

5. ABSENCE DE STATS : Les cotes bookmakers agrègent toute l'information du marché.
   En l'absence de stats d'équipe, les cotes ET le modèle Poisson sont suffisants pour détecter un value bet.
   Si Pinnacle disponible : un écart Pinnacle > marché est un signal value bet fort.
   Confiance MAX = 2/4 sans stats réelles.

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

    # Pinnacle disponible ?
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
  Écart Pinnacle/marché (domicile) : {odds_data.get("pinnacle_gap", "N/A")}
⚠️ Un écart Pinnacle > marché = signal value bet fort.
"""

    prompt = f"""Evalue ce match et decide si c'est un bon pari.

=== MATCH ===
{home_team} vs {away_team}
Competition : {league}
Bookmakers disponibles : {odds_data.get("bookmaker_count", 0)} ({", ".join(odds_data.get("bookmaker_names", [])[:5])})

=== NOTE IMPORTANTE ===
Aucune statistique d'équipe disponible.
Analyse basée sur : cotes bookmakers + modèle Poisson + {"cotes Pinnacle (sharp)" if has_pinnacle else "moyenne marché uniquement"}.
Les cotes bookmakers agrègent l'information du marché et sont une source fiable de probabilités implicites.
Confiance MAX = 2/4 dans ce contexte.

=== MODÈLES MATHÉMATIQUES (Poisson basé sur les cotes) ===
Buts attendus {home_team} : {math_results.get("lambda_home", "?")}
Buts attendus {away_team} : {math_results.get("lambda_away", "?")}
Probabilité victoire {home_team} : {math_results.get("prob_home_win", "?")}%
Probabilité match nul           : {math_results.get("prob_draw", "?")}%
Probabilité victoire {away_team} : {math_results.get("prob_away_win", "?")}%
Over 2.5 buts  : {math_results.get("prob_over25", "?")}%
Under 2.5 buts : {100 - math_results.get("prob_over25", 50) if math_results.get("prob_over25") else "?"}%
Score le plus probable : {math_results.get("best_score", "?")}
{pinnacle_section}
=== COTES MARCHÉ MOYEN (tous bookmakers) ===

MARCHE 1X2 :
  Victoire {home_team} : {odds_data.get("odds_home", "N/A")}
  Match Nul            : {odds_data.get("odds_draw", "N/A")}
  Victoire {away_team} : {odds_data.get("odds_away", "N/A")}

MARCHE HANDICAP :
  {home_team} ({odds_data.get("handicap_home_line", "N/A")}) : {odds_data.get("handicap_home", "N/A")}
  {away_team} ({odds_data.get("handicap_away_line", "N/A")}) : {odds_data.get("handicap_away", "N/A")}

MARCHE OVER/UNDER :
  Over {odds_data.get("over_line", 2.5)} buts  : {odds_data.get("over_odds",  "N/A")}
  Under {odds_data.get("under_line", 2.5)} buts : {odds_data.get("under_odds", "N/A")}

=== TA MISSION ===
1. Applique la règle Value Bet : prob_stat doit dépasser (1 / cote) + 0.05
2. Si Pinnacle disponible : un écart Pinnacle > marché renforce le signal
3. La cote finale DOIT être entre 1.40 et 2.00
4. Si aucun value bet détecté -> REJETE
5. Confiance MAX = 2/4 (pas de stats réelles disponibles)
6. Si moins de 3 bookmakers disponibles -> REJETE (marché peu liquide)

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
        "messages":   [{"role": "user", "content": prompt}],
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
                    f"Confiance : {result.get('confiance')}/4"
                )
                return result
            else:
                logger.error(f"Claude API erreur {r.status_code}: {r.text[:300]}")
        except json.JSONDecodeError as e:
            logger.error(f"Claude JSON parse error: {e}")
        except Exception as e:
            logger.error(f"Claude error: {e}")

    return {"decision": "REJETE", "raison_rejet": "Erreur API Claude"}


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


def _empty_fr(match): return {"analysis": f"Analyse {match.get('home_team','?')} vs {match.get('away_team','?')}.", "key_points": [], "verdict": ""}
def _empty_en(match): return {"analysis": f"Analysis {match.get('home_team','?')} vs {match.get('away_team','?')}.", "key_points": [], "verdict": ""}
