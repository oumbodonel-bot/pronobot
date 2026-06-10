"""
Handlers : /start, choix de langue, menu principal
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from core.database import create_or_update_user, get_user, update_user_language, is_vip
from handlers.stats import handle_referral_start
from utils.texts import t


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    create_or_update_user(user.id, user.username or "", user.first_name or "")

    # Détecter lien de parrainage ← DOIT ÊTRE DANS LA FONCTION
    args = context.args
    if args and args[0].startswith("ref_"):
        ref_code = args[0].replace("ref_", "")
        await handle_referral_start(user.id, ref_code, context)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇫🇷 Français", callback_data="lang_fr"),
            InlineKeyboardButton("🇬🇧 English",  callback_data="lang_en"),
        ]
    ])
    await update.message.reply_text(
        t("welcome", "fr"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )


async def language_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = query.data.split("_")[1]
    update_user_language(query.from_user.id, lang)
    await _show_main_menu(query, lang)


async def menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        db_user = get_user(user_id)
        lang = db_user['language'] if db_user else 'fr'
        await _show_main_menu(query, lang)
    else:
        user_id = update.effective_user.id
        db_user = get_user(user_id)
        lang = db_user['language'] if db_user else 'fr'
        keyboard = _main_menu_keyboard(lang, is_vip(user_id))
        await update.message.reply_text(
            t("main_menu", lang),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )


async def _show_main_menu(query, lang: str):
    from core.database import is_vip, is_basic
    user_id = query.from_user.id
    vip   = is_vip(user_id)
    basic = is_basic(user_id)
    keyboard = _main_menu_keyboard(lang, vip=vip, basic=basic)
    await query.edit_message_text(
        t("main_menu", lang),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )


def _main_menu_keyboard(lang: str, vip: bool = False, basic: bool = False):
    vip_badge   = " 💎" if vip else " 🔒"
    basic_badge = " 💛" if basic else " 🔒"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t("btn_free_prono", lang), callback_data="free_prono")],
        [InlineKeyboardButton(t("btn_vip_pronos", lang) + vip_badge, callback_data="vip_pronos")],
        [
            InlineKeyboardButton(t("btn_combined", lang) + basic_badge, callback_data="combined"),
            InlineKeyboardButton(t("btn_exact_score", lang) + vip_badge, callback_data="exact_score"),
        ],
        [InlineKeyboardButton(t("btn_montante", lang) + vip_badge, callback_data="montante")],
        [InlineKeyboardButton("📊 Nos Performances", callback_data="public_stats")],
        [InlineKeyboardButton("🎁 Parrainer un ami",  callback_data="referral")],
        [InlineKeyboardButton(t("btn_subscribe", lang), callback_data="subscribe_plans")],
    ])
