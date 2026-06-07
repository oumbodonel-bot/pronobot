"""
Handlers Abonnements & Paiements
"""

import uuid
import os
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from core.database import get_user, update_user_plan
from utils.texts import t

PAYMENT_NUMBER = os.getenv("PAYMENT_NUMBER", "+225XXXXXXXXXX")
ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))

PLANS = {
    "basic": {"amount": 5000, "days": 30, "label_fr": "BASIC",  "label_en": "BASIC"},
    "vip":   {"amount": 10000, "days": 30, "label_fr": "VIP",   "label_en": "VIP"},
}


async def subscription_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    db_user = get_user(user_id)
    lang = db_user['language'] if db_user else 'fr'

    action = query.data  # "subscribe_plans" or "subscribe_vip" or "subscribe_basic"

    if action == "subscribe_plans":
        await _show_plans(query, lang, db_user)
    elif action == "subscribe_vip":
        await _show_payment(query, lang, "vip", user_id)
    elif action == "subscribe_basic":
        await _show_payment(query, lang, "basic", user_id)


async def _show_plans(query, lang: str, db_user):
    vip_active = db_user and db_user['plan'] == 'vip' and db_user.get('plan_expires_at') and db_user['plan_expires_at'] >= date.today()
    basic_active = db_user and db_user['plan'] == 'basic' and db_user.get('plan_expires_at') and db_user['plan_expires_at'] >= date.today()

    if lang == 'fr':
        status = f"📋 *Ton plan actuel* : {'💎 VIP' if vip_active else ('💛 BASIC' if basic_active else '🆓 Gratuit')}\n\n"
        text = (
            status +
            t("plan_free", lang) + "\n\n" +
            t("plan_basic", lang) + "\n\n" +
            t("plan_vip", lang)
        )
    else:
        status = f"📋 *Your current plan*: {'💎 VIP' if vip_active else ('💛 BASIC' if basic_active else '🆓 Free')}\n\n"
        text = (
            status +
            t("plan_free", lang) + "\n\n" +
            t("plan_basic", lang) + "\n\n" +
            t("plan_vip", lang)
        )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💛 S'abonner BASIC — 5.000 FCFA" if lang == 'fr' else "💛 Subscribe BASIC — 5,000 FCFA", callback_data="subscribe_basic")],
        [InlineKeyboardButton("💎 S'abonner VIP — 10.000 FCFA" if lang == 'fr' else "💎 Subscribe VIP — 10,000 FCFA", callback_data="subscribe_vip")],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="menu")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def _show_payment(query, lang: str, plan: str, user_id: int):
    ref = f"PRONO-{user_id}-{plan.upper()}-{uuid.uuid4().hex[:6].upper()}"
    plan_info = PLANS[plan]

    text = t(
        "payment_instructions", lang,
        plan=plan_info[f"label_{lang}"],
        amount=plan_info["amount"],
        payment_number=PAYMENT_NUMBER,
        ref=ref
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ J'ai payé — Confirmer" if lang == 'fr' else "✅ I've paid — Confirm",
            callback_data=f"check_pay_{plan}_{ref}"
        )],
        [InlineKeyboardButton(t("btn_back", lang), callback_data="subscribe_plans")],
    ])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)


async def payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Redirige vers _show_payment"""
    query = update.callback_query
    await query.answer()
    # Géré dans subscription_handler


async def check_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """L'utilisateur clique sur 'J'ai payé'. Notifie l'admin."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    db_user = get_user(user_id)
    lang = db_user['language'] if db_user else 'fr'

    parts = query.data.split("_")  # check_pay_{plan}_{ref}
    plan = parts[2]
    ref  = parts[3] if len(parts) > 3 else "???"

    # Notifier l'admin
    if ADMIN_ID:
        username = query.from_user.username or "sans username"
        admin_msg = (
            f"💳 *NOUVELLE DEMANDE PAIEMENT*\n\n"
            f"👤 Utilisateur : @{username} (ID: {user_id})\n"
            f"📦 Plan : {plan.upper()}\n"
            f"🔑 Référence : `{ref}`\n\n"
            f"Commandes admin :\n"
            f"`/activate {user_id} {plan}`"
        )
        try:
            await context.bot.send_message(ADMIN_ID, admin_msg, parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass

    if lang == 'fr':
        text = (
            f"⏳ *Paiement en cours de vérification*\n\n"
            f"Référence : `{ref}`\n\n"
            f"Notre équipe va vérifier ton paiement et activer ton compte "
            f"dans les *30 minutes* maximum.\n\n"
            f"Merci pour ta confiance ! 🙏"
        )
    else:
        text = (
            f"⏳ *Payment being verified*\n\n"
            f"Reference: `{ref}`\n\n"
            f"Our team will verify your payment and activate your account "
            f"within *30 minutes* maximum.\n\n"
            f"Thank you for your trust! 🙏"
        )

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton(t("btn_back", lang), callback_data="menu")
        ]])
    )
