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

SYSTEM_PROMPT = """Tu es un expert en paris sportifs de niveau professionnel.
Tu analyses les donnees mathematiques et les cotes bookmakers pour evaluer chaque match.

REGLES ABSOLUES :
- La cote finale choisie DOIT etre entre 1.30 et 2.20 (prono individuel)
- Si AUCUN marche ne propose une cote dans cette plage -> REJETER le match
- Tu ne promets JAMAIS la victoire
- Tu te bases UNIQUEMENT sur les donnees fournies

STRUCTURE DE REPONSE (JSON pur, rien d'autre) :
{
  "decision": "VALIDE" ou "REJETE",
  "raison_rejet": "Explication si REJETE (sinon null)",
  "marche_choisi": "1X2" ou "Handicap" ou "Over/Under" (si VALIDE),
  "pronostic": "Ex: Victoire domicile (1)" (si VALIDE),
  "cote_choisie": 1.75 (float, si VALIDE),
  "confiance": 4 (entier 1-5, si VALIDE),
  "analyse_fr": "Analyse 150 mots en francais (si VALIDE)",
  "analyse_en": "150 word analysis in English (si VALIDE)",
  "points_cles_fr": ["point 1", "point 2", "point 3"],
  "points_cles_en": ["point 1", "point 2", "point 3"],
  "verdict_fr": "Verdict court en francais",
  "verdict_en": "Short verdict in English"
}"""


async def evaluate_match(
    home_team:  str,
    away_team:  str,
    league:     str,
    home_stats: Optional[Dict],
    away_stats: Optional[Dict],
    odds_data:  Dict,
    math_results: Dict,
) -> Dict:
    """
    Claude evalue le match et decide seul.
    Retourne le JSON de decision complet.
    """
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY manquant!")
        return {"decision": "REJETE", "raison_rejet": "API Claude non configuree"}

    # Construire le prompt avec TOUTES les donnees
    home_form = home_stats.get("form_string", "N/A") if home_stats else "N/A"
    away_form = away_stats.get("form_string", "N/A") if away_stats else "N/A"
    home_avg  = home_stats.get("avg_scored",  "?")   if home_stats else "?"
    away_avg  = away_stats.get("avg_scored",  "?")   if away_stats else "?"
    home_conc = home_stats.get("avg_conceded","?")   if home_stats else "?"
    away_conc = away_stats.get("avg_conceded","?")   if away_stats else "?"
    home_xg   = home_stats.get("xg", "?")            if home_stats else "?"
    away_xg   = away_stats.get("xg", "?")            if away_stats else "?"

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
  Match Nul : {odds_data.get("odds_draw", "N/A")}
  Victoire {away_team} : {odds_data.get("odds_away", "N/A")}

MARCHE HANDICAP :
  {home_team} ({odds_data.get("handicap_home_line", "N/A")}) : {odds_data.get("handicap_home", "N/A")}
  {away_team} ({odds_data.get("handicap_away_line", "N/A")}) : {odds_data.get("handicap_away", "N/A")}

MARCHE OVER/UNDER :
  Over {odds_data.get("over_line", 2.5)} buts : {odds_data.get("over_odds", "N/A")}
  Under {odds_data.get("under_line", 2.5)} buts : {odds_data.get("under_odds", "N/A")}

=== TA MISSION ===
1. Compare les probabilites mathematiques avec les cotes bookmakers
2. Identifie le marche avec le meilleur Value Bet
3. IMPORTANT : La cote finale choisie DOIT etre entre 1.30 et 2.20
4. Si aucune cote dans cette plage -> REJETER
5. Valide ou Rejette le match avec justification

Reponds UNIQUEMENT en JSON pur (pas de markdown, pas de texte avant/apres)."""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
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
                logger.info(
                    f"  Claude decision : {result.get('decision')} | "
                    f"Marche : {result.get('marche_choisi')} | "
                    f"Cote : {result.get('cote_choisie')} | "
                    f"Confiance : {result.get('confiance')}/5"
                )
                return result
            else:
                logger.error(f"Claude API erreur {r.status_code}: {r.text[:300]}")
        except json.JSONDecodeError as e:
            logger.error(f"Claude JSON parse error: {e}")
        except Exception as e:
            logger.error(f"Claude error: {e}")

    return {"decision": "REJETE", "raison_rejet": f"Erreur API Claude"}


async def generate_montante_analysis(match: Dict) -> Tuple[Dict, Dict]:
    """Analyse pour la montante."""
    if not ANTHROPIC_API_KEY:
        return _empty_fr(match), _empty_en(match)

    prompt = f"""Analyse cette montante (1 match tres sur, cote 1.20-1.50) :

Match : {match["home_team"]} vs {match["away_team"]}
Ligue : {match["league"]}
Pronostic : {match["prediction"]} @ {match["odds"]}
Probabilite estimee : {match.get("prob", "?")}%
Confiance : {match.get("confiance", "?")}/5

Explique pourquoi ce match est sur pour une montante.
Reponds en JSON : {{"fr": {{"analysis":"...", "key_points":[], "verdict":""}}, "en": {{"analysis":"...", "key_points":[], "verdict":""}}}}"""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": CLAUDE_MODEL, "max_tokens": 800,
        "system": "Tu es expert en paris sportifs. Reponds uniquement en JSON.",
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(API_URL, headers=headers, json=payload)
            if r.status_code == 200:
                text = r.json()["content"][0]["text"].strip()
                text = text.replace("```json","").replace("```","").strip()
                parsed = json.loads(text)
                return parsed["fr"], parsed["en"]
        except Exception as e:
            logger.error(f"Montante analysis error: {e}")

    return _empty_fr(match), _empty_en(match)


async def generate_combined_analysis(matches: list, total_odds: float) -> Tuple[Dict, Dict]:
    """Analyse pour le combine (3 matchs, cote max 3.00)."""
    if not ANTHROPIC_API_KEY:
        return {"analysis": "Combine selectionne.", "key_points": [], "verdict": ""}, \
               {"analysis": "Combo selected.", "key_points": [], "verdict": ""}

    lines = "\n".join([
        f"{i+1}. {m['home_team']} vs {m['away_team']} → {m['prediction']} @ {m['odds']}"
        for i, m in enumerate(matches)
    ])

    prompt = f"""Analyse ce combine de 3 matchs (cote totale : {total_odds}) :
{lines}

Explique la strategie et conseille la mise.
Reponds en JSON : {{"fr": {{"analysis":"...", "key_points":[], "verdict":""}}, "en": {{"analysis":"...", "key_points":[], "verdict":""}}}}"""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": CLAUDE_MODEL, "max_tokens": 800,
        "system": "Tu es expert en paris sportifs. Reponds uniquement en JSON.",
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        try:
            r = await client.post(API_URL, headers=headers, json=payload)
            if r.status_code == 200:
                text = r.json()["content"][0]["text"].strip()
                text = text.replace("```json","").replace("```","").strip()
                parsed = json.loads(text)
                return parsed["fr"], parsed["en"]
        except Exception as e:
            logger.error(f"Combined error: {e}")

    return {"analysis": "Combine selectionne.", "key_points": [], "verdict": ""}, \
           {"analysis": "Combo selected.", "key_points": [], "verdict": ""}


def _empty_fr(match): return {"analysis": f"Analyse {match.get('home_team','?')} vs {match.get('away_team','?')}.", "key_points": [], "verdict": ""}
def _empty_en(match): return {"analysis": f"Analysis {match.get('home_team','?')} vs {match.get('away_team','?')}.", "key_points": [], "verdict": ""}
