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

3. VALEUR (VALUE BET) : Un pari n'est VALIDE que si la probabilité statistique (xG/Poisson)
   dépasse la probabilité implicite de la cote bookmaker d'au moins +5%.
   Formule : prob_implicite = 1 / cote. Si prob_stat < prob_implicite + 0.05 -> REJETE.

4. DONNÉES MANQUANTES :
   - Si les cotes bookmaker sont absentes -> décision = "REJETE", raison = "Données de cotes indisponibles".
   - Si les stats récentes (forme, xG, H2H) sont absentes ou insuffisantes -> confiance <= 2.
   - Ne jamais estimer, inventer ou extrapoler des statistiques manquantes.

--- FORMAT DE RÉPONSE (JSON PUR — AUCUN TEXTE AVANT OU APRÈS) ---
{
  "decision": "VALIDE" | "REJETE",
  "raison_rejet": "string | null",
  "marche_choisi": "1X2" | "Handicap" | "Over/Under",
  "pronostic": "Texte du pari (ex: Under 2.5 buts)",
  "cote_choisie": <float>,
  "confiance": <Entier de 1 à 4>,
  "analyse": {
    "fr": "Analyse technique concise (xG, forme, H2H, justification mathématique). Maximum 150 mots.",
    "en": "Concise technical analysis (xG, form, H2H, mathematical reasoning). Max 150 words."
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
    """
    Claude evalue le match et decide seul.
    Retourne le JSON de decision complet.
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY manquant!")
        return {"decision": "REJETE", "raison_rejet": "API Claude non configuree"}

    home_form = home_stats.get("form_string",  "N/A") if home_stats else "N/A"
    away_form = away_stats.get("form_string",  "N/A") if away_stats else "N/A"
    home_avg  = home_stats.get("avg_scored",   "?")   if home_stats else "?"
    away_avg  = away_stats.get("avg_scored",   "?")   if away_stats else "?"
    home_conc = home_stats.get("avg_conceded", "?")   if home_stats else "?"
    away_conc = away_stats.get("avg_conceded", "?")   if away_stats else "?"
    home_xg   = home_stats.get("xg",           "?")   if home_stats else "?"
    away_xg   = away_stats.get("xg",           "?")   if away_stats else "?"

    prompt = f"""Evalue ce match et decide si c'est un bon pari.

=== MATCH ===
{home_team} vs {away_team}
Competition : {league}

=== STATISTIQUES REELLES ===
Forme recente {home_team} : {home_form}
Forme recente {away_team} : {away_form}
Buts marques/match {home_team} : {home_avg}
Buts marques/match {away_team} : {away_avg}
Buts encaisses/match {home_team} : {home_conc}
Buts encaisses/match {away_team} : {away_conc}
xG {home_team} : {home_xg}
xG {away_team} : {away_xg}

=== MODELES MATHEMATIQUES (Poisson + Dixon-Coles) ===
Buts attendus {home_team} : {math_results.get("lambda_home", "?")}
Buts attendus {away_team} : {math_results.get("lambda_away", "?")}
Probabilite victoire {home_team} : {math_results.get("prob_home_win", "?")}%
Probabilite match nul : {math_results.get("prob_draw", "?")}%
Probabilite victoire {away_team} : {math_results.get("prob_away_win", "?")}%
Over 2.5 buts : {math_results.get("prob_over25", "?")}%
Under 2.5 buts : {100 - math_results.get("prob_over25", 50) if math_results.get("prob_over25") else "?"}%
BTTS (les deux marquent) : {math_results.get("prob_btts", "?")}%
Score le plus probable : {math_results.get("best_score", "?")}

=== COTES BOOKMAKERS (moyennes multi-bookmakers) ===

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
2. Identifie le marché avec le meilleur Value Bet parmi les 3 marchés disponibles
3. La cote finale choisie DOIT être entre 1.40 et 2.00
4. Si aucune cote dans cette plage ou aucun value bet détecté -> REJETE
5. Si les stats sont absentes ou insuffisantes -> confiance <= 2

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

                # Adapter l'ancien format à la nouvelle structure imbriquée
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
