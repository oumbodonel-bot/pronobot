import re
import unicodedata
from typing import Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)

# Dictionnaire de traduction pour les noms d'équipes courants (API -> Manuel)
TEAM_TRANSLATIONS = {
    "netherlands": "pays-bas",
    "switzerland": "suisse",
    "morocco": "maroc",
    "japan": "japon",
    "brazil": "bresil",
    "ivory coast": "cote d'ivoire",
    # Ajoutez d'autres traductions au besoin
}

def normalize_name(name: str) -> str:
    """Normalise un nom : minuscules, sans accents, sans suffixes FC/SC/etc."""
    if not name:
        return ""
    # Passage en minuscules et suppression des accents
    name = "".join(
        c for c in unicodedata.normalize('NFD', name.lower())
        if unicodedata.category(c) != 'Mn'
    )
    # Suppression des suffixes et caractères spéciaux
    name = re.sub(r'\b(fc|sc|cf|as|united|afc|city|town|stade|olympique)\b', '', name)
    name = re.sub(r'[^a-z0-9 ]', ' ', name)
    return " ".join(name.split())

def get_manual_data_for_match(api_home: str, api_away: str, manual_data_dict: Dict) -> Optional[Dict]:
    """
    Tente de trouver une correspondance entre un match de l'API et les données manuelles.
    manual_data_dict est le dictionnaire 'data' importé de analyse.py
    """
    norm_api_home = normalize_name(api_home)
    norm_api_away = normalize_name(api_away)
    
    # Appliquer les traductions si nécessaire
    norm_api_home = TEAM_TRANSLATIONS.get(norm_api_home, norm_api_home)
    norm_api_away = TEAM_TRANSLATIONS.get(norm_api_away, norm_api_away)

    for manual_key, manual_content in manual_data_dict.items():
        # La clé manuelle est souvent au format "Equipe A vs Equipe B"
        if " vs " not in manual_key:
            continue
            
        man_home, man_away = manual_key.split(" vs ", 1)
        norm_man_home = normalize_name(man_home)
        norm_man_away = normalize_name(man_away)

        # Vérification de correspondance (directe ou inversée pour plus de robustesse)
        match_direct = (norm_api_home == norm_man_home and norm_api_away == norm_man_away)
        match_reverse = (norm_api_home == norm_man_away and norm_api_away == norm_man_home)

        if match_direct or match_reverse:
            logger.info(f"✨ Correspondance trouvée pour {api_home} vs {api_away} dans analyse.py")
            return manual_content

    return None

def fuse_data(api_analysis: Dict, manual_content: Optional[Dict]) -> Dict:
    """Fusionne les données de l'API avec les données manuelles enrichies."""
    if not manual_content:
        return api_analysis

    # On enrichit l'analyse API avec les données manuelles
    # Les données manuelles sont prioritaires ou complémentaires
    fused = api_analysis.copy()
    fused["manual_enrichment"] = manual_content
    
    # On peut aussi injecter des notes spécifiques directement pour Claude
    if "analyst_note" in manual_content:
        fused["expert_note"] = manual_content["analyst_note"]
    
    if "match_context" in manual_content:
        fused["context"] = manual_content["match_context"]
        
    return fused
