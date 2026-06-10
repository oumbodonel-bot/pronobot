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
    text = _format_prono(prono, lang, user_id, username)

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
    if not pronos:
        await query.edit_message_text(
            t("no_prono_today", lang),
            reply_markup=_back_keyboard(lang)
        )
        return

    messages = []
    for i, prono in enumerate(pronos[:max_pronos], 1):
        if not is_revealed(prono):
            timer = _timer_message(prono, lang)
            messages.append(f"🔢 *PRONO {i}/{min(len(pronos), max_pronos)}*\n\n" + timer)
            continue

        already_seen = check_double_consultation(user_id, prono['id'])
        log_consultation(user_id, prono['id'])
        text = f"🔢 *PRONO {i}/{min(len(pronos), max_pronos)}*\n\n" + _format_prono(prono, lang, user_id, username)

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

    pronos = get_today_pronos(plan='vip')
    if len(pronos) < 2:
        await query.edit_message_text(t("no_prono_today", lang), reply_markup=_back_keyboard(lang))
        return

    selected = sorted(pronos, key=lambda x: x['confidence'], reverse=True)[:3]

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
        text = "🎯 *COMBINÉ DU JOUR*\n\n"
        for p in selected:
            log_consultation(user_id, p['id'])
            text += f"✅ *{p['home_team']} vs {p['away_team']}*\n"
            text += f"   └ {p['prediction']} @ {p['odds'] or '?'}\n\n"
        text += f"💰 *Cote totale : {round(total_odds, 2)}*\n"
        text += f"⭐ *Confiance : {stars_emoji(min(4, max(2, int(sum(p['confidence'] for p in selected) / len(selected)))))}*\n\n"
        text += f"🔒 _Combiné pour @{username} — ID:{user_id} — {now}_\n"
        text += f"⚠️ _Les paris comportent des risques._"
    else:
        text = "🎯 *DAILY COMBO*\n\n"
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
