from flask import Flask, render_template_string, request, redirect, url_for, jsonify, session
from functools import wraps
import threading, logging
import bot, config, utils

app = Flask(__name__)
app.secret_key = (config.ADMIN_PASSWORD or "default") + "_secret_key"

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

LOGIN_TEMPLATE = """
<!doctype html>
<title>XT Arb Admin - Login</title>
<h2>{{bot_name}} — Admin Login</h2>
{% if error %}
<p style="color: red;">{{error}}</p>
{% endif %}
<form method="post">
Password: <input type="password" name="password" required><br><br>
<input type="submit" value="Login">
</form>
"""

TEMPLATE = """
<!doctype html>
<title>XT Arb Admin</title>
<h2>{{bot_name}} — Admin panel</h2>
<a href="/logout" style="float: right;">Logout</a>
<p><strong>Status:</strong> {% if dry_run %}DRY RUN MODE (Safe){% else %}<span style="color: red;">LIVE TRADING ACTIVE</span>{% endif %}</p>

<h3>🤖 Bot Control</h3>
<form method="post" action="/control" style="margin-bottom: 20px;">
<button name="action" value="start" type="submit" style="background-color: green; color: white; padding: 10px 20px; margin: 5px;">▶️ START BOT</button>
<button name="action" value="stop" type="submit" style="background-color: red; color: white; padding: 10px 20px; margin: 5px;">⏹️ STOP BOT</button>
<button name="action" value="refresh" type="submit" style="background-color: blue; color: white; padding: 10px 20px; margin: 5px;">🔄 REFRESH BALANCE</button>
</form>

<h3>Account Balance</h3>
<table border="1" style="border-collapse: collapse;">
<tr><th>Currency</th><th>Total</th><th>Available</th><th>Used</th></tr>
{% for currency, info in balance.items() %}
<tr>
  <td>{{currency}}</td>
  <td>{{info.total|round(4)}}</td>
  <td>{{info.available|round(4)}}</td>
  <td>{{info.used|round(4)}}</td>
</tr>
{% endfor %}
</table>
<form method="post" action="/update">
Order amount (USDT): <input name="order_amount" value="{{order_amount}}"><br>
Min spread (%): <input name="min_spread" value="{{min_spread}}"><br>
Leverage: <input name="leverage" value="{{leverage}}"><br>
Max open positions per symbol: <input name="max_open" value="{{max_open}}"><br>
Order book depth: <input name="depth" value="{{depth}}"><br>
{% if allow_live %}
DRY_RUN: <input type="checkbox" name="dry" {% if dry_run %}checked{% endif %}><br>
{% else %}
DRY_RUN: <input type="checkbox" checked disabled> (Locked for security)<br>
{% endif %}
<input type="submit" value="Save">
</form>

<h3>Symbols (toggle to enable/disable)</h3>
<form method="post" action="/toggle">
{% for s, enabled in symbols.items() %}
  <input type="checkbox" name="sym" value="{{s}}" {% if enabled %}checked{% endif %}>{{s}}<br>
{% endfor %}
<input type="submit" value="Apply">
</form>

<h3>Active positions</h3>
<ul>
{% for s, pos in active.items() %}
  <li>{{s}}: {{pos}}</li>
{% endfor %}
</ul>
"""

@app.route("/")
@login_required
def index():
    # Отримання балансу з XT.com (обидва акаунти)
    try:
        from xt_client import get_xt_futures_balance
        balance_1 = get_xt_futures_balance(bot.xt_account_1)
        balance_2 = get_xt_futures_balance(bot.xt_account_2)
        
        # Загальний баланс з обох акаунтів
        xt_balance_data = {
            'total': balance_1.get('total', 0) + balance_2.get('total', 0),
            'free': balance_1.get('free', 0) + balance_2.get('free', 0),
            'used': balance_1.get('used', 0) + balance_2.get('used', 0)
        }
        
        # Формуємо баланс тільки для XT.com
        filtered_balance = {}
        if float(xt_balance_data.get('total', 0)) > 0:
            filtered_balance['XT_USDT'] = {
                'total': xt_balance_data.get('total', 0),
                'available': xt_balance_data.get('free', 0),
                'used': xt_balance_data.get('used', 0)
            }
                
    except Exception as e:
        logging.error(f"Помилка отримання XT.com балансу: {e}")
        filtered_balance = {}
    
    return render_template_string(TEMPLATE,
        bot_name=config.BOT_NAME,
        order_amount=config.ORDER_AMOUNT,
        min_spread=config.MIN_SPREAD,
        leverage=config.LEVERAGE,
        max_open=config.MAX_OPEN_POSITIONS,
        depth=config.ORDER_BOOK_DEPTH,
        dry_run=config.DRY_RUN,
        allow_live=config.ALLOW_LIVE_TRADING,
        symbols=bot.trade_symbols,
        active=bot.active_positions,
        balance=filtered_balance
    )

@app.route("/update", methods=["POST"])
@login_required
def update():
    # ORDER_AMOUNT тепер ФІКСОВАНИЙ на 5.0 USDT - не змінюється
    # config.ORDER_AMOUNT = float(request.form.get("order_amount", config.ORDER_AMOUNT)) # ЗАБЛОКОВАНО
    config.MIN_SPREAD = float(request.form.get("min_spread", config.MIN_SPREAD))
    config.LEVERAGE = int(request.form.get("leverage", config.LEVERAGE))
    config.MAX_OPEN_POSITIONS = int(request.form.get("max_open", config.MAX_OPEN_POSITIONS))
    config.ORDER_BOOK_DEPTH = int(request.form.get("depth", config.ORDER_BOOK_DEPTH))
    config.DRY_RUN = request.form.get("dry", str(config.DRY_RUN)) in ["True","true","1","on"]
    utils.save_config_to_file({
        # "ORDER_AMOUNT": config.ORDER_AMOUNT,  # ЗАБЛОКОВАНО - завжди 5.0
        "MIN_SPREAD": config.MIN_SPREAD,
        "LEVERAGE": config.LEVERAGE,
        "MAX_OPEN_POSITIONS": config.MAX_OPEN_POSITIONS,
        "ORDER_BOOK_DEPTH": config.ORDER_BOOK_DEPTH,
        "DRY_RUN": config.DRY_RUN
    })
    return redirect(url_for('index'))

@app.route("/toggle", methods=["POST"])
@login_required
def toggle():
    sels = request.form.getlist("sym")
    for s in list(bot.trade_symbols.keys()):
        bot.trade_symbols[s] = (s in sels)
    return redirect(url_for('index'))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        # Підтримка двох адмінів з різними паролями
        if password == config.ADMIN_PASSWORD or (config.ADMIN_2_PASSWORD and password == config.ADMIN_2_PASSWORD):
            session['logged_in'] = True
            # Зберігаємо який адмін увійшов
            if password == config.ADMIN_PASSWORD:
                session['admin_id'] = 1
                logging.info("✅ Адмін 1 увійшов в систему")
            else:
                session['admin_id'] = 2
                logging.info("✅ Адмін 2 увійшов в систему")
            return redirect(url_for('index'))
        else:
            error = "Невірний пароль"
    return render_template_string(LOGIN_TEMPLATE, 
                                  bot_name=config.BOT_NAME, 
                                  error=error)

@app.route("/control", methods=["POST"])
@login_required  
def control():
    action = request.form.get("action")
    if action == "start":
        # Запустити бота (перезапустити воркери)
        bot.restart_workers()
        logging.info("🟢 Bot STARTED via admin panel")
    elif action == "stop":
        # Зупинити бота
        bot.stop_all_workers()
        logging.info("🔴 Bot STOPPED via admin panel")
    elif action == "refresh":
        logging.info("🔄 Balance refreshed via admin panel")
    return redirect(url_for('index'))

@app.route("/logout")
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route("/api/auth/login", methods=["POST"])
def api_login():
    """API endpoint для React frontend"""
    try:
        data = request.get_json()
        api_key = data.get('api_key', '')
        api_secret = data.get('api_secret', '')
        password = data.get('password', '')
        
        if password != config.ADMIN_PASSWORD:
            return jsonify({"success": False, "detail": "Неправильний пароль"}), 401
        
        import os
        if api_key != os.getenv('XT_API_KEY') or api_secret != os.getenv('XT_API_SECRET'):
            return jsonify({"success": False, "detail": "Неправильні API ключі XT.com"}), 401
        
        session['logged_in'] = True
        return jsonify({
            "success": True,
            "token": "trinkenbot-session-token",
            "message": "Успішний вхід"
        })
    except Exception as e:
        logging.error(f"API login error: {e}")
        return jsonify({"success": False, "detail": str(e)}), 500

def run_admin():
    app.run(host="0.0.0.0", port=5000, debug=False)

if __name__ == "__main__":
    run_admin()