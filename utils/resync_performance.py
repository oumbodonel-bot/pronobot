import logging
from core.database import get_conn

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def resync_performance():
    """
    Recalcule toute la table performance à partir des pronos déjà marqués comme corrects/incorrects.
    """
    logger.info("🔄 Début de la resynchronisation des performances...")
    
    conn = get_conn()
    cur = conn.cursor()
    
    # 1. Récupérer les stats groupées par date
    cur.execute("""
        SELECT 
            match_date, 
            COUNT(*) as total, 
            SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as correct
        FROM pronos
        WHERE is_correct IS NOT NULL
        GROUP BY match_date
        ORDER BY match_date ASC
    """)
    
    stats_by_date = cur.fetchall()
    
    if not stats_by_date:
        logger.warning("Aucun prono avec résultat trouvé dans la table 'pronos'.")
        cur.close()
        conn.close()
        return

    # 2. Nettoyer la table performance (optionnel, ou on utilise ON CONFLICT)
    # cur.execute("DELETE FROM performance") 
    
    # 3. Insérer les nouvelles stats
    for row in stats_by_date:
        period = row['match_date']
        total = row['total']
        correct = row['correct']
        win_rate = round((correct / total) * 100, 1) if total > 0 else 0
        
        cur.execute("""
            INSERT INTO performance (period, total_pronos, correct_pronos, win_rate)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (period) DO UPDATE
            SET total_pronos = EXCLUDED.total_pronos,
                correct_pronos = EXCLUDED.correct_pronos,
                win_rate = EXCLUDED.win_rate
        """, (period, total, correct, win_rate))
        
        logger.info(f"  📅 {period} : {correct}/{total} ({win_rate}%)")

    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Resynchronisation terminée.")

if __name__ == "__main__":
    resync_performance()
