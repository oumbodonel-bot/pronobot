import os
import asyncio
import logging
from datetime import date, datetime, timezone
from telegram import Bot
from telegram.constants import ParseMode
from core.database import get_conn

# Config logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def send_daily_report():
    """Envoie un rapport de conversion si la journée est bénéficiaire."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN manquant")
        return

    bot = Bot(token=token)
    today = date.today()
    
    conn = get_conn()
    cur = conn.cursor()
    
    # 1. Récupérer les pronos terminés du jour
    cur.execute("""
        SELECT prono_type, is_correct, odds 
        FROM pronos 
        WHERE match_date = %s AND result IS NOT NULL
    """, (today,))
    pronos = cur.fetchall()
    
    if not pronos:
        logger.info("Aucun prono terminé pour le rapport aujourd'hui.")
        return

    # 2. Calculer le bilan
    wins = [p for p in pronos if p['is_correct']]
    total = len(pronos)
    win_rate = (len(wins) / total * 100) if total > 0 else 0
    
    # On considère la journée rentable si win_rate > 60% (ajustable)
    if win_rate < 60:
        logger.info(f"Journée non rentable ({win_rate}%). Pas de rapport envoyé.")
        return

    # 3. Préparer le message de conversion
    # Groupement par section pour le résumé
    sections = {}
    for p in pronos:
        stype = p['prono_type']
        if stype not in sections: sections[stype] = {"total": 0, "wins": 0}
        sections[stype]["total"] += 1
        if p['is_correct']: sections[stype]["wins"] += 1

    report_fr = (
        "📊 *BILAN GAGNANT DU JOUR* ✅\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Quelle journée incroyable ! Notre IA a encore frappé fort aujourd'hui avec un taux de réussite de *{win_rate:.0f}%*.\n\n"
    )
    
    # Détails par section
    type_labels = {
        "free": "⚽ Prono Gratuit",
        "vip": "💎 Pronos VIP",
        "combined": "🎯 Combiné du Jour",
        "montante": "📈 Montante",
        "exact_score": "🎰 Score Exact"
    }
    
    for stype, stats in sections.items():
        label = type_labels.get(stype, stype.upper())
        icon = "✅" if stats['wins'] > 0 else "⏳"
        report_fr += f"{icon} *{label}* : {stats['wins']}/{stats['total']} gagnants\n"

    report_fr += (
        "\n━━━━━━━━━━━━━━━━━━━━\n"
        "🚀 *NE MANQUEZ PLUS RIEN !*\n"
        "Les pronostics de demain sont déjà en préparation. "
        "Passez au niveau supérieur pour accéder à toutes nos analyses exclusives.\n\n"
        "💎 *Plan VIP* : Accès total (Score Exact, Combiné, 5 VIP)\n"
        "💛 *Plan Basic* : Combiné + 3 VIP\n\n"
        "👉 Cliquez sur /menu pour vous abonner !"
    )

    # 4. Envoyer à tous les utilisateurs
    cur.execute("SELECT id FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()

    logger.info(f"Envoi du rapport à {len(users)} utilisateurs...")
    success = 0
    for u in users:
        try:
            await bot.send_message(chat_id=u['id'], text=report_fr, parse_mode=ParseMode.MARKDOWN)
            success += 1
        except Exception:
            pass
    
    logger.info(f"Rapport envoyé avec succès à {success} utilisateurs.")

if __name__ == "__main__":
    asyncio.run(send_daily_report())
