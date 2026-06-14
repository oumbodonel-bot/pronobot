# EliteOddsClub - Fichier d'analyse manuelle quotidienne
# Remplacer le contenu du dictionnaire 'data' chaque jour avant la génération.
# Structure : "Equipe A vs Equipe B": { ... données ... }

data = {
  "Exemple Equipe A vs Exemple Equipe B": {
    "manual_data": {
      "home_team": {
        "team": "Exemple Equipe A",
        "form_note": "Solide à domicile",
        "injuries_suspensions": [],
        "probable_lineup": ["Joueur 1", "Joueur 2"]
      },
      "away_team": {
        "team": "Exemple Equipe B",
        "form_note": "Difficultés à l'extérieur",
        "injuries_suspensions": ["Buteur vedette"],
        "probable_lineup": ["Joueur A", "Joueur B"]
      }
    },
    "analyst_note": "Note d'expert sur le match : avantage domicile suite aux absences clés côté visiteur.",
    "match_context": {
      "importance": "Crucial pour le maintien",
      "atmosphere": "Chaude"
    }
  }
}
