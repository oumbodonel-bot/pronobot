"""
PronoBot - Bot Telegram de Pronostics Sportifs
"""

import logging
import os
import threading
from flask import Flask, render_template_string, request, abort
from datetime import date, datetime
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters
)
from handlers.start import start_handler, language_handler
from handlers.menu import menu_handler
from handlers.pronos import (
    free_prono_handler, vip_pronos_handler,
    combined_handler, exact_score_handler, montante_handler
)
from handlers.subscription import (
    subscription_handler, payment_handler, check_payment_handler
)
from handlers.admin import (
    admin_handler, broadcast_handler, stats_handler,
    activate_handler, perf_stats_handler
)
from handlers.stats import stats_public_handler, referral_handler
from core.database import init_db, get_conn
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import asyncio
from generate_pronos import generate_daily_pronos
from api.check_results import update_results

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════
# DASHBOARD FLASK (admin web)
# ════════════════════════════════════════

ADMIN_TOKEN = os.getenv("ADMIN_DASHBOARD_TOKEN", "changeme")

flask_app = Flask(__name__)

HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EliteOddsClub — Admin</title>
<style>
  body { font-family: Arial, sans-serif; background: #0f0f1a; color: #e0e0e0; margin: 0; padding: 20px; }
  h1   { color: #f0c040; }
  h2   { color: #80c0ff; border-bottom: 1px solid #333; padding-bottom: 6px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: #1a1a2e; border-radius: 10px; padding: 16px; text-align: center; }
  .card .val { font-size: 2em; font-weight: bold; color: #f0c040; }
  .card .lbl { font-size: 0.85em; color: #999; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
  th    { background: #1a1a2e; color: #80c0ff; padding: 10px; text-align: left; }
  td    { padding: 8px 10px; border-bottom: 1px solid #222; font-size: 0.9em; }
  tr:hover td { background: #1a1a2e; }
  .win     { color: #4caf50; }
  .lose    { color: #f44336; }
  .pending { color: #ff9800; }
  .badge-vip   { background: #f0c040; color: #000; border-radius: 4px; padding: 2px 6px; font-size: 0.75em; }
  .badge-basic { background: #ff9800; color: #000; border-radius: 4px; padding: 2px 6px; font-size: 0.75em; }
  .badge-free  { background: #444;    color: #ccc; border-radius: 4px; padding: 2px 6px; font-size: 0.75em; }
</style>
</head>
<body>
<h1>🤖 EliteOddsClub — Dashboard Admin</h1>

<h2>📊 Vue d'ensemble</h2>
<div class="grid">
  <div class="card"><div class="val">{{ stats.total_users }}</div><div class="lbl">Utilisateurs</div></div>
  <div class="card"><div class="val">{{ stats.vip_users }}</div><div class="lbl">VIP actifs</div></div>
  <div class="card"><div class="val">{{ stats.basic_users }}</div><div class="lbl">Basic actifs</div></div>
  <div class="card"><div class="val">{{ stats.free_users }}</div><div class="lbl">Gratuits</div></div>
  <div class="card"><div class="val">{{ stats.win_rate }}%</div><div class="lbl">Taux de réussite</div></div>
  <div class="card"><div class="val">{{ stats.total_pronos }}</div><div class="lbl">Pronos total</div></div>
</div>

<h2>📅 Pronos du jour</h2>
<table>
  <tr><th>Match</th><th>Type</th><th>Prono</th><th>Cote</th><th>Confiance</th><th>Résultat</th></tr>
  {% for p in pronos %}
  <tr>
    <td>{{ p.home_team }} vs {{ p.away_team }}<br><small>{{ p.league }}</small></td>
    <td>{{ p.prono_type }}</td>
    <td>{{ p.prediction }}</td>
    <td>{{ p.odds }}</td>
    <td>{{ p.confidence }}/4</td>
    <td>
      {% if p.is_correct == True %}<span class="win">✅ {{ p.result }}</span>
      {% elif p.is_correct == False %}<span class="lose">❌ {{ p.result }}</span>
      {% else %}<span class="pending">⏳ En attente</span>{% endif %}
    </td>
  </tr>
  {% endfor %}
</table>

<h2>👥 Derniers utilisateurs</h2>
<table>
  <tr><th>ID</th><th>Nom</th><th>Plan</th><th>Expiration</th><th>Inscrit le</th></tr>
  {% for u in users %}
  <tr>
    <td>{{ u.id }}</td>
    <td>{{ u.first_name }} {% if u.username %}(@{{ u.username }}){% endif %}</td>
    <td>
      {% if u.plan == 'vip' %}<span class="badge-vip">VIP</span>
      {% elif u.plan == 'basic' %}<span class="badge-basic">BASIC</span>
      {% else %}<span class="badge-free">FREE</span>{% endif %}
    </td>
    <td>{{ u.plan_expires_at or '—' }}</td>
    <td>{{ u.created_at.strftime('%d/%m/%Y') if u.created_at else '—' }}</td>
  </tr>
  {% endfor %}
</table>

<h2>📈 Performances (30 derniers jours)</h2>
<table>
  <tr><th>Date</th><th>Total</th><th>Corrects</th><th>Taux</th></tr>
  {% for p in perfs %}
  <tr>
    <td>{{ p.period }}</td>
    <td>{{ p.total_pronos }}</td>
    <td>{{ p.correct_pronos }}</td>
    <td>{{ p.win_rate }}%</td>
  </tr>
  {% endfor %}
</table>

<p style="color:#555; font-size:0.8em">Généré le {{ now }} — EliteOddsClub Admin</p>
</body>
</html>
"""


@flask_app.route("/admin")
def dashboard():
    token = request.args.get("token")
    if token != ADMIN_TOKEN:
        abort(403)

    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        SELECT
            COUNT(*) as total_users,
            SUM(CASE WHEN plan = 'vip'   AND plan_expires_at >= CURRENT_DATE THEN 1 ELSE 0 END) as vip_users,
            SUM(CASE WHEN plan = 'basic' AND plan_expires_at >= CURRENT_DATE THEN 1 ELSE 0 END) as basic_users,
            SUM(CASE WHEN plan = 'free'  OR  plan_expires_at < CURRENT_DATE  THEN 1 ELSE 0 END) as free_users
        FROM users
    """)
    u = cur.fetchone()

    cur.execute("""
        SELECT COUNT(*) as total_pronos,
               SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as correct_pronos
        FROM pronos WHERE result IS NOT NULL
    """)
    p = cur.fetchone()

    total    = p["total_pronos"]   or 0
    correct  = p["correct_pronos"] or 0
    win_rate = round(correct / total * 100, 1) if total > 0 else 0

    stats = {
        "total_users":    u["total_users"]  or 0,
        "vip_users":      u["vip_users"]    or 0,
        "basic_users":    u["basic_users"]  or 0,
        "free_users":     u["free_users"]   or 0,
        "total_pronos":   total,
        "correct_pronos": correct,
        "win_rate":       win_rate,
    }

    cur.execute("SELECT * FROM pronos WHERE match_date = %s ORDER BY confidence DESC", (date.today(),))
    pronos = cur.fetchall()

    cur.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 20")
    users = cur.fetchall()

    cur.execute("SELECT * FROM performance ORDER BY period DESC LIMIT 30")
    perfs = cur.fetchall()

    cur.close()
    conn.close()

    return render_template_string(HTML,
        stats=stats, pronos=pronos, users=users, perfs=perfs,
        now=datetime.now().strftime("%d/%m/%Y %H:%M")
    )


@flask_app.route("/")
def index():
    return "EliteOddsClub Bot — Online ✅", 200


def run_dashboard():
    port = int(os.getenv("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port, use_reloader=False)


# ════════════════════════════════════════
# BOT TELEGRAM
# ════════════════════════════════════════

def main():
    init_db()

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN manquant")

    # Lancer le dashboard Flask en arrière-plan
    t = threading.Thread(target=run_dashboard, daemon=True)
    t.start()
    logger.info("🌐 Dashboard démarré")

        # Configuration du Scheduler en UTC
    scheduler = BackgroundScheduler(timezone=pytz.UTC)
    
    # Tâche 1 : Génération des pronos à 09h00 UTC (10h00 au Cameroun)
    scheduler.add_job(
        lambda: asyncio.run(generate_daily_pronos()),
        trigger=CronTrigger(hour=9, minute=0, timezone=pytz.UTC),
        id="generate_pronos",
        name="Génération quotidienne des pronostics",
        replace_existing=True,
        misfire_grace_time=3600
    )
    
    # Tâche 2 : Vérification des résultats à 11h00 UTC (12h00 au Cameroun)
    scheduler.add_job(
        lambda: asyncio.run(update_results()),
        trigger=CronTrigger(hour=11, minute=0, timezone=pytz.UTC),
        id="check_results",
        name="Vérification quotidienne des résultats",
        replace_existing=True,
        misfire_grace_time=3600
    )
    
    scheduler.start()
    logger.info("⏰ Scheduler démarré en UTC (09h00: Pronos, 11h00: Résultats)")

    app = Application.builder().token(token).build()

    # Commandes
    app.add_handler(CommandHandler("start",    start_handler))
    app.add_handler(CommandHandler("menu",     menu_handler))
    app.add_handler(CommandHandler("admin",    admin_handler))
    app.add_handler(CommandHandler("activate", activate_handler))
    app.add_handler(CommandHandler("broadcast", broadcast_handler))
    app.add_handler(CommandHandler("stats",    stats_public_handler))
    app.add_handler(CommandHandler("referral", referral_handler))

    # Callbacks
    app.add_handler(CallbackQueryHandler(language_handler,      pattern="^lang_"))
    app.add_handler(CallbackQueryHandler(menu_handler,          pattern="^menu$"))
    app.add_handler(CallbackQueryHandler(free_prono_handler,    pattern="^free_prono$"))
    app.add_handler(CallbackQueryHandler(vip_pronos_handler,    pattern="^vip_pronos$"))
    app.add_handler(CallbackQueryHandler(combined_handler,      pattern="^combined$"))
    app.add_handler(CallbackQueryHandler(exact_score_handler,   pattern="^exact_score$"))
    app.add_handler(CallbackQueryHandler(montante_handler,      pattern="^montante$"))
    app.add_handler(CallbackQueryHandler(subscription_handler,  pattern="^subscribe_"))
    app.add_handler(CallbackQueryHandler(payment_handler,       pattern="^pay_"))
    app.add_handler(CallbackQueryHandler(check_payment_handler, pattern="^check_pay_"))
    app.add_handler(CallbackQueryHandler(stats_handler,         pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(broadcast_handler,     pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(perf_stats_handler,    pattern="^perf_stats$"))
    app.add_handler(CallbackQueryHandler(stats_public_handler,  pattern="^public_stats$"))
    app.add_handler(CallbackQueryHandler(referral_handler,      pattern="^referral$"))

    logger.info("🤖 PronoBot démarré!")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
