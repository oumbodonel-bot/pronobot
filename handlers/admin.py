import os
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from core.database import get_global_stats, update_user_plan, get_user

ADMIN_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))

def is_admin(user_id: int) -> bool:
    return user_id == ADMIN_ID

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Accès refusé.")
        return
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistiques", callback_data="admin_stats")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
    ])
    await update.message.reply_text(
        "🔧 *Panel Admin PronoBot*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

async def activate_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Admin only")
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("`/activate USER_ID vip` or `/activate USER_ID basic`", parse_mode=ParseMode.MARKDOWN)
        return
    try:
        target_id = int(context.args[0])
        plan = context.args[1].lower()
        if plan not in ('vip', 'basic'):
            await update.message.reply_text("Invalid plan")
            return
        expires = date.today() + timedelta(days=30)
        update_user_plan(target_id, plan, expires)
        target = get_user(target_id)
        username = target['username'] if target else str(target_id)
        await update.message.reply_text(f"✅ Activated {plan.upper()} for {username}")
        try:
            await context.bot.send_message(target_id, f"🎉 Your {plan.upper()} plan is active until {expires}!")
        except:
            pass
    except Exception as e:
        await update.message.reply_text(f"Error: {str(e)}")

async def perf_stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    stats = get_global_stats()
    p = stats['performance']
    total = p['total'] if p and p['total'] else 0
    correct = p['correct'] if p and p['correct'] else 0
    win_rate = round((correct / total * 100), 1) if total > 0 else 0
    text = f"📊 *OUR TRACK RECORD*\n\n✅ Wins: {correct}/{total}\n📈 Win Rate: {win_rate}%\n\n🧮 Methods: Poisson, Dixon-Coles, xG, Elo, Kelly"
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="menu")]])
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    stats = get_global_stats()
    u = stats['users']
    p = stats['performance']
    win_rate = round((p['correct'] or 0) / p['total'] * 100, 1) if p and p['total'] else 0
    text = f"📊 *ADMIN STATS*\n\n👥 Total Users: {u['total_users']}\n💎 VIP: {u['vip_users']}\n💛 BASIC: {u['basic_users']}\n\n📈 Pronos: {p['total']}\n✅ Winners: {p['correct']}\n📊 Rate: {win_rate}%"
    await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN)

async def broadcast_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        return
    await query.edit_message_text("📢 Send: `/broadcast Your message`", parse_mode=ParseMode.MARKDOWN)
