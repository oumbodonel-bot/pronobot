"""
Claude AI - Juge unique des pronostics
Claude recoit TOUT et decide seul : valide ou rejette, choisit le marche
Modele : claude-3-5-sonnet-20240620
"""
import os
import json
import logging
import asyncio
from typing import Dict, Tuple, Optional
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = "claude-3-5-sonnet-20240620"
client            = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# System Prompt optimisé (plus court, plus direct)
SYSTEM_PROMPT = """Tu es l'expert EliteOddsClub. Analyse les données fournies pour décider d'un pari.

RÈGLES STRICTES :
1. PLAFONNEMENT : Max 85% probabilité affichée.
2. SÉLECTION :
   - /gratuit : [1.40 - 2.00]
   - /montante : [1.20 - 1.50]
   - /combine : 3 matchs, total [2.50 - 4.00]
3. VALEUR :
   - MODE A (Stats) : prob_stat > prob_implicite + 2% => VALIDE.
   - MODE B (Poisson) : Signal Pinnacle FORT (≥5%) ou MODÉRÉ (≥3%) => VALIDE. Sinon, market_alignment ≥ 70.
4. FORMAT : JSON pur uniquement.

JSON structure:
{
  "decision": "VALIDE" | "REJETE",
  "raison_rejet": "string",
  "marche_choisi": "1X2" | "Handicap" | "Over/Under",
  "pronostic": "Texte court",
  "cote_choisie": float,
  "confiance": 1-4,
  "analyse": {"fr": "...", "en": "..."},
  "points_cles": {"fr": [], "en": []},
  "verdict": {"fr": "...", "en": "..."}
}"""

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
        return {"decision": "REJETE", "raison_rejet": "API Key missing"}

    mode = math_results.get("mode", "B")
    alignment = math_results.get("alignment", {})
    pin = math_results.get("pinnacle", {})
    
    # Construction d'un prompt ultra-compact
    compact_data = {
        "match": f"{home_team} vs {away_team} ({league})",
        "mode": mode,
        "stats_avail": math_results.get("has_real_stats", False),
        "lambdas": [math_results.get("lambda_home"), math_results.get("lambda_away")],
        "probs": {
            "1X2": [round(math_results.get("prob_home", 0)*100, 1), round(math_results.get("prob_draw", 0)*100, 1), round(math_results.get("prob_away", 0)*100, 1)],
            "O/U": [round(math_results.get("prob_over", 0)*100, 1), round(math_results.get("prob_under", 0)*100, 1)],
            "BTTS": [round(math_results.get("prob_btts", 0)*100, 1)]
        },
        "best_score": math_results.get("best_score"),
        "pinnacle": {"signal": pin.get("signal"), "edge": pin.get("pinnacle_edge")},
        "alignment": alignment.get("market_alignment_score"),
        "market_odds": {
            "1X2": [odds_data.get("odds_home"), odds_data.get("odds_draw"), odds_data.get("odds_away")],
            "O/U": [odds_data.get("over_odds"), odds_data.get("under_odds")]
        }
    }

    user_content = f"Evaluate: {json.dumps(compact_data)}"

    if not client:
        return {"decision": "REJETE", "raison_rejet": "Client Anthropic non initialisé"}

    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}]
            )
            
            text = response.content[0].text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            
            result = json.loads(text.strip())
            logger.info(f"Claude decision for {home_team}: {result.get('decision')}")
            return result

        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed for {home_team}: {e}")
            if "rate_limit" in str(e).lower():
                wait = (attempt + 1) * 5
                await asyncio.sleep(wait)
                continue
            if attempt == 2: break
            await asyncio.sleep(2)

    return {"decision": "REJETE", "raison_rejet": "Claude API Error"}

def _format_top_scores(top_scores: list) -> str:
    return ", ".join([f"{s['score']} ({s['prob']}%)" for s in top_scores[:3]])

async def generate_montante_analysis(match: Dict) -> Tuple[Dict, Dict]:
    # Version simplifiée pour réduire les tokens
    return await _simple_gen("montante", match)

async def generate_combined_analysis(matches: list, total_odds: float) -> Tuple[Dict, Dict]:
    # Version simplifiée pour réduire les tokens
    data = {"type": "combined", "odds": total_odds, "matches": matches}
    return await _simple_gen("combined", data)

async def _simple_gen(type_label: str, data: Dict) -> Tuple[Dict, Dict]:
    if not client:
        empty = {"analysis": "Analyse indisponible", "key_points": [], "verdict": "Pari sélectionné par l'algorithme."}
        return empty, empty
    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600,
            system="Tu es un expert en paris. Réponds uniquement en JSON: {\"fr\": {\"analysis\":\"...\", \"key_points\":[], \"verdict\":\"\"}, \"en\": {...}}",
            messages=[{"role": "user", "content": f"Analyze {type_label}: {json.dumps(data)}"}]
        )
        text = response.content[0].text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        parsed = json.loads(text.strip())
        return parsed["fr"], parsed["en"]
    except Exception as e:
        logger.error(f"Simple gen error: {e}")
        empty = {"analysis": "Analyse indisponible", "key_points": [], "verdict": "Pari sélectionné par l'algorithme."}
        return empty, empty
