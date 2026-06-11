"""
Handler /stats — Performance publique + Parrainage
"""
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from core.database import (
    get_user, get_performance_stats,
    get_user_by_referral, apply_referral_reward,
    update_user_plan
)
from core.database import get_conn


async def stats_public_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche les stats de performance publiques."""
    query = update.callback_query
    if query:
        await query.answer()
        send = query.edit_message_text
    else:
        send = update.message.reply_text

    stats    = get_performance_stats(30)
    total    = stats["total"]   or 0
    correct  = stats["correct"] or 0
    wrong    = stats["wrong"]   or 0
    win_rate = round(correct / total * 100, 1) if total > 0 else 0
    streak   = stats["streak"]
    s_type   = stats["streak_type"]

    msg = (
        f"📊 *EliteOddsClub — Performances*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 *30 derniers jours*\n\n"
        f"✅ Gagnants : `{correct}`\n"
        f"❌ Perdants : `{wrong}`\n"
        f"📈 Taux de réussite : `{win_rate}%`\n"
        f"🔥 Streak actuel : `{streak} {s_type}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Les résultats passés ne garantissent pas les performances futures._"
    )
    await send(msg, parse_mode="Markdown")


async def referral_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Affiche le lien de parrainage de l'utilisateur."""
    query = update.callback_query
    if query:
        await query.answer()
        user_id = query.from_user.id
        send    = query.edit_message_text
    else:
        user_id = update.effective_user.id
        send    = update.message.reply_text

    user = get_user(user_id)
    if not user:
        await send("Démarre d'abord avec /start")
        return

    code      = user["referral_code"]
    bot_name  = context.bot.username
    link      = f"https://t.me/{bot_name}?start=ref_{code}"
    nb_parr   = await _count_referrals(user_id)  # ← await séparé, pas dans f-string

    msg = (
        f"🎁 *Ton lien de parrainage*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"`{link}`\n\n"
        f"👆 Partage ce lien à tes amis !\n\n"
        f"*Récompense :*\n"
        f"Pour chaque ami qui s'inscrit et s'abonne → tu reçois *+3 jours VIP* offerts 🎉\n\n"
        f"*Tes parrainages actifs :* _{nb_parr}_"
    )
    await send(msg, parse_mode="Markdown")


async def _count_referrals(user_id: int) -> int:
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) as cnt FROM users WHERE referred_by = %s", (user_id,))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result["cnt"] if result else 0


async def handle_referral_start(user_id: int, ref_code: str, context):
    """Appelé au /start si le lien contient ref_XXXX."""
    if not ref_code:
        return
    referrer = get_user_by_referral(ref_code)
    if not referrer:
        return
    if referrer["id"] == user_id:
        return  # Pas d'auto-parrainage
    user = get_user(user_id)
    if user and user.get("referred_by"):
        return  # Déjà parrainé

    apply_referral_reward(user_id, referrer["id"])

    try:
        await context.bot.send_message(
            chat_id=referrer["id"],
            text="🎉 *+3 jours VIP offerts !*\nUn ami a rejoint EliteOddsClub grâce à ton lien !",
            parse_mode="Markdown"
        )
    except:
        pass
