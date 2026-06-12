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
SYSTEM_PROMPT = """Tu es l'expert EliteOddsClub. Ta mission est de TROUVER un pari valide parmi les marchés fournis.
Sois souple : si un marché a une probabilité > 55% ou un léger avantage, VALIDE-LE.
Réponds UNIQUEMENT en JSON compact:
{"decision":"VALIDE"|"REJETE","raison":"Court","pari":"Label","cote":1.8,"confiance":1-5}
Favorise la validation (VALIDE) si les données sont cohérentes. INTERDIT: blabla, markdown."""

async def get_claude_decision(home_team: str, away_team: str, match_data: Dict, analysis_data: Dict) -> Dict:
    if not client:
        return {"decision": "REJETE", "raison": "Claude non configuré"}

    # Compactage des données envoyées
    user_content = f"Match: {home_team}-{away_team}. Data: {json.dumps(analysis_data)}"

    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=150, # Très court
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

    prompt = "Expert paris. Réponds UNIQUEMENT en JSON: {\"fr\":{\"analysis\":\"...\",\"key_points\":[],\"verdict\":\"\"},\"en\":{...}}. Max 2 phrases."
    
    try:
        response = await client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=600, # Augmenté pour éviter la troncature
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
