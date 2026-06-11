"""
Textes multilingues FR / EN
"""

TEXTS = {
    # ── ONBOARDING ──
    "welcome": {
        "fr": (
            "⚽ *Bienvenue sur PronoBot!*\n\n"
            "Le bot de pronostics sportifs le plus fiable, "
            "propulsé par l'Intelligence Artificielle et les "
            "modèles mathématiques des grands bookmakers.\n\n"
            "Choisis ta langue / Choose your language :"
        ),
        "en": (
            "⚽ *Welcome to PronoBot!*\n\n"
            "The most reliable sports prediction bot, "
            "powered by Artificial Intelligence and the "
            "mathematical models used by top bookmakers.\n\n"
            "Choisis ta langue / Choose your language :"
        ),
    },

    # ── MENU PRINCIPAL ──
    "main_menu": {
        "fr": (
            "🏠 *Menu Principal*\n\n"
            "Que souhaites-tu consulter aujourd'hui ?"
        ),
        "en": (
            "🏠 *Main Menu*\n\n"
            "What would you like to check today?"
        ),
    },

    # ── BOUTONS MENU ──
    "btn_free_prono": {"fr": "⚽ Prono Gratuit du Jour", "en": "⚽ Free Pick of the Day"},
    "btn_vip_pronos": {"fr": "💎 Pronos VIP (3-5 matchs)", "en": "💎 VIP Picks (3-5 matches)"},
    "btn_combined":   {"fr": "🎯 Combiné du Jour", "en": "🎯 Daily Combo"},
    "btn_exact_score":{"fr": "🎰 Score Exact", "en": "🎰 Exact Score"},
    "btn_montante":   {"fr": "📈 Montante du Jour", "en": "📈 Daily Montante"},
    "btn_subscribe":  {"fr": "💳 S'abonner / Gérer mon plan", "en": "💳 Subscribe / Manage Plan"},
    "btn_stats":      {"fr": "📊 Nos Performances", "en": "📊 Our Track Record"},
    "btn_back":       {"fr": "⬅️ Retour", "en": "⬅️ Back"},

    # ── PLANS ──
    "plans_title": {
        "fr": "💳 *Nos Abonnements*\n\nChoisis ton plan :",
        "en": "💳 *Our Plans*\n\nChoose your plan:",
    },
    "plan_free": {
        "fr": "🆓 *GRATUIT*\n• 1 prono par jour\n• Stats de base",
        "en": "🆓 *FREE*\n• 1 pick per day\n• Basic stats",
    },
    "plan_basic": {
        "fr": "💛 *BASIC — 5.000 FCFA/mois*\n• 3 pronos/jour\n• Combiné du jour\n•",
        "en": "💛 *BASIC — 5.000 FCFA/month*\n• 3 picks/day\n• Daily combo\n•",
    },
    "plan_vip": {
        "fr": (
            "💎 *VIP — 10.000 FCFA/mois*\n"
            "• 5 pronos/jour\n"
            "• Combiné du jour\n"
            "• Score exact\n"
            "• Montante\n"
            "• Analyse complète\n"
            "• Gestion bankroll"
        ),
        "en": (
            "💎 *VIP — 10.000 FCFA/month*\n"
            "• 5 picks/day\n"
            "• Daily combo\n"
            "• Exact score\n"
            "• Montante\n"
            "• Full analysis\n"
            "• Bankroll management"
        ),
    },

    # ── ACCÈS RESTREINT ──
    "vip_required": {
        "fr": (
            "🔒 *Contenu VIP*\n\n"
            "Cette section est réservée aux membres VIP.\n\n"
            "👇 Voici un aperçu de ce que tu manques :"
        ),
        "en": (
            "🔒 *VIP Content*\n\n"
            "This section is for VIP members only.\n\n"
            "👇 Here's a preview of what you're missing:"
        ),
    },
    "upgrade_btn": {
        "fr": "🚀 Passer en VIP maintenant",
        "en": "🚀 Upgrade to VIP now",
    },

    # ── PRONO TEMPLATE ──
    "prono_header": {
        "fr": "⚽ *{home} vs {away}*\n🏆 {league}\n📅 {date}\n",
        "en": "⚽ *{home} vs {away}*\n🏆 {league}\n📅 {date}\n",
    },
    "prono_stats": {
        "fr": (
            "📊 *ANALYSE MATHÉMATIQUE*\n"
            "• Victoire {home} : {prob_home}%\n"
            "• Match nul       : {prob_draw}%\n"
            "• Victoire {away} : {prob_away}%\n"
            "• Over 2.5 buts   : {prob_over}%\n"
            "• Les deux marquent : {prob_btts}%\n"
        ),
        "en": (
            "📊 *MATHEMATICAL ANALYSIS*\n"
            "• {home} win : {prob_home}%\n"
            "• Draw       : {prob_draw}%\n"
            "• {away} win : {prob_away}%\n"
            "• Over 2.5   : {prob_over}%\n"
            "• BTTS       : {prob_btts}%\n"
        ),
    },
    "prono_prediction": {
        "fr": (
            "🎯 *PRONOSTIC* : {prediction}\n"
            "📈 *Value Bet* : {value}% {value_icon}\n"
            "💰 *Mise conseillée* : {kelly}% de ta bankroll\n"
            "⭐ *Confiance* : {stars}\n"
        ),
        "en": (
            "🎯 *PREDICTION* : {prediction}\n"
            "📈 *Value Bet* : {value}% {value_icon}\n"
            "💰 *Recommended stake* : {kelly}% of your bankroll\n"
            "⭐ *Confidence* : {stars}\n"
        ),
    },
    "prono_footer": {
        "fr": (
            "\n⚠️ _Les paris comportent des risques. "
            "Ne misez que ce que vous pouvez vous permettre de perdre._\n"
            "🔒 _Analyse générée pour @{username} — ID:{user_id}_"
        ),
        "en": (
            "\n⚠️ _Betting involves risks. "
            "Only bet what you can afford to lose._\n"
            "🔒 _Analysis generated for @{username} — ID:{user_id}_"
        ),
    },

    # ── TEASER VIP (score exact flou) ──
    "teaser_exact_score": {
        "fr": (
            "🎰 *SCORE EXACT DU JOUR*\n\n"
            "Notre algorithme Dixon-Coles a identifié\n"
            "le score le plus probable...\n\n"
            "┌─────────────────────────┐\n"
            "│  {home} vs {away}      │\n"
            "│  Score : *?️⃣ - ?️⃣*          │\n"
            "│  Probabilité : **%      │\n"
            "│  Cote estimée : ~X.XX   │\n"
            "└─────────────────────────┘\n\n"
            "🔒 _Débloque le score exact en passant VIP_"
        ),
        "en": (
            "🎰 *EXACT SCORE OF THE DAY*\n\n"
            "Our Dixon-Coles algorithm identified\n"
            "the most likely score...\n\n"
            "┌─────────────────────────┐\n"
            "│  {home} vs {away}      │\n"
            "│  Score: *?️⃣ - ?️⃣*           │\n"
            "│  Probability: **%       │\n"
            "│  Estimated odds: ~X.XX  │\n"
            "└─────────────────────────┘\n\n"
            "🔒 _Unlock the exact score by going VIP_"
        ),
    },

    # ── PERFORMANCE ──
    "performance": {
        "fr": (
            "📊 *NOS PERFORMANCES*\n\n"
            "📅 Derniers 30 jours :\n"
            "✅ Pronos gagnants : {wins}/{total}\n"
            "📈 Taux de réussite : *{win_rate}%*\n"
            "💹 ROI moyen : *{roi}%*\n\n"
            "_La transparence est notre engagement._"
        ),
        "en": (
            "📊 *OUR TRACK RECORD*\n\n"
            "📅 Last 30 days:\n"
            "✅ Winning picks: {wins}/{total}\n"
            "📈 Win rate: *{win_rate}%*\n"
            "💹 Average ROI: *{roi}%*\n\n"
            "_Transparency is our commitment._"
        ),
    },

    # ── PAIEMENT ──
    "payment_instructions": {
        "fr": (
            "💳 *Paiement — Plan {plan}*\n\n"
            "Montant : *{amount} FCFA*\n\n"
            "📱 *Wave / Orange Money / MTN* :\n"
            "Envoie le montant au : `{payment_number}`\n"
            "Référence : `{ref}`\n\n"
            "Après paiement, clique sur ✅ Confirmer"
        ),
        "en": (
            "💳 *Payment — {plan} Plan*\n\n"
            "Amount: *{amount} FCFA*\n\n"
            "📱 *Wave / Orange Money / MTN*:\n"
            "Send the amount to: `{payment_number}`\n"
            "Reference: `{ref}`\n\n"
            "After payment, click ✅ Confirm"
        ),
    },

    # ── ERREURS ──
    "limit_reached": {
        "fr": "⏰ Tu as atteint ta limite gratuite du jour. Reviens demain ou passe VIP !",
        "en": "⏰ You've reached your daily free limit. Come back tomorrow or go VIP!",
    },
    "no_prono_today": {
        "fr": "📭 Aucun pronostic disponible pour aujourd'hui. Reviens plus tard !",
        "en": "📭 No predictions available for today. Check back later!",
    },
    "loading": {
        "fr": "⏳ Analyse en cours... (peut prendre 10-15 secondes)",
        "en": "⏳ Analyzing... (may take 10-15 seconds)",
    },
}


def t(key: str, lang: str = "fr", **kwargs) -> str:
    """Retourne le texte traduit avec variables interpolées"""
    text_obj = TEXTS.get(key, {})
    text = text_obj.get(lang, text_obj.get("fr", f"[{key}]"))
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text


def stars_emoji(n: int) -> str:
    return "⭐" * n + "☆" * (5 - n)
