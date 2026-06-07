"""
Handlers Pronostics - avec révélation 1h avant + watermark + anti-double
"""

import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from core.database import (
    get_user, is_vip,
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


def _upgrade_keyboard(lang: str):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("upgrade_btn", lang), callback_data="subscribe_vip")],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="menu")],
    ])


def _timer_message(prono, lang: str) -> str:
    """Message de compte à rebours avant révélation"""
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
    """Avertissement double consultation"""
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
    user_id = query.from_user.id
    lang = _get_lang(user_id)
    username = query.from_user.username or "user"

    if not is_vip(user_id):
        count = count_free_consultations_today(user_id)
        if count >= 1:
            await query.edit_message_text(
                t("limit_reached", lang),
                reply_markup=_upgrade_keyboard(lang)
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

    # ── Vérification révélation 1h avant ──
    if not is_revealed(prono):
        await query.edit_message_text(
            _timer_message(prono, lang),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_back_keyboard(lang)
        )
        return

    # ── Double consultation (watermark) ──
    already_seen = check_double_consultation(user_id, prono['id'])

    log_consultation(user_id, prono['id'])
    text = _format_prono(prono, lang, user_id, username)

    if already_seen:
        warning = _double_consult_warning(prono, lang, user_id, username)
        text = warning + "\n\n" + text

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_back_keyboard(lang)
    )


# ════════════════════════════════════════════════════
# PRONOS VIP (3-5 matchs)
# ════════════════════════════════════════════════════

async def vip_pronos_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = _get_lang(user_id)
    username = query.from_user.username or "user"

    if not is_vip(user_id):
        await _show_vip_teaser(query, lang)
        return

    await query.edit_message_text(t("loading", lang))

    pronos = get_today_pronos(plan='vip')
    if not pronos:
        await query.edit_message_text(
            t("no_prono_today", lang),
            reply_markup=_back_keyboard(lang)
        )
        return

    messages = []
    for i, prono in enumerate(pronos[:5], 1):
        # Vérification révélation
        if not is_revealed(prono):
            timer = _timer_message(prono, lang)
            messages.append(f"🔢 *PRONO {i}/{len(pronos[:5])}*\n\n" + timer)
            continue

        already_seen = check_double_consultation(user_id, prono['id'])
        log_consultation(user_id, prono['id'])
        text = f"🔢 *PRONO {i}/{len(pronos[:5])}*\n\n" + _format_prono(prono, lang, user_id, username)

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
# COMBINÉ DU JOUR
# ════════════════════════════════════════════════════

async def combined_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = _get_lang(user_id)
    username = query.from_user.username or "user"

    if not is_vip(user_id):
        await _show_combined_teaser(query, lang)
        return

    await query.edit_message_text(t("loading", lang))

    pronos = get_today_pronos(plan='vip')
    if len(pronos) < 2:
        await query.edit_message_text(t("no_prono_today", lang), reply_markup=_back_keyboard(lang))
        return

    selected = sorted(pronos, key=lambda x: x['confidence'], reverse=True)[:3]

    # Révélation = 1h avant le PREMIER match du combiné
    # (le match avec l'heure la plus tôt)
    first_unrevealed = next((p for p in selected if not is_revealed(p)), None)
    if first_unrevealed:
        await query.edit_message_text(
            _timer_message(first_unrevealed, lang),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_back_keyboard(lang)
        )
        return

    total_odds = 1.0
    for p in selected:
        total_odds *= (p['odds'] or 1.5)

    now = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    if lang == 'fr':
        text = f"🎯 *COMBINÉ DU JOUR*\n\n"
        for p in selected:
            log_consultation(user_id, p['id'])
            text += f"✅ *{p['home_team']} vs {p['away_team']}*\n"
            text += f"   └ {p['prediction']} @ {p['odds'] or '?'}\n\n"
        text += f"💰 *Cote totale : {round(total_odds, 2)}*\n"
        text += f"⭐ *Confiance : {stars_emoji(min(4, max(2, int(sum(p['confidence'] for p in selected) / len(selected)))))}*\n\n"
        text += f"🔒 _Combiné pour @{username} — ID:{user_id} — {now}_\n"
        text += f"⚠️ _Les paris comportent des risques._"
    else:
        text = f"🎯 *DAILY COMBO*\n\n"
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
# SCORE EXACT
# ════════════════════════════════════════════════════

async def exact_score_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = _get_lang(user_id)
    username = query.from_user.username or "user"

    prono = get_prono_by_type("exact_score")

    if not is_vip(user_id):
        if prono:
            teaser = t("teaser_exact_score", lang, home=prono['home_team'], away=prono['away_team'])
        else:
            teaser = t("teaser_exact_score", lang, home="Équipe A", away="Équipe B")
        await query.edit_message_text(teaser, parse_mode=ParseMode.MARKDOWN, reply_markup=_upgrade_keyboard(lang))
        return

    if not prono:
        await query.edit_message_text(t("no_prono_today", lang), reply_markup=_back_keyboard(lang))
        return

    # Vérification révélation
    if not is_revealed(prono):
        await query.edit_message_text(
            _timer_message(prono, lang),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=_back_keyboard(lang)
        )
        return

    already_seen = check_double_consultation(user_id, prono['id'])
    log_consultation(user_id, prono['id'])

    now = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    if lang == 'fr':
        text = (
            f"🎰 *SCORE EXACT DU JOUR*\n\n"
            f"⚽ *{prono['home_team']} vs {prono['away_team']}*\n"
            f"🏆 {prono['league']}\n\n"
        )
        if prono.get('exact_score'):
            import json
            try:
                scores = json.loads(prono['exact_score']) if isinstance(prono['exact_score'], str) else prono['exact_score']
                text += "📊 *Top scores (Dixon-Coles)* :\n"
                for s in scores[:5]:
                    text += f"  • {s['score']} → {s['prob']}%\n"
            except:
                text += f"  • {prono['exact_score']}\n"
        text += (
            f"\n🎯 *Score recommandé* : `{prono['prediction']}`\n"
            f"⭐ Confiance : {stars_emoji(prono['confidence'])}\n\n"
            f"🔒 _Généré pour @{username} — ID:{user_id} — {now}_\n"
            f"⚠️ _Les paris comportent des risques._"
        )
    else:
        text = (
            f"🎰 *EXACT SCORE OF THE DAY*\n\n"
            f"⚽ *{prono['home_team']} vs {prono['away_team']}*\n"
            f"🏆 {prono['league']}\n\n"
        )
        if prono.get('exact_score'):
            import json
            try:
                scores = json.loads(prono['exact_score']) if isinstance(prono['exact_score'], str) else prono['exact_score']
                text += "📊 *Top scores (Dixon-Coles)*:\n"
                for s in scores[:5]:
                    text += f"  • {s['score']} → {s['prob']}%\n"
            except:
                text += f"  • {prono['exact_score']}\n"
        text += (
            f"\n🎯 *Recommended score*: `{prono['prediction']}`\n"
            f"⭐ Confidence: {stars_emoji(prono['confidence'])}\n\n"
            f"🔒 _Generated for @{username} — ID:{user_id} — {now}_\n"
            f"⚠️ _Betting involves risks._"
        )

    if already_seen:
        text = _double_consult_warning(prono, lang, user_id, username) + "\n\n" + text

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_back_keyboard(lang))


# ════════════════════════════════════════════════════
# MONTANTE
# ════════════════════════════════════════════════════

async def montante_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = _get_lang(user_id)
    username = query.from_user.username or "user"

    if not is_vip(user_id):
        if lang == 'fr':
            teaser = (
                "📈 *MONTANTE DU JOUR*\n\n"
                "Notre algorithme a sélectionné une montante\n"
                "de 4 matchs avec une cote combinée de ~*?.??*\n\n"
                "┌─────────────────────────┐\n"
                "│  Match 1 : 🔒 VIP       │\n"
                "│  Match 2 : 🔒 VIP       │\n"
                "│  Match 3 : 🔒 VIP       │\n"
                "│  Match 4 : 🔒 VIP       │\n"
                "└─────────────────────────┘\n\n"
                "🔒 _Débloque la montante avec VIP_"
            )
        else:
            teaser = (
                "📈 *DAILY MONTANTE*\n\n"
                "Our algorithm selected a montante\n"
                "of 4 matches with combined odds ~*?.??*\n\n"
                "┌─────────────────────────┐\n"
                "│  Match 1: 🔒 VIP        │\n"
                "│  Match 2: 🔒 VIP        │\n"
                "│  Match 3: 🔒 VIP        │\n"
                "│  Match 4: 🔒 VIP        │\n"
                "└─────────────────────────┘\n\n"
                "🔒 _Unlock with VIP_"
            )
        await query.edit_message_text(teaser, parse_mode=ParseMode.MARKDOWN, reply_markup=_upgrade_keyboard(lang))
        return

    prono = get_prono_by_type("montante")
    if not prono:
        await query.edit_message_text(t("no_prono_today", lang), reply_markup=_back_keyboard(lang))
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
    text = _format_prono(prono, lang, user_id, username)

    if already_seen:
        text = _double_consult_warning(prono, lang, user_id, username) + "\n\n" + text

    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_back_keyboard(lang))


# ════════════════════════════════════════════════════
# HELPERS
# ════════════════════════════════════════════════════

def _format_prono(prono, lang: str, user_id: int, username: str) -> str:
    value_icon = "✅" if (prono.get('value_bet') or 0) > 0 else "⚠️"
    analysis = prono.get(f'analysis_{lang}') or prono.get('analysis_fr') or ""
    now = datetime.utcnow().strftime("%d/%m/%Y %H:%M UTC")

    if isinstance(analysis, dict):
        analysis_text = analysis.get('analysis', '')
        key_points = analysis.get('key_points', [])
        verdict = analysis.get('verdict', '')
    else:
        analysis_text = str(analysis)
        key_points = []
        verdict = ''

    if lang == 'fr':
        text = (
            f"⚽ *{prono['home_team']} vs {prono['away_team']}*\n"
            f"🏆 {prono['league']}\n"
            f"📅 {prono['match_date']}\n\n"
            f"🎯 *PRONOSTIC* : `{prono['prediction']}`\n"
            f"📈 Value Bet : {prono.get('value_bet') or '?'}% {value_icon}\n"
            f"💰 Mise conseillée : {prono.get('kelly_stake') or 3}% de ta bankroll\n"
            f"⭐ Confiance : {stars_emoji(prono['confidence'])}\n\n"
        )
        if analysis_text:
            text += f"📝 *ANALYSE*\n{analysis_text}\n\n"
        if key_points:
            text += "🔑 *Points clés* :\n" + "\n".join(f"  • {p}" for p in key_points) + "\n\n"
        if verdict:
            text += f"✅ *Verdict* : {verdict}\n\n"
        text += (
            f"🔒 _@{username} — ID:{user_id} — {now}_\n"
            f"⚠️ _Les paris comportent des risques._"
        )
    else:
        text = (
            f"⚽ *{prono['home_team']} vs {prono['away_team']}*\n"
            f"🏆 {prono['league']}\n"
            f"📅 {prono['match_date']}\n\n"
            f"🎯 *PREDICTION*: `{prono['prediction']}`\n"
            f"📈 Value Bet: {prono.get('value_bet') or '?'}% {value_icon}\n"
            f"💰 Recommended stake: {prono.get('kelly_stake') or 3}% of bankroll\n"
            f"⭐ Confidence: {stars_emoji(prono['confidence'])}\n\n"
        )
        if analysis_text:
            text += f"📝 *ANALYSIS*\n{analysis_text}\n\n"
        if key_points:
            text += "🔑 *Key points*:\n" + "\n".join(f"  • {p}" for p in key_points) + "\n\n"
        if verdict:
            text += f"✅ *Verdict*: {verdict}\n\n"
        text += (
            f"🔒 _@{username} — ID:{user_id} — {now}_\n"
            f"⚠️ _Betting involves risks._"
        )
    return text


async def _show_vip_teaser(query, lang: str):
    if lang == 'fr':
        text = (
            "💎 *PRONOS VIP DU JOUR*\n\n"
            "Notre IA a analysé aujourd'hui :\n\n"
            "🔒 Match 1 : Confiance ★★★★★ — VIP\n"
            "🔒 Match 2 : Confiance ★★★★☆ — VIP\n"
            "🔒 Match 3 : Confiance ★★★★☆ — VIP\n"
            "🔒 Match 4 : Confiance ★★★☆☆ — VIP\n"
            "🔒 Match 5 : Confiance ★★★★☆ — VIP\n\n"
            "🚀 Passe VIP pour accéder à toutes les analyses!"
        )
    else:
        text = (
            "💎 *VIP PICKS OF THE DAY*\n\n"
            "Our AI analyzed today:\n\n"
            "🔒 Match 1: Confidence ★★★★★ — VIP\n"
            "🔒 Match 2: Confidence ★★★★☆ — VIP\n"
            "🔒 Match 3: Confidence ★★★★☆ — VIP\n"
            "🔒 Match 4: Confidence ★★★☆☆ — VIP\n"
            "🔒 Match 5: Confidence ★★★★☆ — VIP\n\n"
            "🚀 Go VIP to access all analyses!"
        )
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_upgrade_keyboard(lang))


async def _show_combined_teaser(query, lang: str):
    if lang == 'fr':
        text = (
            "🎯 *COMBINÉ DU JOUR*\n\n"
            "3 matchs sélectionnés par notre IA\n\n"
            "🔒 Match A : ??? @ ?.??\n"
            "🔒 Match B : ??? @ ?.??\n"
            "🔒 Match C : ??? @ ?.??\n\n"
            "🔒 _Débloque avec VIP_"
        )
    else:
        text = (
            "🎯 *DAILY COMBO*\n\n"
            "3 matches selected by our AI\n\n"
            "🔒 Match A: ??? @ ?.??\n"
            "🔒 Match B: ??? @ ?.??\n"
            "🔒 Match C: ??? @ ?.??\n\n"
            "🔒 _Unlock with VIP_"
        )
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=_upgrade_keyboard(lang))
