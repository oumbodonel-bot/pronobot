"""
Base de données - Modèles et initialisation
"""

import os
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date, timedelta, timezone
import logging

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/pronobot")


def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def get_all_users():
    """Récupère tous les utilisateurs pour le broadcast."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return users


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              BIGINT PRIMARY KEY,
            username        TEXT,
            first_name      TEXT,
            language        TEXT DEFAULT 'fr',
            plan            TEXT DEFAULT 'free',
            plan_expires_at DATE,
            referral_code   TEXT UNIQUE,
            referred_by     BIGINT,
            created_at      TIMESTAMP DEFAULT NOW(),
            is_banned       BOOLEAN DEFAULT FALSE
        );

        CREATE TABLE IF NOT EXISTS pronos (
            id              SERIAL PRIMARY KEY,
            match_id        TEXT,
            home_team       TEXT NOT NULL,
            away_team       TEXT NOT NULL,
            league          TEXT NOT NULL,
            match_date      DATE NOT NULL,
            match_time      TIME,
            revealed_at     TIMESTAMPTZ,
            prono_type      TEXT NOT NULL,
            prediction      TEXT NOT NULL,
            confidence      INTEGER NOT NULL,
            odds            FLOAT,
            kelly_stake     FLOAT,
            value_bet       FLOAT,
            analysis_fr     TEXT,
            analysis_en     TEXT,
            exact_score     TEXT,
            result          TEXT,
            is_correct      BOOLEAN,
            plan_required   TEXT DEFAULT 'free',
            created_at      TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS user_consultations (
            id              SERIAL PRIMARY KEY,
            user_id         BIGINT REFERENCES users(id),
            prono_id        INTEGER REFERENCES pronos(id),
            consulted_at    TIMESTAMP DEFAULT NOW(),
            count           INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id              SERIAL PRIMARY KEY,
            user_id         BIGINT REFERENCES users(id),
            plan            TEXT NOT NULL,
            amount          FLOAT NOT NULL,
            currency        TEXT DEFAULT 'XOF',
            payment_method  TEXT,
            payment_ref     TEXT,
            status          TEXT DEFAULT 'pending',
            starts_at       DATE,
            expires_at      DATE,
            created_at      TIMESTAMP DEFAULT NOW()
        );

        CREATE TABLE IF NOT EXISTS performance (
            id              SERIAL PRIMARY KEY,
            period          DATE NOT NULL UNIQUE,
            total_pronos    INTEGER DEFAULT 0,
            correct_pronos  INTEGER DEFAULT 0,
            win_rate        FLOAT DEFAULT 0,
            roi             FLOAT DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_pronos_date ON pronos(match_date);
        CREATE INDEX IF NOT EXISTS idx_consultations_user ON user_consultations(user_id);
        CREATE INDEX IF NOT EXISTS idx_users_plan ON users(plan);
    """)

    try:
        cur.execute("ALTER TABLE pronos ADD COLUMN IF NOT EXISTS match_time TIME")
        cur.execute("ALTER TABLE pronos ADD COLUMN IF NOT EXISTS revealed_at TIMESTAMPTZ")
        cur.execute("ALTER TABLE performance ADD COLUMN IF NOT EXISTS period DATE UNIQUE")
    except Exception:
        pass

    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Base de données initialisée")


# ── USERS ──

def get_user(user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


def create_or_update_user(user_id: int, username: str, first_name: str, language: str = 'fr'):
    conn = get_conn()
    cur = conn.cursor()
    import random, string
    referral = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    cur.execute("""
        INSERT INTO users (id, username, first_name, language, referral_code)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE
        SET username   = EXCLUDED.username,
            first_name = EXCLUDED.first_name
        RETURNING *
    """, (user_id, username, first_name, language, referral))
    user = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return user


def update_user_language(user_id: int, language: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET language = %s WHERE id = %s", (language, user_id))
    conn.commit()
    cur.close()
    conn.close()


def update_user_plan(user_id: int, plan: str, expires_at: date):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET plan = %s, plan_expires_at = %s WHERE id = %s",
        (plan, expires_at, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()


def is_vip(user_id: int) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    if user['plan'] == 'vip' and user['plan_expires_at']:
        return user['plan_expires_at'] >= date.today()
    return False


def is_basic(user_id: int) -> bool:
    """Basic = accès pronos + combiné, pas montante ni score exact."""
    user = get_user(user_id)
    if not user:
        return False
    if user['plan'] == 'basic' and user['plan_expires_at']:
        return user['plan_expires_at'] >= date.today()
    return False


# ── PRONOS ──

def is_revealed(prono) -> bool:
    if not prono.get('revealed_at'):
        return False
    now = datetime.now(timezone.utc)
    revealed_at = prono['revealed_at']
    if isinstance(revealed_at, str):
        # Handle potential Z or +00:00
        revealed_at = datetime.fromisoformat(revealed_at.replace("Z", "+00:00"))
    if revealed_at.tzinfo is None:
        revealed_at = revealed_at.replace(tzinfo=timezone.utc)
    return now >= revealed_at


def time_until_reveal(prono) -> str:
    if not prono.get('revealed_at'):
        return "N/A"
    now = datetime.now(timezone.utc)
    revealed_at = prono['revealed_at']
    if isinstance(revealed_at, str):
        # Handle potential Z or +00:00
        revealed_at = datetime.fromisoformat(revealed_at.replace("Z", "+00:00"))
    if revealed_at.tzinfo is None:
        revealed_at = revealed_at.replace(tzinfo=timezone.utc)
    
    diff = revealed_at - now
    if diff.total_seconds() <= 0:
        return "0h 00min"
        
    hours   = int(diff.total_seconds() // 3600)
    minutes = int((diff.total_seconds() % 3600) // 60)
    return f"{hours}h {minutes:02d}min"


def check_double_consultation(user_id: int, prono_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT COUNT(*) as cnt FROM user_consultations
        WHERE user_id = %s AND prono_id = %s
    """, (user_id, prono_id))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result['cnt'] > 0


def get_today_pronos(plan: str = 'free'):
    conn = get_conn()
    cur = conn.cursor()
    today = date.today()
    cur.execute("""
        SELECT * FROM pronos
        WHERE match_date = %s AND plan_required = %s
        ORDER BY confidence DESC
    """, (today, plan))
    pronos = cur.fetchall()
    cur.close()
    conn.close()
    return pronos


def get_prono_by_type(prono_type: str, today_only: bool = True):
    conn = get_conn()
    cur = conn.cursor()
    today = date.today()
    if today_only:
        cur.execute("""
            SELECT * FROM pronos
            WHERE prono_type = %s AND match_date = %s
            ORDER BY confidence DESC LIMIT 1
        """, (prono_type, today))
    else:
        cur.execute("""
            SELECT * FROM pronos
            WHERE prono_type = %s
            ORDER BY match_date DESC LIMIT 1
        """, (prono_type,))
    prono = cur.fetchone()
    cur.close()
    conn.close()
    return prono


def log_consultation(user_id: int, prono_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO user_consultations (user_id, prono_id)
        VALUES (%s, %s)
    """, (user_id, prono_id))
    conn.commit()
    cur.close()
    conn.close()


def count_free_consultations_today(user_id: int) -> int:
    conn = get_conn()
    cur = conn.cursor()
    today = date.today()
    cur.execute("""
        SELECT COUNT(*) as cnt FROM user_consultations uc
        JOIN pronos p ON p.id = uc.prono_id
        WHERE uc.user_id = %s
          AND DATE(uc.consulted_at) = %s
          AND p.plan_required = 'free'
    """, (user_id, today))
    result = cur.fetchone()
    cur.close()
    conn.close()
    return result['cnt'] if result else 0


def insert_prono(data: dict) -> int:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO pronos (
            match_id, home_team, away_team, league, match_date,
            match_time, revealed_at,
            prono_type, prediction, confidence, odds, kelly_stake,
            value_bet, analysis_fr, analysis_en, exact_score, plan_required
        ) VALUES (
            %(match_id)s, %(home_team)s, %(away_team)s, %(league)s, %(match_date)s,
            %(match_time)s, %(revealed_at)s,
            %(prono_type)s, %(prediction)s, %(confidence)s, %(odds)s, %(kelly_stake)s,
            %(value_bet)s, %(analysis_fr)s, %(analysis_en)s, %(exact_score)s, %(plan_required)s
        ) RETURNING id
    """, data)
    prono_id = cur.fetchone()['id']
    conn.commit()
    cur.close()
    conn.close()
    return prono_id


async def get_team_stats(home_team: str, away_team: str):
    """
    Fonction temporaire pour éviter l'erreur d'import.
    Retourne None pour forcer le Mode B (calibration cotes) qui est plus fiable sans base de données de stats.
    """
    return None, None


def get_global_stats():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COUNT(*) as total_users,
            SUM(CASE WHEN plan = 'vip'   AND plan_expires_at >= CURRENT_DATE THEN 1 ELSE 0 END) as vip_users,
            SUM(CASE WHEN plan = 'basic' AND plan_expires_at >= CURRENT_DATE THEN 1 ELSE 0 END) as basic_users
        FROM users
    """)
    users = cur.fetchone()
    cur.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN is_correct = TRUE THEN 1 ELSE 0 END) as correct
        FROM pronos WHERE result IS NOT NULL
    """)
    perf = cur.fetchone()
    cur.close()
    conn.close()
    return {'users': users, 'performance': perf}


def get_performance_stats(days: int = 30):
    """Stats de performance sur N jours pour /stats public."""
    conn = get_conn()
    cur  = conn.cursor()

    # On calcule les stats directement depuis la table pronos pour plus de fiabilité
    cur.execute(f"""
        SELECT
            COUNT(*)::int                                        AS total,
            COALESCE(SUM(CASE WHEN is_correct = TRUE  THEN 1 ELSE 0 END), 0)::int AS correct,
            COALESCE(SUM(CASE WHEN is_correct = FALSE THEN 1 ELSE 0 END), 0)::int AS wrong,
            ROUND(COALESCE(AVG(CASE WHEN is_correct = TRUE THEN odds ELSE 0 END), 0)::numeric, 2) AS avg_win_odds
        FROM pronos
        WHERE match_date >= CURRENT_DATE - INTERVAL '{days} days'
          AND result IS NOT NULL
    """)
    stats = cur.fetchone()

    cur.execute("""
        SELECT is_correct FROM pronos
        WHERE result IS NOT NULL
        ORDER BY match_date DESC, id DESC
        LIMIT 20
    """)
    rows   = cur.fetchall()
    streak = 0
    streak_type = "❌"
    if rows:
        first = rows[0]["is_correct"]
        streak_type = "✅" if first else "❌"
        for r in rows:
            if r["is_correct"] == first:
                streak += 1
            else:
                break

    cur.close()
    conn.close()
    
    res = dict(stats) if stats else {"total": 0, "correct": 0, "wrong": 0, "avg_win_odds": 0}
    res["streak"] = streak
    res["streak_type"] = streak_type
    return res


def get_user_by_referral(code: str):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT * FROM users WHERE referral_code = %s", (code,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user


def apply_referral_reward(referred_user_id: int, referrer_id: int):
    """Donne 3 jours VIP au parrain."""
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("UPDATE users SET referred_by = %s WHERE id = %s",
                (referrer_id, referred_user_id))

    cur.execute("SELECT plan_expires_at, plan FROM users WHERE id = %s", (referrer_id,))
    referrer = cur.fetchone()
    today    = date.today()

    if referrer["plan"] == "vip" and referrer["plan_expires_at"] and referrer["plan_expires_at"] >= today:
        new_expiry = referrer["plan_expires_at"] + timedelta(days=3)
    else:
        new_expiry = today + timedelta(days=3)

    cur.execute("UPDATE users SET plan = 'vip', plan_expires_at = %s WHERE id = %s",
                (new_expiry, referrer_id))
    conn.commit()
    cur.close()
    conn.close()
