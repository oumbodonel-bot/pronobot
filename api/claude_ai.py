"""
Claude AI - Analyses narratives professionnelles
Modele : claude-sonnet-4-6
"""
import os
import httpx
import json
import logging
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-sonnet-4-6"
API_URL           = "https://api.anthropic.com/v1/messages"

SYSTEM_PROMPT = """Tu es un expert en analyse sportive et paris sportifs de niveau professionnel.
Tu analyses les donnees mathematiques (Loi de Poisson, Dixon-Coles, xG, Elo, Value Bet, Kelly) pour generer des pronostics.

REGLES STRICTES :
- Tu analyses UNIQUEMENT les donnees fournies, jamais de valeurs inventees
- Tu ne promets JAMAIS la victoire
- Tu rappelles toujours le risque des paris
- Ton analyse doit etre specifique au match, pas generique

Reponds UNIQUEMENT en JSON valide :
{
  "fr": {
    "analysis": "Analyse de 150-200 mots specifique a ce match",
    "key_points": ["3 points cles specifiques"],
    "verdict": "Verdict court et precis"
  },
  "en": {
    "analysis": "150-200 word analysis specific to this match",
    "key_points": ["3 specific key points"],
    "verdict": "Short precise verdict"
  }
}"""


async def generate_match_analysis(
    home_team: str,
    away_team: str,
    league: str,
    home_stats: Dict,
    away_stats: Dict,
    math_results: Dict,
    prediction: str,
    odds: float,
) -> Tuple[Dict, Dict]:
    """Genere une vraie analyse narrative via Claude."""

    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY manquant!")
        return _empty_analysis(home_team, away_team)

    home_form = home_stats.get("form_string", "N/A") if home_stats else "N/A"
    away_form = away_stats.get("form_string", "N/A") if away_stats else "N/A"
    home_avg  = home_stats.get("avg_scored", "?") if home_stats else "?"
    away_avg  = away_stats.get("avg_scored", "?") if away_stats else "?"

    prompt = f"""Analyse ce match pour un pronostic professionnel :

MATCH : {home_team} vs {away_team}
COMPETITION : {league}

STATISTIQUES REELLES :
- Forme recente {home_team} : {home_form} (W=Victoire D=Nul L=Defaite)
- Forme recente {away_team} : {away_form}
- Buts/match {home_team} : {home_avg}
- Buts/match {away_team} : {away_avg}
- xG {home_team} : {home_stats.get('xg', '?') if home_stats else '?'}
- xG {away_team} : {away_stats.get('xg', '?') if away_stats else '?'}

MODELES MATHEMATIQUES :
- Buts attendus {home_team} : {math_results.get('lambda_home', '?')}
- Buts attendus {away_team} : {math_results.get('lambda_away', '?')}
- Probabilite victoire {home_team} : {math_results.get('prob_home_win', '?')}%
- Probabilite nul : {math_results.get('prob_draw', '?')}%
- Probabilite victoire {away_team} : {math_results.get('prob_away_win', '?')}%
- Over 2.5 buts : {math_results.get('prob_over25', '?')}%
- BTTS (les deux marquent) : {math_results.get('prob_btts', '?')}%
- Score le plus probable : {math_results.get('best_score', '?')}
- Value Bet : {math_results.get('value_bet', '?')}%
- Confiance : {math_results.get('stars', '?')}/5 etoiles

PRONOSTIC SELECTIONNE : {prediction} @ {odds}

Genere une analyse professionnelle specifique a ce match en JSON."""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }

    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1500,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }

    async with httpx.AsyncClient(timeout=45) as client:
        try:
            r = await client.post(API_URL, headers=headers, json=payload)
            if r.status_code == 200:
                data = r.json()
                text = data["content"][0]["text"].strip()
                # Nettoyer si markdown
                text = text.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(text)
                logger.info(f"  Claude analyse generee pour {home_team} vs {away_team}")
                return parsed["fr"], parsed["en"]
            else:
                logger.error(f"Claude API erreur {r.status_code}: {r.text[:300]}")
        except json.JSONDecodeError as e:
            logger.error(f"Claude JSON parse error: {e}")
        except Exception as e:
            logger.error(f"Claude error: {e}")

    return _empty_analysis(home_team, away_team)


def _empty_analysis(home: str, away: str) -> Tuple[Dict, Dict]:
    """Retourne une analyse vide (pas de donnees inventees)."""
    fr = {
        "analysis": f"Analyse en cours pour {home} vs {away}.",
        "key_points": ["Donnees en cours de traitement"],
        "verdict": "Consultez notre canal pour l'analyse complete.",
    }
    en = {
        "analysis": f"Analysis pending for {home} vs {away}.",
        "key_points": ["Data being processed"],
        "verdict": "Check our channel for the complete analysis.",
    }
    return fr, en


async def generate_montante_analysis(match: Dict) -> Tuple[Dict, Dict]:
    """Analyse pour la montante (1 seul match)."""
    if not ANTHROPIC_API_KEY:
        return _empty_analysis(match.get("home_team","?"), match.get("away_team","?"))

    prompt = f"""Analyse cette montante (1 match tres sur) :

Match : {match['home_team']} vs {match['away_team']}
Ligue : {match['league']}
Pronostic : {match['prediction']} @ {match['odds']}
Probabilite estimee : {match.get('prob', '?')}%
Confiance : {match.get('stars', '?')}/5

Ce match a ete selectionne car c'est le match le plus sur du jour
avec une cote entre 1.20 et 1.50.

Explique pourquoi ce match est sur et conseille la mise.
Reponds en JSON (fr + en)."""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 800,
        "system": SYSTEM_PROMPT,
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

    return _empty_analysis(match.get("home_team","?"), match.get("away_team","?"))


async def generate_combined_analysis(matches: list, total_odds: float) -> Tuple[Dict, Dict]:
    """Analyse pour le combine du jour (3 matchs, cote max 3.00)."""
    if not ANTHROPIC_API_KEY:
        return {"analysis": "Combine du jour selectionne.", "key_points": [], "verdict": ""}, \
               {"analysis": "Daily combo selected.", "key_points": [], "verdict": ""}

    lines = "\n".join([
        f"{i+1}. {m['home_team']} vs {m['away_team']} → {m['prediction']} @ {m['odds']}"
        for i, m in enumerate(matches)
    ])

    prompt = f"""Analyse ce combine de 3 matchs :

{lines}

Cote totale : {total_odds}
(Cote max autorisee : 3.00)

Ces 3 matchs ont ete selectionnes car ils ont tous une cote
entre 1.30 et 2.20 et une confiance elevee.

Explique la strategie et conseille la mise.
Reponds en JSON (fr + en)."""

    headers = {
        "Content-Type": "application/json",
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": CLAUDE_MODEL,
        "max_tokens": 800,
        "system": SYSTEM_PROMPT,
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
            logger.error(f"Combined analysis error: {e}")

    fr = {"analysis": "Combine selectionne par notre algorithme.", "key_points": [], "verdict": ""}
    en = {"analysis": "Combo selected by our algorithm.", "key_points": [], "verdict": ""}
    return fr, en
