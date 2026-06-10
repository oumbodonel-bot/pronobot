"""
PronoBot - Bot Telegram de Pronostics Sportifs
Auteur: PronoBot Team
"""

import logging
import os
import threading
from dashboard.app import app as flask_app

def run_dashboard():
    flask_app.run(host="0.0.0.0", port=8080)

def main():
    init_db()

    # Lancer le dashboard en arrière-plan
    thread = threading.Thread(target=run_dashboard, daemon=True)
    thread.start()
from handlers.stats import stats_public_handler, referral_handler, handle_referral_start
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler
)
from handlers.start import start_handler, language_handler
from handlers.menu import menu_handler
from handlers.pronos import (
    free_prono_handler,
    vip_pronos_handler,
    combined_handler,
    exact_score_handler,
    montante_handler
)
from handlers.subscription import (
    subscription_handler,
    payment_handler,
    check_payment_handler
)
from handlers.admin import (
    admin_handler,
    broadcast_handler,
    stats_handler,
    activate_handler,
    perf_stats_handler
)
from core.database import init_db

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)


def main():
    """Démarrage du bot"""
    init_db()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN manquant dans les variables d'environnement")

    app = Application.builder().token(token).build()

    # ── Commandes de base ──
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("menu", menu_handler))
    app.add_handler(CommandHandler("admin", admin_handler))
    app.add_handler(CommandHandler("activate", activate_handler))
    app.add_handler(CommandHandler("stats",    stats_public_handler))
    app.add_handler(CommandHandler("referral", referral_handler))

    # ── Callbacks boutons ──
    app.add_handler(CallbackQueryHandler(language_handler, pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(menu_handler, pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(free_prono_handler, pattern="^free_prono$"))
    app.add_handler(CallbackQueryHandler(vip_pronos_handler, pattern="^vip_pronos$"))
    app.add_handler(CallbackQueryHandler(combined_handler, pattern="^combined$"))
    app.add_handler(CallbackQueryHandler(exact_score_handler, pattern="^exact_score$"))
    app.add_handler(CallbackQueryHandler(montante_handler, pattern="^montante$"))
    app.add_handler(CallbackQueryHandler(subscription_handler, pattern="^subscribe_"))
    app.add_handler(CallbackQueryHandler(payment_handler, pattern="^pay_"))
    app.add_handler(CallbackQueryHandler(check_payment_handler, pattern="^check_pay_"))
    app.add_handler(CallbackQueryHandler(stats_handler, pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(broadcast_handler, pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(perf_stats_handler, pattern="^perf_stats$"))
    app.add_handler(CallbackQueryHandler(stats_public_handler, pattern="^public_stats$"))

    logger.info("🤖 PronoBot démarré avec succès!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
