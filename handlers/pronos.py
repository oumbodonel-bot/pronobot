"""
Handlers Pronostics - avec révélation 1h avant + watermark + anti-double
Basic = prono gratuit + VIP pronos + combiné
VIP   = tout (+ score exact + montante)
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from core.database import (
    get_user, is_vip, is_basic,
    get_today_pronos, get_prono_by_type,
    count_free_consultations_today, log_consultation,
    is_revealed, time_until_reveal, check_double_consultation
)
from utils.texts import t, stars_emoji

logger = logging.getLogger(__name__)


def _get_lang(user_id: int) -> str:
    user = get_user(user_id)
    return user['language'] if user else 'fr'


def _back_keyboard(lang: str):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t("btn_back", lang), callback_data="menu")
    ]])


def _upgrade_keyboard(lang: str, target: str = "vip"):
    """Clavier upgrade — target = 'vip' ou 'basic'"""
    if target == "vip":
        btn_text = "🚀 Passer VIP" if lang == 'fr' else "🚀 Upgrade to VIP"
    else:
        btn_text = "💛 Passer Basic ou VIP" if lang == 'fr' else "💛 Go Basic or VIP"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(btn_text, callback_data="subscribe_plans")],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="menu")],
    ])


def _timer_message(prono, lang: str) -> str:
    time_left = time_until_reveal(prono)
    if lang == 'fr':
        return (
            f"⏳ *PRONO EN COURS DE PRÉPARATION*\n\n"
            f"⚽ *{prono['home_team']} vs {prono['away_team']}*\n"
            f"🏆 {prono['league']}\n\n"
            f"🔒 Ce pronostic sera révélé dans :\n\n"
            f"┌─────────────────────┐\n"
            f"│  ⏱️  *{time_left}*  │\n"
            f"└─────────────────────┘\n\n"
            f"_Le prono est révélé 1h avant le coup d'envoi._\n"
            f"_Reviens à ce moment-là!_ 🎯"
        )
    else:
        return (
            f"⏳ *PICK BEING PREPARED*\n\n"
            f"⚽ *{prono['home_team']} vs {prono['away_team']}*\n"
            f"🏆 {prono['league']}\n\n"
            f"🔒 This prediction will be revealed in:\n\n"
            f"┌─────────────────────┐\n"
            f"│  ⏱️  *{time_left}*  │\n"
            f"└─────────────────────┘\n\n"
            f"_The pick is revealed 1h before kick-off._\n"
            f"_Come back then!_ 🎯"
        )


def _double_consult_warning(prono, lang: str, user_id: int, username: str) -> str:
    now = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")
    if lang == 'fr':
        return (
            f"⚠️ *CONSULTATION ENREGISTRÉE*\n\n"
            f"Tu as déjà consulté ce pronostic.\n"
            f"Cette consultation est loggée :\n\n"
            f"👤 @{username} (ID: `{user_id}`)\n"
            f"📅 {now}\n"
            f"🔑 Prono #{prono['id']}\n\n"
            f"_Toute revente de nos pronostics est détectable._"
        )
    else:
        return (
            f"⚠️ *CONSULTATION LOGGED*\n\n"
            f"You already viewed this prediction.\n"
            f"This consultation is recorded:\n\n"
            f"👤 @{username} (ID: `{user_id}`)\n"
            f"📅 {now}\n"
            f"🔑 Pick #{prono['id']}\n\n"
            f"_Any reselling of our picks is detectable._"
        )


# ════════════════════════════════════════════════════
# PRONO GRATUIT
# ════════════════════════════════════════════════════

async def free_prono_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id  = query.from_user.id
    lang     = _get_lang(user_id)
    username = query.from_user.username or "user"

    if not is_vip(user_id) and not is_basic(user_id):
        count = count_free_consultations_today(user_id)
        if count >= 1:
            await query.edit_message_text(
                t("limit_reached", lang),
                reply_markup=_upgrade_keyboard(lang, "basic")
            )
            return

    await query.edit_message_text(t("loading", lang))

    prono = get_prono_by_type("free")
    if not prono:
        await query.edit_message_text(
            t("no_prono_today", lang),
            reply_markup=_back_keyboard(lang)
        )
        return

    if not is_revealed(prono):
        await query.edit_message_text(
            _timer_message(prono, lang),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_back_keyboard(lang)
        )
        return

    already_seen = check_double_consultation(user_id, prono['id'])
    log_consultation(user_id, prono['id'])
    header = "⚽ *PRONO GRATUIT DU JOUR*\n\n" if lang == 'fr' else "⚽ *FREE PICK OF THE DAY*\n\n"
    text = header + _format_prono(prono, lang, user_id, username)

    if already_seen:
        text = _double_consult_warning(prono, lang, user_id, username) + "\n\n" + text

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_back_keyboard(lang)
    )


# ════════════════════════════════════════════════════
# PRONOS VIP (3-5 matchs) — accessible Basic ET VIP
# ════════════════════════════════════════════════════

async def vip_pronos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id  = query.from_user.id
    lang     = _get_lang(user_id)
    username = query.from_user.username or "user"

    if not is_vip(user_id) and not is_basic(user_id):
        await _show_vip_teaser(query, lang)
        return

    # Basic = 3 pronos max, VIP = 5
    max_pronos = 5 if is_vip(user_id) else 3

    await query.edit_message_text(t("loading", lang))

    pronos = get_today_pronos(plan='vip')
    # Filtrage des doublons par match pour l'affichage VIP
    unique_pronos = []
    seen_matches = set()
    for p in pronos:
        m_id = f"{p['home_team']}_{p['away_team']}"
        if m_id not in seen_matches and p['prono_type'] == 'vip':
            unique_pronos.append(p)
            seen_matches.add(m_id)
            
    if not unique_pronos:
        await query.edit_message_text(
            t("no_prono_today", lang),
            reply_markup=_back_keyboard(lang)
        )
        return

    messages = []
    for i, prono in enumerate(unique_pronos[:max_pronos], 1):
        label = f"💎 *PRONO VIP {i}/{min(len(pronos), max_pronos)}*" if lang == 'fr' else f"💎 *VIP PICK {i}/{min(len(pronos), max_pronos)}*"
        if not is_revealed(prono):
            timer = _timer_message(prono, lang)
            messages.append(f"{label}\n\n" + timer)
            continue

        already_seen = check_double_consultation(user_id, prono['id'])
        log_consultation(user_id, prono['id'])
        text = f"{label}\n\n" + _format_prono(prono, lang, user_id, username)

        if already_seen:
            text = _double_consult_warning(prono, lang, user_id, username) + "\n\n" + text
        messages.append(text)

    full_text = "\n\n━━━━━━━━━━━━━━━━━━━━━━\n\n".join(messages)
    if len(full_text) > 4000:
        full_text = full_text[:4000] + "..."

    await query.edit_message_text(
        full_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_back_keyboard(lang)
    )


# ════════════════════════════════════════════════════
# COMBINÉ DU JOUR — accessible Basic ET VIP
# ════════════════════════════════════════════════════

async def combined_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id  = query.from_user.id
    lang     = _get_lang(user_id)
    username = query.from_user.username or "user"

    if not is_vip(user_id) and not is_basic(user_id):
        await _show_combined_teaser(query, lang)
        return

    await query.edit_message_text(t("loading", lang))

    # On récupère les pronos spécifiquement marqués comme 'combined'
    pronos = get_today_pronos(plan='vip')
    selected = [p for p in pronos if p['prono_type'] == 'combined']
    
    if len(selected) < 2:
        # Fallback si pas de 'combined' spécifique : on prend les top VIP
        selected = sorted([p for p in pronos if p['prono_type'] == 'vip'], 
                          key=lambda x: x['confidence'], reverse=True)[:3]

    if len(selected) < 2:
        await query.edit_message_text(t("no_prono_today", lang), reply_markup=_back_keyboard(lang))
        return
    
    # Le combiné est révélé dès que le PREMIER match est prêt (1h avant)
    header = "🎯 *COMBINÉ DU JOUR*\n\n" if lang == 'fr' else "🎯 *DAILY COMBO*\n\n"
    
    # On trie par date/heure pour trouver le premier match chronologique
    sorted_by_time = sorted(selected, key=lambda x: (x['match_date'], x['match_time'] or "23:59:59"))
    first_match = sorted_by_time[0]
    
    # Si le premier match n'est pas révélé, on montre les timers pour tout le ticket
    if not is_revealed(first_match):
        messages = []
        for i, p in enumerate(selected, 1):
            messages.append(f"🔢 *MATCH {i}/3*\n" + _timer_message(p, lang))
        
        full_text = header + "\n\n━━━━━━━━━━━━━━━━━━━━━━\n\n".join(messages)
        await query.edit_message_text(full_text, parse_mode=ParseMode.MARKDOWN, reply_markup=_back_keyboard(lang))
        return
    
    # Si le premier match est révélé, on révèle TOUT le ticket
    # (La suite du code existant gère déjà l'affichage complet)

    total_odds = 1.0
    for p in selected:
        total_odds *= (p['odds'] or 1.5)

    now = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    if lang == 'fr':
        text = header
        for p in selected:
            log_consultation(user_id, p['id'])
            text += f"✅ *{p['home_team']} vs {p['away_team']}*\n"
            text += f"   └ {p['prediction']} @ {p['odds'] or '?'}\n\n"
        text += f"💰 *Cote totale : {round(total_odds, 2)}*\n"
        text += f"⭐ *Confiance : {stars_emoji(min(4, max(2, int(sum(p['confidence'] for p in selected) / len(selected)))))}*\n\n"
        text += f"🔒 _Combiné pour @{username} — ID:{user_id} — {now}_\n"
        text += f"⚠️ _Les paris comportent des risques._"
    else:
        text = header
        for p in selected:
            log_consultation(user_id, p['id'])
            text += f"✅ *{p['home_team']} vs {p['away_team']}*\n"
            text += f"   └ {p['prediction']} @ {p['odds'] or '?'}\n\n"
        text += f"💰 *Total odds: {round(total_odds, 2)}*\n"
        text += f"⭐ *Confidence: {stars_emoji(min(4, max(2, int(sum(p['confidence'] for p in selected) / len(selected)))))}*\n\n"
        text += f"🔒 _Combo for @{username} — ID:{user_id} — {now}_\n"
        text += f"⚠️ _Betting involves risks._"

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_back_keyboard(lang)
    )


# ════════════════════════════════════════════════════
# SCORE EXACT — VIP uniquement
# ════════════════════════════════════════════════════

async def exact_score_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id  = query.from_user.id
    lang     = _get_lang(user_id)
    username = query.from_user.username or "user"

    prono = get_prono_by_type("exact_score")

    # Basic ET free → bloqué, VIP uniquement
    if not is_vip(user_id):
        if prono:
            teaser = t("teaser_exact_score", lang, home=prono['home_team'], away=prono['away_team'])
        else:
            teaser = t("teaser_exact_score", lang, home="Équipe A", away="Équipe B")
        await query.edit_message_text(
            teaser,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_upgrade_keyboard(lang, "vip")
        )
        return

    if not prono:
        await query.edit_message_text(t("no_prono_today", lang), reply_markup=_back_keyboard(lang))
        return

    header = "🎰 *SCORE EXACT DU JOUR*\n\n" if lang == 'fr' else "🎰 *EXACT SCORE OF THE DAY*\n\n"
    if not is_revealed(prono):
        await query.edit_message_text(
            header + _timer_message(prono, lang),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_back_keyboard(lang)
        )
        return

    already_seen = check_double_consultation(user_id, prono['id'])
    log_consultation(user_id, prono['id'])

    now = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    # On utilise le formateur standard pour garder la même structure professionnelle
    text = _format_prono(prono, lang, user_id, username, label=header.strip())

    if already_seen:
        text = _double_consult_warning(prono, lang, user_id, username) + "\n\n" + text

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_back_keyboard(lang))


# ════════════════════════════════════════════════════
# MONTANTE — VIP uniquement
# ════════════════════════════════════════════════════

async def montante_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id  = query.from_user.id
    lang     = _get_lang(user_id)
    username = query.from_user.username or "user"

    # Basic ET free → bloqué, VIP uniquement
    if not is_vip(user_id):
        if lang == 'fr':
            teaser = (
                "📈 *MONTANTE DU JOUR*\n\n"
                "Notre algorithme a sélectionné une montante\n"
                "avec une cote sécurisée entre 1.20 et 1.50\n\n"
                "┌─────────────────────────┐\n"
                "│  Match : 🔒 VIP only    │\n"
                "│  Cote  : 🔒 VIP only    │\n"
                "│  Mise  : 🔒 VIP only    │\n"
                "└─────────────────────────┘\n\n"
                "🔒 _Réservé aux membres VIP_"
            )
        else:
            teaser = (
                "📈 *DAILY MONTANTE*\n\n"
                "Our algorithm selected a secure montante\n"
                "with odds between 1.20 and 1.50\n\n"
                "┌─────────────────────────┐\n"
                "│  Match: 🔒 VIP only     │\n"
                "│  Odds:  🔒 VIP only     │\n"
                "│  Stake: 🔒 VIP only     │\n"
                "└─────────────────────────┘\n\n"
                "🔒 _Reserved for VIP members_"
            )
        await query.edit_message_text(
            teaser,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_upgrade_keyboard(lang, "vip")
        )
        return

    prono = get_prono_by_type("montante")
    if not prono:
        await query.edit_message_text(t("no_prono_today", lang), reply_markup=_back_keyboard(lang))
        return

    header = "📈 *MONTANTE DU JOUR*\n\n" if lang == 'fr' else "📈 *DAILY MONTANTE*\n\n"
    if not is_revealed(prono):
        await query.edit_message_text(
            header + _timer_message(prono, lang),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_back_keyboard(lang)
        )
        return

    already_seen = check_double_consultation(user_id, prono['id'])
    log_consultation(user_id, prono['id'])
    text = header + _format_prono(prono, lang, user_id, username)

    if already_seen:
        text = _double_consult_warning(prono, lang, user_id, username) + "\n\n" + text

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_back_keyboard(lang))


# ════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════

def _format_prono(prono, lang: str, user_id: int, username: str, label: str = None) -> str:
    """Formate un prono individuel avec structure professionnelle stricte."""
    now = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")
    
    # Extraction de l'heure du match
    match_time = prono.get('match_time', 'N/A')
    
    # Valeur du Value Bet
    value_bet = prono.get('value_bet', 0)
    value_text = f"{value_bet}%" if value_bet is not None and value_bet != 0 else "N/A"

    # Extraction de l'analyse synthétique
    analysis = prono.get(f'analysis_{lang}') or prono.get('analysis_fr') or ""
    import json
    if isinstance(analysis, str):
        try:
            analysis_obj = json.loads(analysis)
            analysis_text = analysis_obj.get('analysis', analysis)
        except:
            analysis_text = analysis
    else:
        analysis_text = ""

    # Pour le Score Exact, on peut vouloir ajouter la probabilité spécifique
    score_prob_text = ""
    if prono.get('prono_type') == 'exact_score' and prono.get('exact_score'):
        try:
            scores = json.loads(prono['exact_score']) if isinstance(prono['exact_score'], str) else prono['exact_score']
            if isinstance(scores, list) and len(scores) > 0:
                best = scores[0]
                score_prob_text = f"📊 *PROBABILITÉ* : {best['prob']}%\n" if lang == 'fr' else f"📊 *PROBABILITY* : {best['prob']}%\n"
        except:
            pass

    header = f"{label}\n\n" if label else ""

    if lang == 'fr':
        text = (
            header +
            f"🏆 *COMPÉTITION* : {prono['league']}\n"
            f"⏰ *HEURE DU MATCH* : {match_time}\n"
            f"⚽ *AFFICHE* : {prono['home_team']} vs {prono['away_team']}\n"
            f"🎯 *PRONOSTIC* : {prono['prediction']}\n"
            f"💰 *COTE* : {prono['odds']}\n"
            f"⭐ *CONFIANCE* : {prono['confidence']}/5\n"
            f"{score_prob_text}"
            f"📈 *VALUE BET* : {value_text}\n\n"
            f"📝 *ANALYSE* :\n_{analysis_text}_\n\n"
            f"🔒 _Généré pour @{username} — ID:{user_id} — {now}_\n"
            f"⚠️ _Les paris comportent des risques._"
        )
    else:
        text = (
            header +
            f"🏆 *COMPETITION* : {prono['league']}\n"
            f"⏰ *MATCH TIME* : {match_time}\n"
            f"⚽ *MATCH* : {prono['home_team']} vs {prono['away_team']}\n"
            f"🎯 *PREDICTION* : {prono['prediction']}\n"
            f"💰 *ODDS* : {prono['odds']}\n"
            f"⭐ *CONFIDENCE* : {prono['confidence']}/5\n"
            f"{score_prob_text}"
            f"📈 *VALUE BET* : {value_text}\n\n"
            f"📝 *ANALYSIS*:\n_{analysis_text}_\n\n"
            f"🔒 _Generated for @{username} — ID:{user_id} — {now}_\n"
            f"⚠️ _Betting involves risks._"
        )
    return text


async def _show_vip_teaser(query, lang: str):
    if lang == 'fr':
        text = (
            "💎 *PRONOS VIP DU JOUR*\n\n"
            "Notre IA a analysé aujourd'hui :\n\n"
            "🔒 Match 1 : Confiance ★★★★★ — VIP/Basic\n"
            "🔒 Match 2 : Confiance ★★★★☆ — VIP/Basic\n"
            "🔒 Match 3 : Confiance ★★★★☆ — VIP/Basic\n"
            "🔒 Match 4 : Confiance ★★★☆☆ — VIP only\n"
            "🔒 Match 5 : Confiance ★★★★☆ — VIP only\n\n"
            "💛 Basic = 3 pronos | 💎 VIP = 5 pronos\n\n"
            "🚀 Abonne-toi pour accéder aux analyses!"
        )
    else:
        text = (
            "💎 *VIP PICKS OF THE DAY*\n\n"
            "Our AI analyzed today:\n\n"
            "🔒 Match 1: Confidence ★★★★★ — VIP/Basic\n"
            "🔒 Match 2: Confidence ★★★★☆ — VIP/Basic\n"
            "🔒 Match 3: Confidence ★★★★☆ — VIP/Basic\n"
            "🔒 Match 4: Confidence ★★★☆☆ — VIP only\n"
            "🔒 Match 5: Confidence ★★★★☆ — VIP only\n\n"
            "💛 Basic = 3 picks | 💎 VIP = 5 picks\n\n"
            "🚀 Subscribe to access all analyses!"
        )
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_upgrade_keyboard(lang, "basic"))


async def _show_combined_teaser(query, lang: str):
    if lang == 'fr':
        text = (
            "🎯 *COMBINÉ DU JOUR*\n\n"
            "3 matchs sélectionnés par notre IA\n\n"
            "🔒 Match A : ??? @ ?.??\n"
            "🔒 Match B : ??? @ ?.??\n"
            "🔒 Match C : ??? @ ?.??\n\n"
            "💛 Accessible dès le plan Basic\n"
            "🔒 _Débloque avec Basic ou VIP_"
        )
    else:
        text = (
            "🎯 *DAILY COMBO*\n\n"
            "3 matches selected by our AI\n\n"
            "🔒 Match A: ??? @ ?.??\n"
            "🔒 Match B: ??? @ ?.??\n"
            "🔒 Match C: ??? @ ?.??\n\n"
            "💛 Available from Basic plan\n"
            "🔒 _Unlock with Basic or VIP_"
        )
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_upgrade_keyboard(lang, "basic"))
