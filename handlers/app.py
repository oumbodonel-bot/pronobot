"""
Dashboard Admin — Flask
Accès : https://ton-app.railway.app/admin
"""
from flask import Flask, render_template_string, request, redirect, abort
import os
from core.database import get_conn
from datetime import date, timedelta

app   = Flask(__name__)
ADMIN_TOKEN = os.getenv("ADMIN_DASHBOARD_TOKEN", "changeme")

HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>EliteOddsClub — Admin</title>
<style>
  body { font-family: Arial, sans-serif; background: #0f0f1a; color: #e0e0e0; margin: 0; padding: 20px; }
  h1   { color: #f0c040; } h2 { color: #80c0ff; border-bottom: 1px solid #333; padding-bottom: 6px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .card { background: #1a1a2e; border-radius: 10px; padding: 16px; text-align: center; }
  .card .val { font-size: 2em; font-weight: bold; color: #f0c040; }
  .card .lbl { font-size: 0.85em; color: #999; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 24px; }
  th    { background: #1a1a2e; color: #80c0ff; padding: 10px; text-align: left; }
  td    { padding: 8px 10px; border-bottom: 1px solid #222; font-size: 0.9em; }
  tr:hover td { background: #1a1a2e; }
  .win  { color: #4caf50; } .lose { color: #f44336; } .pending { color: #ff9800; }
  .badge-vip  { background: #f0c040; color: #000; border-radius: 4px; padding: 2px 6px; font-size: 0.75em; }
  .badge-free { background: #444;    color: #ccc; border-radius: 4px; padding: 2px 6px; font-size: 0.75em; }
</style>
</head>
<body>
<h1>🤖 EliteOddsClub — Dashboard Admin</h1>

<h2>📊 Vue d'ensemble</h2>
<div class="grid">
  <div class="card"><div class="val">{{ stats.total_users }}</div><div class="lbl">Utilisateurs</div></div>
  <div class="card"><div class="val">{{ stats.vip_users }}</div><div class="lbl">VIP actifs</div></div>
  <div class="card"><div class="val">{{ stats.free_users }}</div><div class="lbl">Gratuits</div></div>
  <div class="card"><div class="val">{{ stats.win_rate }}%</div><div class="lbl">Taux de réussite</div></div>
  <div class="card"><div class="val">{{ stats.total_pronos }}</div><div class="lbl">Pronos total</div></div>
  <div class="card"><div class="val">{{ stats.correct_pronos }}</div><div class="lbl">Pronos corrects</div></div>
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
    <td>{% if u.plan == 'vip' %}<span class="badge-vip">VIP</span>{% else %}<span class="badge-free">FREE</span>{% endif %}</td>
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


@app.route("/admin")
def dashboard():
    token = request.args.get("token")
    if token != ADMIN_TOKEN:
        abort(403)

    conn = get_conn()
    cur  = conn.cursor()

    # Stats globales
    cur.execute("""
        SELECT
            COUNT(*) as total_users,
            SUM(CASE WHEN plan = 'vip' AND plan_expires_at >= CURRENT_DATE THEN 1 ELSE 0 END) as vip_users,
            SUM(CASE WHEN plan = 'free' OR plan_expires_at < CURRENT_DATE THEN 1 ELSE 0 END) as free_users
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
        "free_users":     u["free_users"]   or 0,
        "total_pronos":   total,
        "correct_pronos": correct,
        "win_rate":       win_rate,
    }

    # Pronos du jour
    cur.execute("""
        SELECT * FROM pronos WHERE match_date = %s ORDER BY confidence DESC
    """, (date.today(),))
    pronos = cur.fetchall()

    # Derniers users
    cur.execute("SELECT * FROM users ORDER BY created_at DESC LIMIT 20")
    users = cur.fetchall()

    # Performances 30j
    cur.execute("""
        SELECT * FROM performance
        ORDER BY period DESC LIMIT 30
    """)
    perfs = cur.fetchall()

    cur.close()
    conn.close()

    from datetime import datetime
    return render_template_string(HTML,
        stats=stats, pronos=pronos,
        users=users, perfs=perfs,
        now=datetime.now().strftime("%d/%m/%Y %H:%M")
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
