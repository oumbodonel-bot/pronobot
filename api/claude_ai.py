import os
import json
import logging
import asyncio
import re
from typing import Dict, Optional, Tuple
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL      = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")
client            = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# System Prompt ultra-compact et pro-validation
SYSTEM_PROMPT = """Tu es l'IA experte de "EliteOddsClub", un service de pronostics professionnels.
Ta mission : Identifier les opportunités de pari les plus cohérentes.
──────────────────────────── RÈGLES ────────────────────────────
1. NE REJETTE PAS systématiquement. Si les cotes sont logiques et les stats Poisson cohérentes, VALIDE le match.
2. CONFIANCE : 1=Faible, 2=Modérée, 3=Élevée, 4=Très élevée.
3. VALUE : probabilité_estimee - probabilité_implicite. Même une value de 0% ou légèrement négative est VALIDABLE si le favori est solide.
4. MARCHÉS : Privilégie 1X2, Double Chance, Over/Under 2.5, Draw No Bet.
──────────────────────────── DIRECTIVES ────────────────────────────
Réponse JSON compacte uniquement. Aucun commentaire.
{
"decision": "VALIDE/REJETE",
"raison_rejet": "Si rejeté, max 1 phrase",
"marche_choisi": "Nom du marché",
"pronostic": "Sélection précise",
"cote_choisie": 0.00,
"confiance": 1-4,
"value_pct": 0.0
}"""

async def get_claude_decision(home_team: str, away_team: str, match_data: Dict, analysis_data: Dict) -> Dict:
    if not client:
        return {"decision": "REJETE", "raison": "Claude non configuré"}

    # Compactage des données envoyées
    user_content = f"Match: {home_team}-{away_team}. Data: {json.dumps(analysis_data)}"

    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=300, # Réduit pour économie
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}]
            )
            
            raw_text = response.content[0].text.strip()
            
            # Nettoyage et extraction JSON
            result = parse_claude_json(raw_text)
            if result:
                logger.info(f"Claude decision for {home_team}: {result.get('decision')}")
                return result
            
            raise ValueError(f"Parsing failed for: {raw_text[:100]}...")

        except Exception as e:
            logger.error(f"Attempt {attempt+1} failed for {home_team}: {e}")
            if "rate_limit" in str(e).lower():
                await asyncio.sleep(5 * (attempt + 1))
            else:
                await asyncio.sleep(1)

    return {"decision": "REJETE", "raison": "Claude API Error"}

def parse_claude_json(text: str) -> Optional[Dict]:
    """Parsing JSON ultra-robuste avec réparation de troncature."""
    try:
        # Nettoyage basique
        text = text.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        
        text = text.strip()
        
        # Réparation de troncature (fermeture d'accolades et guillemets)
        if text.startswith("{") and not text.endswith("}"):
            # Réparation plus robuste des structures imbriquées
            # On ferme les guillemets ouverts
            if text.count('"') % 2 != 0:
                text += '"'
            
            # On ferme les accolades manquantes
            open_braces = text.count('{')
            close_braces = text.count('}')
            if open_braces > close_braces:
                text += '}' * (open_braces - close_braces)
            
            # On ferme les crochets manquants
            open_brackets = text.count('[')
            close_brackets = text.count(']')
            if open_brackets > close_brackets:
                text += ']' * (open_brackets - close_brackets)
            
        # Tentative de parsing direct
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Tentative via regex pour extraire le premier objet JSON valide
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except:
                    pass
        
        # Si toujours rien, logger la réponse brute pour debug
        logger.error(f"ÉCHEC PARSING JSON. Réponse brute: {text}")
        return None
    except Exception as e:
        logger.error(f"Erreur fatale dans parse_claude_json: {e}")
        return None

async def generate_simple_analysis(type_label: str, data: Dict) -> Tuple[Dict, Dict]:
    """Génère une analyse courte pour les pronos."""
    if not client:
        empty = {"analysis": "Non dispo", "key_points": [], "verdict": "Auto"}
        return empty, empty

    prompt = "Tu es l'IA experte de EliteOddsClub. Fournis une analyse d'UNE SEULE PHRASE courte et objective. Réponds UNIQUEMENT en JSON compact: {\"fr\":{\"analysis\":\"...\"},\"en\":{\"analysis\":\"...\"}}. Aucun autre champ."
    
    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=300, # Réduit pour économie
            temperature=0,
            system=prompt,
            messages=[{"role": "user", "content": f"Analyse {type_label}: {json.dumps(data)}"}]
        )
        parsed = parse_claude_json(response.content[0].text)
        if parsed and "fr" in parsed and "en" in parsed:
            return parsed["fr"], parsed["en"]
    except Exception as e:
        logger.error(f"Simple gen error: {e}")
    
    empty = {"analysis": "Analyse auto", "key_points": [], "verdict": "Pari validé."}
    return empty, empty
