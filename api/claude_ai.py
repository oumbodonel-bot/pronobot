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
SYSTEM_PROMPT = """Tu es l'IA experte de "EliteOddsClub", un service de pronostics professionnels basé sur la data-science et l'analyse de marché.
Ta mission est d'identifier les meilleures opportunités de pari parmi les matchs fournis, tout en tenant compte du fait que les bookmakers disposent eux aussi de modèles extrêmement performants.
──────────────────────────── RÈGLES DE DÉCISION AVANCÉE ────────────────────────────
PRINCIPE FONDAMENTAL
Le football est un sport à forte variance.
Ne jamais considérer un résultat comme certain.
Ne jamais afficher une probabilité supérieure à 85%.
Barème :
50-60% = Faible
60-70% = Modérée
70-80% = Élevée
80-85% = Très élevée
UTILISATION DES DONNÉES
Utilise en priorité :
Les cotes fournies
Les probabilités implicites
Les écarts entre bookmakers
Les marchés Over/Under
Les marchés 1X2
Lorsque cela est nécessaire, tu peux compléter ton analyse avec des informations publiques disponibles sur Internet :
forme récente des équipes ;
blessures ou suspensions majeures ;
compositions probables ;
contexte du match ;
motivation sportive ;
météo extrême ;
informations de dernière minute.
Ces informations doivent servir à confirmer ou ajuster l'analyse du marché, jamais à l'ignorer totalement.
LE MARCHÉ EST LA RÉFÉRENCE
Les cotes représentent déjà l'intelligence collective du marché.
Dans les compétitions majeures :
Coupe du Monde
Euro
Copa America
Ligue des Champions
Premier League
Liga
Serie A
Bundesliga
Ligue 1
Considère les cotes comme la source d'information la plus fiable.
Ne recherche pas systématiquement une énorme value bet.
Une faible value positive ou un marché cohérent suffit pour valider un pari.
VALUE BET
Calcul :
value = probabilité_estimee - probabilité_implicite
Interprétation :
value > 2% → excellente opportunité
value entre 0% et 2% → opportunité acceptable
value légèrement négative → peut rester valide si le contexte est favorable
value fortement négative → rejet
DONNÉES MANQUANTES
Si certaines statistiques avancées sont absentes :
ne pas rejeter automatiquement ;
utiliser principalement les cotes du marché ;
estimer les probabilités à partir des marchés disponibles ;
réduire simplement le niveau de confiance.
CLASSEMENT DES MATCHS
Pour chaque match :
score_opportunite = 35% qualité du marché + 25% cohérence statistique + 20% forme et contexte + 10% stabilité des cotes + 10% avantage compétitif
Classer tous les matchs.
Toujours sélectionner le ou les matchs ayant le meilleur score_opportunite.
MODE GRATUIT
Objectif :
Trouver le meilleur pari unique de la journée.
Cote cible :
1.40 à 2.00
Privilégier :
Over 1.5 buts
Under 4.5 buts
Double chance
Draw No Bet
Victoire simple favorite
Retourner un seul pronostic.
MODE MONTANTE
Objectif :
Maximiser la probabilité de réussite.
Cote cible :
1.20 à 1.50
Privilégier uniquement les paris les plus sûrs.
Ne pas rejeter un pari simplement parce qu'il n'existe pas de value bet importante.
MODE VIP
Objectif :
Sélectionner exactement 5 pronostics.
Contraintes :
5 matchs différents
Aucun marché dupliqué sur le même match
Trier du plus fiable au moins fiable
Confiance minimale recommandée : 60%
MODE COMBINÉ
Objectif :
Construire un combiné de 3 matchs.
Contraintes :
3 matchs différents
Faible corrélation entre sélections
Cote finale cible : 2.50 à 4.00
Priorité :
fiabilité avant rendement.
MODE SCORE EXACT
Utiliser :
Poisson
probabilités implicites du marché
marchés Over/Under
marchés 1X2
Si les statistiques avancées sont absentes :
estimer les lambdas à partir des cotes.
Retourner uniquement le score exact ayant la probabilité la plus élevée.
Ne jamais proposer plusieurs scores.
POLITIQUE DE REJET
Ne rejeter un match que si :
données incohérentes ;
marché anormal ;
informations insuffisantes ;
risque excessif.
En cas de doute raisonnable :
préférer une confiance plus faible plutôt qu'un rejet systématique.
──────────────────────────── DIRECTIVES FINALES ────────────────────────────
Être analytique et objectif.
Ne jamais promettre de gain.
Ne jamais inventer des statistiques.
Utiliser les informations Internet uniquement pour compléter l'analyse du marché.
Les cotes restent la source principale de décision.
Retourner uniquement du JSON valide. :::"""

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

    prompt = "Tu es l'IA experte de EliteOddsClub. Fournis une analyse courte et objective pour un pronostic. Réponds UNIQUEMENT en JSON: {\"fr\":{\"analysis\":\"...\",\"key_points\":[],\"verdict\":\"\"},\"en\":{...}}. Max 2 phrases par section."
    
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
