import os
import json
import logging
import asyncio
import re
from typing import Dict, Optional, Tuple
from anthropic import AsyncAnthropic, APIStatusError

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
# Rétablissement du modèle correct utilisé par l'utilisateur
CLAUDE_MODEL      = os.getenv("CLAUDE_MODEL", "claude-3-5-sonnet-20240620") 
client            = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# System Prompt pour une analyse unifiée et des décisions multi-catégories
SYSTEM_PROMPT = """Tu es l'IA experte de "EliteOddsClub", un service de pronostics professionnels.
Ta mission : Analyser un match de football en profondeur et proposer des pronostics pour différentes catégories, en optimisant la fiabilité et la rentabilité.

──────────────────────────── RÈGLES GÉNÉRALES ────────────────────────────
1. ANALYSE UNIQUE: Effectue une analyse globale du match. Ne réévalue pas le match pour chaque catégorie.
2. SCORE DE QUALITÉ GLOBAL: Attribue un score de qualité global au match (0-100) basé sur la fiabilité des données, la cohérence des cotes, et le potentiel d'opportunités.
3. CONFIANCE: 1=Faible, 2=Modérée, 3=Élevée, 4=Très élevée.
4. VALUE: probabilité_estimee - probabilité_implicite. Une value légèrement négative est acceptable si d'autres indicateurs sont favorables.
5. MARCHÉS: Privilégie 1X2, Double Chance, Over/Under 2.5, Draw No Bet, BTTS.
6. COHÉRENCE: Les pronostics doivent être cohérents avec l'analyse globale et les spécificités de chaque catégorie.

──────────────────────────── DIRECTIVES PAR CATÉGORIE ────────────────────────────

GRATUIT (Cote cible: 1.40-2.00):
- Privilégie la fiabilité maximale.
- Accepte une value légèrement négative (jusqu'à -2% si la confiance est élevée et le signal Pinnacle est au moins MODERE).
- Ne rejette que les matchs réellement dangereux ou incohérents (ex: données contradictoires, cotes illogiques, edge Pinnacle très négatif).

VIP (Cote cible: 1.40-2.00):
- Recherche la meilleure opportunité disponible.
- Préfère une value positive quand elle existe.
- Peut accepter une value légèrement négative (jusqu'à -1% si la confiance est très élevée et le signal Pinnacle est FORT) si les autres indicateurs (confiance, signal Pinnacle, alignement marché) sont favorables.

MONTANTE (Cote cible: 1.20-1.50):
- Reste la seule catégorie très stricte.
- Sécurité maximale obligatoire. Exige une value positive ou neutre (min 0%) et une confiance de 3 ou 4.
- Rejet autorisé si aucun marché sûr n'existe.

SCORE_EXACT (Cote cible: 1.01-100.0):
- Analyse précise du score le plus probable via Poisson et contexte.
- La confiance est basée sur la probabilité du score exact et la cohérence générale du match.

COMBINÉ (Cote cible: 2.00-4.00):
- N'est PAS une catégorie à analyser directement par Claude. Il sera construit avec les meilleurs matchs validés GRATUIT et VIP.
- Ne pas exiger une value positive sur les 3 sélections du combiné (cette règle sera gérée par le code Python).

──────────────────────────── FORMAT DE RÉPONSE JSON ────────────────────────────
Réponse JSON compacte uniquement. Aucun commentaire.
{
  "global_quality_score": 0-100, // Score global de qualité du match
  "GRATUIT": {
    "decision": "VALIDE/REJETE",
    "raison_rejet": "Si rejeté, max 1 phrase",
    "marche_choisi": "Nom du marché",
    "pronostic": "Sélection précise",
    "cote_choisie": 0.00,
    "confiance": 1-4,
    "value_pct": 0.0
  },
  "VIP": {
    "decision": "VALIDE/REJETE",
    "raison_rejet": "Si rejeté, max 1 phrase",
    "marche_choisi": "Nom du marché",
    "pronostic": "Sélection précise",
    "cote_choisie": 0.00,
    "confiance": 1-4,
    "value_pct": 0.0
  },
  "MONTANTE": {
    "decision": "VALIDE/REJETE",
    "raison_rejet": "Si rejeté, max 1 phrase",
    "marche_choisi": "Nom du marché",
    "pronostic": "Sélection précise",
    "cote_choisie": 0.00,
    "confiance": 1-4,
    "value_pct": 0.0
  },
  "SCORE_EXACT": {
    "decision": "VALIDE/REJETE",
    "raison_rejet": "Si rejeté, max 1 phrase",
    "marche_choisi": "Nom du marché",
    "pronostic": "Sélection précise",
    "cote_choisie": 0.00,
    "confiance": 1-4,
    "value_pct": 0.0
  }
}"""

async def get_claude_decision(home_team: str, away_team: str, match_data: Dict, analysis_data: Dict) -> Dict:
    if not client:
        return _empty_decision("Claude non configuré")

    user_content = f"Match: {home_team} vs {away_team}. Données d'analyse complètes: {json.dumps(analysis_data)}"

    for attempt in range(3):
        try:
            response = await client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1000, 
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_content}]
            )
            
            raw_text = response.content[0].text.strip()
            result = parse_claude_json(raw_text)
            if result:
                logger.info(f"Claude analysis for {home_team} vs {away_team} received.")
                return result
            
            raise ValueError(f"Parsing failed for: {raw_text[:200]}...")

        except APIStatusError as e:
            # Gestion intelligente des erreurs API
            if e.status_code == 404:
                logger.error(f"Modèle Claude invalide ({CLAUDE_MODEL}). Arrêt immédiat des tentatives.")
                return _empty_decision(f"Erreur Modèle: {CLAUDE_MODEL} non trouvé")
            
            if e.status_code == 401:
                logger.error("Clé API Anthropic invalide.")
                return _empty_decision("Erreur API Key")

            logger.error(f"Attempt {attempt+1} failed for {home_team} vs {away_team}: {e}")
            if e.status_code == 429: # Rate limit
                await asyncio.sleep(5 * (attempt + 1))
            else:
                await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Unexpected error on attempt {attempt+1} for {home_team} vs {away_team}: {e}")
            await asyncio.sleep(1)

    return _empty_decision("Claude API Error après 3 tentatives")

def _empty_decision(reason: str) -> Dict:
    return {
        "global_quality_score": 0, 
        "GRATUIT": {"decision": "REJETE", "raison_rejet": reason}, 
        "VIP": {"decision": "REJETE", "raison_rejet": reason}, 
        "MONTANTE": {"decision": "REJETE", "raison_rejet": reason}, 
        "SCORE_EXACT": {"decision": "REJETE", "raison_rejet": reason}
    }

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
            if text.count('"') % 2 != 0:
                text += '"'
            
            open_braces = text.count('{')
            close_braces = text.count('}')
            if open_braces > close_braces:
                text += '}' * (open_braces - close_braces)
            
            open_brackets = text.count('[')
            close_brackets = text.count(']')
            if open_brackets > close_brackets:
                text += ']' * (open_brackets - close_brackets)
            
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group())
                except:
                    pass
        
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
            max_tokens=300, 
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
