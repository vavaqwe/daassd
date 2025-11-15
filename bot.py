import time
import threading
import requests
import json
import os
from collections import deque
from config import *
from utils import calculate_spread, send_telegram, plot_spread_live, save_config_to_file, load_config_from_file, generate_crypto_signal, test_telegram_configuration, get_proper_dexscreener_link, send_to_admins_and_group
from telegram_admin import run_telegram_bot
# Gate.io integration removed - using only XT.com
# # # import gate_client  # Видалено - використовуємо тільки XT  # Removed: XT.com only system removed
from xt_client import create_xt, load_xt_futures_markets, get_xt_price, is_xt_futures_tradeable, get_xt_futures_balance, xt_open_market_position, xt_close_position_market, analyze_xt_order_book_liquidity, fetch_xt_ticker, fetch_xt_order_book, get_xt_open_positions
import xt_client

# Helper functions for XT.com compatibility (replacing Gate.io functions)
def fetch_ticker(exchange, symbol):
    """Wrapper for XT ticker"""
    return fetch_xt_ticker(exchange, symbol)

def fetch_order_book(exchange, symbol, depth=10):
    """Wrapper for XT order book"""
    return fetch_xt_order_book(exchange, symbol, depth)
from dex_client import get_dex_price_simple, get_dex_token_info, get_advanced_token_analysis
import logging
from datetime import datetime
import threading

# XT.com - ДВА ПАРАЛЕЛЬНИХ АКАУНТИ
xt_account_1 = create_xt(api_key=XT_API_KEY, api_secret=XT_API_SECRET, account_name="Account 1")  # Перший акаунт

# Другий акаунт тільки якщо налаштовано ключі
if XT_ACCOUNT_2_API_KEY and XT_ACCOUNT_2_API_SECRET:
    xt_account_2 = create_xt(api_key=XT_ACCOUNT_2_API_KEY, api_secret=XT_ACCOUNT_2_API_SECRET, account_name="Account 2")
    logging.info("✅ Другий XT акаунт налаштовано")
else:
    xt_account_2 = xt_account_1  # Використовуємо перший акаунт якщо другий не налаштовано
    logging.info("ℹ️ Другий XT акаунт не налаштовано, використовуємо тільки перший")

xt = xt_account_1  # Для backwards compatibility з існуючим кодом
markets = {}  # XT markets will be stored here
xt_markets_available = True
trade_symbols = {}  # runtime on/off per symbol
active_positions = {}  # symbol -> position dict {side, avg_entry, size_usdt, adds_done, last_add_price, tp_price, last_add_time, opened_at, expires_at, xt_pair_url, account}
active_positions_account_2 = {}  # Позиції другого акаунту

spread_store = deque(maxlen=1000)
_plot_thread = None
bot_running = True
monitor_stop_event = threading.Event()  # 🛡️ THREAD-SAFE MONITOR: Event замість boolean
monitor_lifecycle_lock = threading.Lock()  # 🔒 ЗАХИСТ від дублікатів потоків
worker_threads = []
monitor_thread = None  # 🎯 Референс на потік моніторингу

# 🕒 КУЛДАУН система для кожної монети (2 хвилини як просив користувач)
telegram_cooldown = {}  # symbol -> timestamp останнього сигналу
# TELEGRAM_COOLDOWN_SEC імпортується з config.py автоматично

# 🔒 SIMPLE THREADING LOCKS (replaced external locks module)
active_positions_lock = threading.Lock()
balance_check_lock = threading.Lock()
order_placement_lock = threading.Lock()
config_lock = threading.Lock()
telegram_cooldown_lock = threading.Lock()
opportunities_lock = threading.Lock()
signals_lock = threading.Lock()
trading_lock = threading.Lock()
monitoring_lock = threading.Lock()
processing_symbols_lock = threading.Lock()

# 🎯 ГЛОБАЛЬНИЙ ПОШУКАЧ НАЙКРАЩИХ МОЖЛИВОСТЕЙ (замість багатьох сигналів)
best_opportunities = {}  # {symbol: {spread, side, score, data}}
last_best_signal_time = 0
BEST_SIGNAL_INTERVAL = 30  # Відправляємо ОДИН найкращий сигнал раз на 30 секунд

# ------------------------------------------------------
# ⚫ BLACKLIST SYSTEM (ЧОРНИЙ СПИСОК)
# ------------------------------------------------------
blacklist_lock = threading.Lock()
blacklist_file = 'blacklist.json'
blacklist_data = {
    "banned_symbols": [],  # Список заблокованих символів
    "loss_counts": {}      # Лічильник збитків: {"BTC/USDT": 1}
}

def load_blacklist():
    """Завантажує чорний список з файлу при старті"""
    global blacklist_data
    try:
        if os.path.exists(blacklist_file):
            with open(blacklist_file, 'r') as f:
                blacklist_data = json.load(f)
            logging.info(f"⚫ BLACKLIST: Завантажено {len(blacklist_data['banned_symbols'])} заблокованих монет")
        else:
            logging.info("⚫ BLACKLIST: Файл не знайдено, починаємо з чистого аркуша")
    except Exception as e:
        logging.error(f"❌ Помилка завантаження blacklist: {e}")

def save_blacklist():
    """Зберігає чорний список у файл"""
    try:
        with blacklist_lock:
            with open(blacklist_file, 'w') as f:
                json.dump(blacklist_data, f, indent=4)
    except Exception as e:
        logging.error(f"❌ Помилка збереження blacklist: {e}")

def check_and_update_blacklist(symbol, pnl_pct):
    """
    Перевіряє, чи був це Stop Loss, і оновлює лічильник.
    Якщо 3 збитки підряд — додає в бан.
    """
    # Флаг для відправки повідомлення ЗА МЕЖАМИ локу
    should_send_blacklist_alert = False
    
    # Якщо збиток більший або рівний нашому STOP_LOSS_PCT (наприклад, -3%)
    # pnl_pct буде від'ємним числом, тому порівнюємо: -3.5 <= -3.0
    if pnl_pct <= -STOP_LOSS_PCT:
        with blacklist_lock:
            # Отримуємо поточну кількість збитків
            current_losses = blacklist_data["loss_counts"].get(symbol, 0) + 1
            blacklist_data["loss_counts"][symbol] = current_losses
            
            logging.warning(f"⚠️ [{symbol}] STOP LOSS #{current_losses}! (Поріг: 3)")

            if current_losses >= 3:
                if symbol not in blacklist_data["banned_symbols"]:
                    blacklist_data["banned_symbols"].append(symbol)
                    logging.warning(f"⛔ [{symbol}] ДОДАНО В ЧОРНИЙ СПИСОК (3 stop-loss)")
                    should_send_blacklist_alert = True  # 🔧 ФІКС: Встановлюємо флаг замість відправки
            
            save_blacklist()
        
        # 🔧 КРИТИЧНИЙ ФІКС: Відправляємо Telegram ЗА МЕЖАМИ локу
        if should_send_blacklist_alert:
            send_to_admins_and_group(f"⛔ **BLACKLIST ALERT**\nMoneta **{symbol}** отримала 3 стоп-лосси і заблокована для торгівлі.")
    
    # (Опціонально) Якщо отримали Тейк-Профіт, можна скидати лічильник невдач:
    elif pnl_pct >= TAKE_PROFIT_PCT:
        with blacklist_lock:
            if symbol in blacklist_data["loss_counts"] and blacklist_data["loss_counts"][symbol] > 0:
                blacklist_data["loss_counts"][symbol] = 0
                save_blacklist()
                logging.info(f"♻️ [{symbol}] Лічильник збитків скинуто після успішного TP")
# ------------------------------------------------------

# 💾 ФУНКЦІЇ ЗБЕРЕЖЕННЯ/ЗАВАНТАЖЕННЯ ПОЗИЦІЙ
def save_positions_to_file():
    """Зберігає active_positions в positions.json з захистом від race conditions"""
    try:
        with active_positions_lock:
            positions_data = active_positions.copy()
        
        # Додаємо мітку часу збереження для діагностики
        save_data = {
            'positions': positions_data,
            'saved_at': time.time(),
            'version': '1.1'  # Версія для сумісності
        }
        
        with open('positions.json', 'w') as f:
            json.dump(save_data, f, indent=2)
        
        logging.info(f"💾 Збережено {len(positions_data)} позицій в positions.json")
        return True
    except Exception as e:
        logging.error(f"❌ Помилка збереження позицій: {e}")
        return False

def load_positions_from_file():
    """Завантажує позиції з positions.json та оновлює expires_at для існуючих позицій"""
    global active_positions
    
    try:
        if not os.path.exists('positions.json'):
            logging.info("📁 positions.json не знайдено, починаємо з пустих позицій")
            return
        
        with open('positions.json', 'r') as f:
            save_data = json.load(f)
        
        # Підтримка старих форматів та нових
        if isinstance(save_data, dict) and 'positions' in save_data:
            loaded_positions = save_data['positions']
            saved_at = save_data.get('saved_at', time.time())
        else:
            # Старий формат: прямо словник позицій
            loaded_positions = save_data
            saved_at = time.time()
        
        current_time = time.time()
        valid_positions = {}
        
        for symbol, position in loaded_positions.items():
            # ФІКС БАГУ: НЕ перезаписуємо існуючі timestamps!
            if 'opened_at' not in position or position.get('opened_at', 0) <= 0:
                position['opened_at'] = saved_at  # Наближена мітка часу
                logging.info(f"🔧 {symbol}: Відновлено opened_at={position['opened_at']} з файлу")
            else:
                logging.info(f"🔧 {symbol}: Збережено існуючий opened_at={position['opened_at']} з файлу")
            
            if 'expires_at' not in position or position.get('expires_at', 0) <= 0:
                position['expires_at'] = position['opened_at'] + POSITION_MAX_AGE_SEC
                logging.info(f"🔧 {symbol}: Відновлено expires_at={position['expires_at']} з файлу")
            else:
                logging.info(f"🔧 {symbol}: Збережено існуючий expires_at={position['expires_at']} з файлу")
            
            if 'xt_pair_url' not in position:
                position['xt_pair_url'] = generate_xt_pair_url(symbol)
            
            # Перевіряємо чи позиція не прострочена
            if ENABLE_TIME_STOP and current_time >= position['expires_at']:
                logging.warning(f"⏰ {symbol}: Позиція прострочена ({(current_time - position['expires_at'])/60:.1f}хв), буде закрита")
                # Не додаємо прострочену позицію, вона буде закрита в наступному циклі моніторингу
            else:
                valid_positions[symbol] = position
        
        with active_positions_lock:
            active_positions.update(valid_positions)
        
        logging.info(f"📂 Завантажено {len(valid_positions)} валідних позицій з positions.json")
        
        # Зберігаємо оновлені позиції
        if len(valid_positions) != len(loaded_positions):
            save_positions_to_file()
        
    except Exception as e:
        logging.error(f"❌ Помилка завантаження позицій: {e}")

def get_positions_by_account():
    """Повертає позиції розділені по акаунтах + загальну кількість"""
    try:
        with active_positions_lock:
            positions_acc_1 = active_positions.copy()
            positions_acc_2 = active_positions_account_2.copy()
        
        # Формуємо список позицій акаунту 1
        account_1_positions = []
        for symbol, position in positions_acc_1.items():
            # Забезпечуємо що всі числові поля мають валідні значення (не None)
            avg_entry = position.get('avg_entry')
            avg_entry = float(avg_entry) if avg_entry is not None and avg_entry != 0 else 0.0
            
            size_usdt = position.get('size_usdt', 0)
            size_usdt = float(size_usdt) if size_usdt is not None else 0.0
            
            pnl = calculate_pnl_percentage(position) if avg_entry > 0 else 0.0
            pnl = float(pnl) if pnl is not None else 0.0
            
            position_data = {
                'symbol': symbol,
                'side': position.get('side', 'LONG'),
                'size': size_usdt,
                'entry_price': avg_entry,
                'pnl': pnl,
                'account': 1
            }
            account_1_positions.append(position_data)
        
        # Формуємо список позицій акаунту 2
        account_2_positions = []
        for symbol, position in positions_acc_2.items():
            # Забезпечуємо що всі числові поля мають валідні значення (не None)
            avg_entry = position.get('avg_entry')
            avg_entry = float(avg_entry) if avg_entry is not None and avg_entry != 0 else 0.0
            
            size_usdt = position.get('size_usdt', 0)
            size_usdt = float(size_usdt) if size_usdt is not None else 0.0
            
            pnl = calculate_pnl_percentage(position) if avg_entry > 0 else 0.0
            pnl = float(pnl) if pnl is not None else 0.0
            
            position_data = {
                'symbol': symbol,
                'side': position.get('side', 'LONG'),
                'size': size_usdt,
                'entry_price': avg_entry,
                'pnl': pnl,
                'account': 2
            }
            account_2_positions.append(position_data)
        
        total_positions = len(positions_acc_1) + len(positions_acc_2)
        
        return {
            'account_1': account_1_positions,
            'account_2': account_2_positions,
            'total': total_positions,
            'account_1_count': len(account_1_positions),
            'account_2_count': len(account_2_positions)
        }
    except Exception as e:
        logging.error(f"❌ Помилка get_positions_by_account: {e}")
        return {
            'account_1': [],
            'account_2': [],
            'total': 0,
            'account_1_count': 0,
            'account_2_count': 0
        }

def generate_xt_pair_url(symbol):
    """Генерує XT.com посилання для торгової пари"""
    try:
        # Очищаємо символ: ETH/USDT:USDT → ETHUSDT
        clean_symbol = symbol.replace('/USDT:USDT', '').replace('/USDT', '').upper()
        pair = f"{clean_symbol}USDT"
        # ✅ ПРАВИЛЬНИЙ ФОРМАТ XT.com futures trading
        return f"https://www.xt.com/en/trade/futures_{pair}"
    except:
        return "https://www.xt.com/en/trade"

def calculate_pnl_percentage(position, use_leverage=True):
    """
    🧮 УНІФІКОВАНИЙ розрахунок PnL у відсотках з fallback логікою та XT ticker
    
    Args:
        position: словник позиції з різними ключами для цін
        use_leverage: чи застосовувати леверидж до P&L (за замовчуванням True)
    
    Returns:
        float: PnL у відсотках
    """
    try:
        symbol = position.get('symbol', 'UNKNOWN')
        
        # 🔧 FALLBACK ЛОГІКА для entry price
        entry_price = float(
            position.get('entryPrice') or 
            position.get('avg_entry') or 
            position.get('entry_price') or 0
        )
        
        # 🔧 FALLBACK ЛОГІКА для current price
        current_price = float(
            position.get('markPrice') or 
            position.get('currentPrice') or 
            position.get('current_price') or 0
        )
        
        # 🚀 КРИТИЧНО: Якщо currentPrice відсутня, отримуємо з XT ticker
        if current_price <= 0 and symbol != 'UNKNOWN' and xt:
            try:
                xt_ticker = xt.fetch_ticker(symbol)
                if xt_ticker and xt_ticker.get('last'):
                    current_price = float(xt_ticker['last'])
                    # Оновлюємо позицію для наступних викликів
                    position['currentPrice'] = current_price
                    logging.info(f"🔄 [{symbol}] XT ticker ціна: ${current_price}")
            except Exception as ticker_error:
                logging.warning(f"⚠️ [{symbol}] Помилка XT ticker: {ticker_error}")
        
        # 🔧 Нормалізація сторони
        side = str(position.get('side', 'LONG')).upper()
        if side.lower() in ['buy', 'long']:
            side = 'LONG'
        elif side.lower() in ['sell', 'short']:
            side = 'SHORT'
        
        # 🧮 Валідація даних
        if entry_price <= 0 or current_price <= 0:
            if symbol != 'UNKNOWN':
                logging.warning(f"🚨 [{symbol}] P&L неможливо: entry={entry_price}, current={current_price}")
            return 0.0
        
        # 📊 Розрахунок базового P&L%
        if side == 'LONG':
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:  # SHORT
            pnl_pct = ((entry_price - current_price) / entry_price) * 100
        
        # ⚡ Застосування левериджу якщо потрібно
        if use_leverage:
            leverage = float(position.get('leverage', LEVERAGE))
            pnl_pct = pnl_pct * leverage
        
        logging.info(f"✅ [{symbol}] P&L: {side} {pnl_pct:.2f}% (entry=${entry_price}, current=${current_price}, lev={use_leverage})")
        return round(pnl_pct, 2)
        
    except Exception as e:
        symbol = position.get('symbol', 'UNKNOWN') if isinstance(position, dict) else 'UNKNOWN'
        logging.error(f"❌ P&L помилка [{symbol}]: {e}")
        return 0.0

def send_best_opportunity_signal():
    """
    🎯 ВИБІРКА НАЙКРАЩОЇ МОЖЛИВОСТІ: замість багатьох сигналів - ОДИН найкращий
    """
    global last_best_signal_time, best_opportunities
    
    while bot_running:
        try:
            current_time = time.time()
            
            # Перевіряємо чи настав час для нового сигналу
            if current_time - last_best_signal_time >= BEST_SIGNAL_INTERVAL:
                with opportunities_lock:
                    if best_opportunities:
                        # Знаходимо найкращу можливість за рейтингом
                        best_symbol = max(best_opportunities.keys(), 
                                         key=lambda s: best_opportunities[s]['score'])
                        best_data = best_opportunities[best_symbol]
                        
                        # Очищуємо старі можливості (старші 60 секунд)
                        old_threshold = current_time - 60
                        fresh_opportunities = {k: v for k, v in best_opportunities.items() 
                                             if v['timestamp'] > old_threshold}
                        best_opportunities.clear()
                        best_opportunities.update(fresh_opportunities)
                        
                        # 🔒 КРИТИЧНО: Перевіряємо кулдаун для найкращої можливості!
                        if best_data['timestamp'] > old_threshold:  # Перевіряємо свіжість
                            
                            # 🕒 THREAD-SAFE КУЛДАУН: перевіряємо чи можна відправити сигнал для цього символу
                            signal_allowed = False
                            with telegram_cooldown_lock:
                                last_signal_time = telegram_cooldown.get(best_symbol, 0)
                                time_since_last = current_time - last_signal_time
                                
                                if time_since_last >= TELEGRAM_COOLDOWN_SEC:
                                    telegram_cooldown[best_symbol] = current_time
                                    signal_allowed = True
                                else:
                                    time_left = int(TELEGRAM_COOLDOWN_SEC - time_since_last)
                                    logging.info(f"🏆 НАЙКРАЩИЙ СИГНАЛ ЗАБЛОКОВАНО: {best_symbol} ще {time_left}с кулдауну")
                            
                            if signal_allowed:  # ВІДПРАВЛЯЄМО ТІЛЬКИ ЯКЩО ДОЗВОЛЕНО
                                side = best_data['side']
                                spread = best_data['spread']
                                xt_price = best_data['xt_price']
                                dex_price = best_data['dex_price']
                                token_info = best_data['token_info']
                                
                                # 🛡️ ВЕРИФІКАЦІЯ СИГНАЛУ (як просить користувач - блокуємо без DEX адреси!)
                                try:
                                    from signal_parser import ArbitrageSignal
                                    from signal_verification import verify_arbitrage_signal
                                    from telegram_formatter import format_arbitrage_signal_message
                                    
                                    # Отримуємо clean_symbol для верифікації
                                    clean_symbol = best_symbol.replace('/USDT:USDT', '').replace('1000', '')
                                    
                                    test_signal = ArbitrageSignal(
                                        asset=clean_symbol,
                                        action=side,
                                        spread_percent=spread,
                                        xt_price=xt_price,
                                        dex_price=dex_price,
                                        size_usd=ORDER_AMOUNT,
                                        leverage=LEVERAGE
                                    )
                                    
                                    # КРИТИЧНО: Повна верифікація з блокуванням сигналів без DEX адреси
                                    verification_result = verify_arbitrage_signal(test_signal)
                                    
                                    if verification_result.valid:
                                        # ✅ СИГНАЛ ВАЛІДНИЙ - відправляємо ОБОМ АДМІНАМ + ГРУПІ
                                        logging.info(f"🔍 ВЕРИФІКУЮ СИГНАЛ: {best_symbol} - валідний")
                                        signal_message = format_arbitrage_signal_message(test_signal, verification_result, for_group=False)
                                        send_to_admins_and_group(signal_message)
                                        
                                        logging.info(f"✅ СИГНАЛ ВЕРИФІКОВАНО для {best_symbol}: {side} спред={spread:.2f}% (рейтинг={best_data['score']:.1f})")
                                    else:
                                        # ⚠️ ВІДПРАВЛЯЄМО FALLBACK СИГНАЛ ОБОМ АДМІНАМ + ГРУПІ (як просив користувач - ВСІ сигнали мають відправлятися!)
                                        logging.info(f"⚠️ ВІДПРАВЛЯЄМО FALLBACK СИГНАЛ для {best_symbol}: {'; '.join(verification_result.errors)}")
                                        signal_message = format_arbitrage_signal_message(test_signal, verification_result, for_group=False)
                                        send_to_admins_and_group(signal_message)
                                        
                                except Exception as signal_error:
                                    logging.error(f"❌ Помилка верифікації найкращого сигналу {best_symbol}: {signal_error}")
                                last_best_signal_time = current_time
                            
                            # Очищуємо всі можливості після перевірки (незалежно від відправки)
                            best_opportunities.clear()
                        
            time.sleep(5)  # Перевіряємо кожні 5 секунд
            
        except Exception as e:
            logging.error(f"Помилка в send_best_opportunity_signal: {e}")
            time.sleep(10)

# 🔥 PnL PATCH v2.0 ЗАВЕРШЕНО! 
logging.info("🚀 PnL PATCH v2.0 завершено! Видалено дублікат функції та покращено fallback логіку")

# 🎯 ФУНКЦІЇ ДЛЯ АВТОМАТИЧНОГО ЗАКРИТТЯ ПОЗИЦІЙ

def compute_cross_exchange_spread(position, symbol):
    """📊 Розрахунок поточного спреду між біржами для перевірки конвергенції"""
    try:
        arb_pair = position.get('arb_pair', 'xt-dex')
        
        if arb_pair == 'gate-dex':
            # Gate.io відключена - повертаємо None
            return None, None, None
                
        elif arb_pair == 'xt-dex':
            # Отримуємо поточні ціни XT.com та DEX
            xt_ticker = xt_client.fetch_xt_ticker(xt, symbol) if xt else None
            xt_price = float(xt_ticker['last']) if xt_ticker else None
            
            dex_price = get_dex_price_simple(symbol, for_convergence=True)
            
            if xt_price and dex_price:
                spread_pct = calculate_spread(dex_price, xt_price)
                return abs(spread_pct), xt_price, dex_price
                
        elif arb_pair == 'gate-xt':
            # Gate.io відключена - повертаємо None
            return None, None, None
                
        return None, None, None
        
    except Exception as e:
        logging.error(f"❌ Помилка розрахунку спреду {symbol}: {e}")
        return None, None, None

def gate_close_position_market(symbol, side, size_usdt):
    """🔒 DEPRECATED: Перенаправлено на XT.com (Gate.io видалено)"""
    # 🔒 ПОДВІЙНИЙ ЗАХИСТ: DRY_RUN + ALLOW_LIVE_TRADING
    if DRY_RUN:
        logging.info("[GATE DRY-RUN] close market %s %s %sUSDT", symbol, side, size_usdt)
        return True
    
    if not ALLOW_LIVE_TRADING:
        logging.error("[GATE SECURITY] 🚨 LIVE TRADING BLOCKED: ALLOW_LIVE_TRADING=False")
        return False
    
    try:
        # 🔒 КРИТИЧНО: Отримуємо актуальну позицію з біржі для точного розміру
        try:
            positions = get_xt_open_positions(xt)
            actual_position = None
            
            for pos in positions:
                if pos['symbol'] == symbol and str(pos['side']).upper() == side.upper() and pos['size'] != 0:
                    actual_position = pos
                    break
                    
            if not actual_position:
                logging.error(f"❌ {symbol}: Активна позиція {side} не знайдена на Gate.io")
                return False
                
            # Використовуємо точний розмір позиції з біржі (а не USDT розрахунок)
            contracts = abs(float(actual_position['size']))  # 🔒 КРИТИЧНО: точний розмір з API біржі
            
        except Exception as e:
            logging.error(f"❌ {symbol}: Помилка отримання позиції з XT.com: {e}")
            # FALLBACK: Використовуємо старий метод розрахунку
            ticker = fetch_xt_ticker(xt, symbol)
            if not ticker:
                logging.error(f"❌ Не вдалося отримати ціну для {symbol}")
                return False
            current_price = float(ticker['last'])
            contracts = round(size_usdt / current_price, 6)
        
        if contracts <= 0:
            logging.error(f"❌ {symbol}: Неправильний розмір позиції {contracts}")
            return False
        
        # 🔒 КРИТИЧНО: Нормалізуємо side перед розрахунком close_side
        side = side.upper()  # АРХІТЕКТОР: виправляємо case-sensitivity bug!
        logging.info(f"🔧 {symbol}: Нормалізований side='{side}' для закриття")
        
        # Визначаємо протилежну сторону для закриття  
        close_side = "sell" if side == "LONG" else "buy"
        logging.info(f"🔧 {symbol}: Розраховано close_side='{close_side}' для side='{side}'")
        
        # Створюємо ордер на закриття з reduce-only
        # 🎯 ЗАКРИВАЄМО НА ОБОХ АКАУНТАХ
        result_1 = xt_close_position_market(xt_account_1, symbol, side, size_usdt)
        result_2 = xt_close_position_market(xt_account_2, symbol, side, size_usdt)
        result = result_1 or result_2  # Успішно якщо хоча б один закрився
        if result:
            order = {"id": f"xt-close-{int(time.time())}", "status": "filled"}
            if result_1:
                logging.info(f"✅ АКАУНТ 1: Закрито позицію {symbol} {side}")
            if result_2:
                logging.info(f"✅ АКАУНТ 2: Закрито позицію {symbol} {side}")
        else:
            order = None
        
        if order:
            # 🔧 ДЕТАЛЬНЕ ЛОГУВАННЯ ДЛЯ БЕЗПЕКИ
            logging.info(f"✅ {symbol}: УСПІШНЕ ЗАКРИТТЯ:")
            logging.info(f"   • Side: {side} → Close_side: {close_side}")  
            logging.info(f"   • Contracts: {contracts}")
            logging.info(f"   • Order ID: {order.get('id')}")
            logging.info(f"   • Status: {order.get('status', 'unknown')}")
            return order
        else:
            logging.error(f"❌ {symbol}: ПРОВАЛЕНЕ ЗАКРИТТЯ позиції {side}")
            logging.error(f"   • Side: {side} → Close_side: {close_side}")
            logging.error(f"   • Contracts: {contracts}")
            return False
            
    except Exception as e:
        logging.error(f"❌ {symbol}: Помилка закриття позиції Gate.io: {e}")
        return False

def close_position(symbol, position):
    """🎯 Закриття позиції з правильним API в залежності від біржі"""
    try:
        exchange = position.get('exchange', 'gate')
        side = position.get('side', 'LONG')
        size_usdt = position.get('size_usdt', 0)
        
        logging.warning(f"🔥 CLOSE_POSITION: symbol={symbol}, exchange={exchange}, side={side}, size_usdt={size_usdt}")
        logging.warning(f"🔥 CLOSE_POSITION: xt_account_1={xt_account_1 is not None}, xt_account_2={xt_account_2 is not None}")
        
        # Тільки XT.com (Gate.io видалено) - ЗАКРИВАЄМО НА ОБОХ АКАУНТАХ
        if xt_account_1 and xt_account_2:
            logging.warning(f"🔥 CLOSE_POSITION: Викликаємо xt_close_position_market() для АКАУНТУ 1...")
            result_1 = xt_close_position_market(xt_account_1, symbol, side, size_usdt)
            logging.warning(f"🔥 CLOSE_POSITION: АКАУНТ 1 result={result_1}")
            
            logging.warning(f"🔥 CLOSE_POSITION: Викликаємо xt_close_position_market() для АКАУНТУ 2...")
            result_2 = xt_close_position_market(xt_account_2, symbol, side, size_usdt)
            logging.warning(f"🔥 CLOSE_POSITION: АКАУНТ 2 result={result_2}")
            
            result = result_1 or result_2
            logging.warning(f"🔥 CLOSE_POSITION: Фінальний result={result} (result_1={result_1}, result_2={result_2})")
            
            if result_1:
                logging.info(f"✅ АКАУНТ 1: Закрито {symbol} {side}")
            else:
                logging.error(f"❌ АКАУНТ 1: НЕ ВДАЛОСЯ закрити {symbol} {side}")
            
            if result_2:
                logging.info(f"✅ АКАУНТ 2: Закрито {symbol} {side}")
            else:
                logging.error(f"❌ АКАУНТ 2: НЕ ВДАЛОСЯ закрити {symbol} {side}")
            
            return result
        else:
            logging.error(f"❌ {symbol}: Акаунти XT не доступні (xt_account_1={xt_account_1 is not None}, xt_account_2={xt_account_2 is not None})")
            return False
        
    except Exception as e:
        logging.error(f"❌ {symbol}: Помилка закриття позиції: {e}")
        import traceback
        logging.error(f"❌ {symbol}: Traceback: {traceback.format_exc()}")
        return False

def monitor_open_positions():
    """🎯 МОНІТОРИНГ ПОЗИЦІЙ: Автоматичне закриття при конвергенції цін, +5% прибутку, або 1-годинному таймері"""
    thread_id = threading.current_thread().ident
    logging.warning(f"🎯 MONITOR-{thread_id}: Захищений потік моніторингу позицій запущено!")
    
    while not monitor_stop_event.is_set():
        try:
            positions_to_close = []
            current_time = time.time()
            
            # Копіюємо позиції з захистом від race conditions
            with active_positions_lock:
                current_positions = active_positions.copy()
            
            # Діагностика отримання позицій з обох XT акаунтів
            all_exchange_positions = []
            for account_num, xt_account in [(1, xt_account_1), (2, xt_account_2)]:
                if xt_account:
                    try:
                        raw_positions = xt_account.fetch_positions()
                        xt_positions = xt_client.get_xt_open_positions(xt_account)
                        logging.info(f"🔧 XT АКАУНТ {account_num}: raw_positions={len(raw_positions) if raw_positions else 0}, filtered={len(xt_positions)}")
                        
                        if raw_positions and len(raw_positions) > 0:
                            logging.info(f"📊 XT АКАУНТ {account_num} ПОЗИЦІЙ: {len(raw_positions)} (перші 2):")
                            for i, pos in enumerate(raw_positions[:2]):
                                symbol = pos.get('symbol', '?')
                                size = pos.get('size', 0)
                                contracts = pos.get('contracts', 0)
                                notional = pos.get('notional', 0)
                                logging.info(f"   {i+1}. {symbol}: size={size}, contracts={contracts}, notional={notional}")
                            all_exchange_positions.extend(xt_positions)
                        else:
                            logging.info(f"📊 XT АКАУНТ {account_num}: Немає raw позицій або пустий список")
                            
                    except Exception as e:
                        logging.error(f"❌ XT АКАУНТ {account_num} ДІАГНОСТИКА ПОМИЛКА: {e}")
            
            # 🔥 КРИТИЧНО: Синхронізуємо позиції з обох акаунтів в active_positions
            if all_exchange_positions:
                exchange_positions = all_exchange_positions 
                if exchange_positions:
                    logging.info(f"🔄 СИНХРОНІЗАЦІЯ: Знайдено {len(exchange_positions)} позицій на XT.com")
                    
                    # Додаємо позиції з біржі до активних
                    with active_positions_lock:
                        for pos in exchange_positions:
                            symbol = pos['symbol']
                            side = pos['side'].upper()
                            size = pos.get('size_usdt', pos.get('size', 0))
                            entry_price = pos.get('entryPrice', 0)
                            
                            # Додаємо тільки якщо її немає в active_positions
                            if symbol not in active_positions:
                                current_time = time.time()
                                # 🛡️ ЗАХИСТ: Якщо біржа повертає size=0, використовуємо ORDER_AMOUNT
                                safe_size = abs(size) if abs(size) > 0 else ORDER_AMOUNT
                                logging.info(f"🔧 {symbol}: біржа size={size} → safe_size={safe_size}")
                                active_positions[symbol] = {
                                    'symbol': symbol,
                                    'side': side,
                                    'size_usdt': safe_size,
                                    'avg_entry': entry_price,
                                    'exchange': 'xt',
                                    'status': 'open',
                                    'adds_done': 0,  # 🎯 ВИПРАВЛЕНО: дозволяємо 1 усереднення для синхронізованих позицій
                                    'last_add_time': 0,  # Давній час, щоб cooldown не блокував
                                    'entry_time': current_time,
                                    'opened_at': current_time,  # 🔧 ФІКС ТАЙМЕРА: додано opened_at
                                    'expires_at': current_time + POSITION_MAX_AGE_SEC,  # 🔧 ФІКС ТАЙМЕРА: додано expires_at
                                    'synced_from_exchange': True  # Позначка що це з біржі
                                }
                                logging.info(f"➕ СИНХРОНІЗОВАНО: {symbol} {side} ${size:.2f} від XT.com")
                        
                        # Оновлюємо current_positions після синхронізації
                        current_positions = active_positions.copy()
                        
            logging.info(f"🎯 MONITOR: Перевіряю {len(current_positions)} активних позицій...")
            
            if len(current_positions) == 0:
                time.sleep(30)
                continue
            
            for symbol, position in current_positions.items():
                # Пропускаємо позиції які вже закриваються
                if position.get('status') == 'closing':
                    continue
                
                # 🔧 КРИТИЧНО: СПОЧАТКУ отримуємо поточну ціну для ВСІХ перевірок PnL
                exchange = position.get('exchange', 'gate')
                entry_price = position.get('avg_entry', 0)
                
                # Отримуємо поточну ціну з правильної біржі
                current_price = None
                if exchange == "gate":
                    ticker = fetch_xt_ticker(xt, symbol)
                    current_price = float(ticker['last']) if ticker else None
                elif exchange == "xt" and xt:
                    ticker = xt_client.fetch_xt_ticker(xt, symbol)
                    current_price = float(ticker['last']) if ticker else None
                    
                if not current_price or not entry_price:
                    logging.warning(f"⚠️ [{symbol}] Пропускаємо: current_price={current_price}, entry_price={entry_price}")
                    continue
                
                # 🔧 КРИТИЧНО: Оновлюємо позицію поточною ціною для правильного розрахунку PnL
                position['currentPrice'] = current_price
                position['markPrice'] = current_price
                
                # ⏰ 1. ПЕРЕВІРКА 1-ГОДИННОГО ТАЙМЕРА (НАЙВИЩА ПРІОРИТЕТНІСТЬ)
                if ENABLE_TIME_STOP:
                    expires_at = position.get('expires_at', 0)
                    opened_at = position.get('opened_at', 0)
                    logging.info(f"🔧 ТАЙМЕР DEBUG [{symbol}]: current_time={current_time}, opened_at={opened_at}, expires_at={expires_at}, delta={(current_time - opened_at)/60:.1f}хв")
                    if expires_at > 0 and current_time >= expires_at:
                        time_elapsed = (current_time - position.get('opened_at', current_time)) / 3600
                        reason = f"Time Stop 1h (час: {time_elapsed:.1f}год)"
                        
                        # 🚀 ВИКОРИСТОВУЄМО НОВУ УНІФІКОВАНУ P&L ФУНКЦІЮ
                        pnl_pct = calculate_pnl_percentage(position, use_leverage=True)
                        logging.info(f"⏰ [{symbol}] ТАЙМЕР P&L: {pnl_pct:.2f}%")
                        
                        # 🎯 КРАСИВЕ СПОВІЩЕННЯ ПРО ЗАКРИТТЯ ЗА ТАЙМЕРОМ
                        timer_signal = f"⏰ **ЗАКРИТТЯ ЗА ТАЙМЕРОМ 1 ГОДИНА!**\n"\
                                     f"📊 Символ: **{symbol.replace('/USDT:USDT', '')}** ({position['side']})\n"\
                                     f"💰 Розмір: **${position['size_usdt']:.2f}**\n"\
                                     f"⏱️ Час у позиції: **{time_elapsed:.1f}год** (максимум 1.0год)\n"\
                                     f"💎 P&L: **{pnl_pct:+.1f}%** (${(position['size_usdt'] * pnl_pct / 100):+.2f})\n"\
                                     f"🚪 Автоматичне закриття для управління ризиком\n"\
                                     f"⏰ Час: **{time.strftime('%H:%M:%S %d.%m.%Y')}**"
                        send_to_admins_and_group(timer_signal)
                        
                        positions_to_close.append((symbol, position, reason, pnl_pct))
                        continue  # Переходимо до наступної позиції
                    
                # Перевіряємо мінімальний час утримання позиції
                entry_time = position.get('entry_time', time.time())
                if time.time() - entry_time < MIN_HOLD_SEC:
                    continue
                    
                side = position.get('side', 'LONG').upper()  # 🔒 КРИТИЧНО: нормалізуємо до uppercase
                    
                # 1. ПЕРЕВІРКА TAKE PROFIT (З ЛЕВЕРИДЖЕМ!)
                pnl_pct = calculate_pnl_percentage(position, use_leverage=True)
                
                # 🔍 ДЕТАЛЬНЕ ЛОГУВАННЯ PnL ПЕРЕВІРОК
                logging.info(f"📊 [{symbol}] PnL CHECK: {pnl_pct:+.2f}% | TP={TAKE_PROFIT_PCT}% | SL=-{STOP_LOSS_PCT}%")
                
                if pnl_pct >= TAKE_PROFIT_PCT:
                    logging.info(f"🎯 TP TRIGGERED [{symbol}] PnL={pnl_pct:.2f}% >= +{TAKE_PROFIT_PCT:.2f}% → CLOSE")
                    reason = f"TP +{pnl_pct:.1f}%"
                    positions_to_close.append((symbol, position, reason, pnl_pct))
                    continue
                
                # 1.1 ПЕРЕВІРКА СТОП-ЛОСС (Виправлено на пряме порівняння)
                # Якщо PnL (ROE) менше або дорівнює -10.0% (виправлено з 20% на 10%)
                if pnl_pct <= -STOP_LOSS_PCT:
                    logging.info(f"🚨 SL TRIGGERED [{symbol}] PnL={pnl_pct:.2f}% ≤ -{STOP_LOSS_PCT:.2f}% → CLOSE")
                    reason = f"SL {pnl_pct:.1f}%"
                    positions_to_close.append((symbol, position, reason, pnl_pct))
                    continue
                    
                # 1.2 ПЕРЕВІРКА 50% РУХУ ВІД ПОЧАТКОВОГО СПРЕДУ (Nazir: додано)
                if HALF_MOVE_CLOSE and position.get('entry_spread_pct'):
                    initial_spread_pct = abs(position.get('entry_spread_pct', 0))
                    # Розраховуємо поточний спред
                    spread_result = compute_cross_exchange_spread(position, symbol)
                    if spread_result[0] is not None:
                        current_spread_pct, price1, price2 = spread_result
                        current_spread_pct = abs(current_spread_pct)
                        
                        # Якщо спред зменшився на 50% від початкового
                        half_target = initial_spread_pct * HALF_MOVE_PCT  # 50% від початкового спреду
                        spread_reduction = initial_spread_pct - current_spread_pct
                        
                        if spread_reduction >= half_target:
                            reason = f"50% рух: {initial_spread_pct:.2f}%→{current_spread_pct:.2f}% (-{spread_reduction:.2f}%)"
                            
                            # Повідомлення про 50% рух
                            half_move_signal = f"🎯 **50% РУХ ЦІН!**\n"\
                                             f"📊 Символ: **{symbol.replace('/USDT:USDT', '')}** ({position['side']})\n"\
                                             f"💰 Розмір: **${position['size_usdt']:.2f}**\n"\
                                             f"📈 Початковий спред: **{initial_spread_pct:.2f}%**\n"\
                                             f"📉 Поточний спред: **{current_spread_pct:.2f}%**\n"\
                                             f"⚡ Рух: **-{spread_reduction:.2f}%** (50% досягнуто)\n"\
                                             f"💎 P&L: **{pnl_pct:+.1f}%** (${(position['size_usdt'] * pnl_pct / 100):+.2f})\n"\
                                             f"✨ Ціни зійшлися на 50%! Фіксуємо прибуток\n"\
                                             f"⏰ Час: **{time.strftime('%H:%M:%S %d.%m.%Y')}**"
                            send_to_admins_and_group(half_move_signal)
                            
                            positions_to_close.append((symbol, position, reason, pnl_pct))
                            continue
                    
                # 2. ПЕРЕВІРКА КОНВЕРГЕНЦІЇ ЦІН (DEX конвергенція - повернуто)
                logging.info(f"🎯 MONITOR [{symbol}]: Перевірка DEX конвергенції... CLOSE_ON_CONVERGENCE={CLOSE_ON_CONVERGENCE}")
                if CLOSE_ON_CONVERGENCE:
                    try:
                        spread_result = compute_cross_exchange_spread(position, symbol)
                        logging.info(f"🎯 MONITOR [{symbol}]: Результат спреду: {spread_result}")
                        
                        if spread_result[0] is not None:
                            current_spread_pct, price1, price2 = spread_result
                            logging.info(f"🎯 MONITOR [{symbol}]: Поточний спред: {current_spread_pct:.3f}%, поріг: {CONVERGENCE_SPREAD_PCT}%")
                            
                            if abs(current_spread_pct) <= CONVERGENCE_SPREAD_PCT:
                                reason = f"DEX конвергенція {current_spread_pct:.2f}% ≤ {CONVERGENCE_SPREAD_PCT}%"
                                
                                # 🎯 КРАСИВЕ СПОВІЩЕННЯ ПРО КОНВЕРГЕНЦІЮ ЦІН
                                convergence_signal = f"🎯 **КОНВЕРГЕНЦІЯ ЦІН!**\n"\
                                                    f"📊 Символ: **{symbol.replace('/USDT:USDT', '')}** ({position['side']})\n"\
                                                    f"💰 Розмір: **${position['size_usdt']:.2f}**\n"\
                                                    f"📈 Ціни: Біржа **${price1:.6f}** | Dex **${price2:.6f}**\n"\
                                                    f"📉 Спред: **{abs(current_spread_pct):.2f}%** ≤ {CONVERGENCE_SPREAD_PCT}% (конвергенція)\n"\
                                                    f"💎 P&L: **{pnl_pct:+.1f}%** (${(position['size_usdt'] * pnl_pct / 100):+.2f})\n"\
                                                    f"✨ Ціни зійшлися! Фіксуємо прибуток\n"\
                                                    f"⏰ Час: **{time.strftime('%H:%M:%S %d.%m.%Y')}**"
                                send_to_admins_and_group(convergence_signal)
                                
                                positions_to_close.append((symbol, position, reason, pnl_pct))
                                continue
                        else:
                            logging.warning(f"🎯 MONITOR [{symbol}]: Не вдалося отримати спред для конвергенції")
                    
                    except Exception as e:
                        logging.error(f"🎯 MONITOR [{symbol}]: Помилка при перевірці конвергенції: {e}")
                        # Продовжуємо без конвергенції якщо є помилка з DEX
            
            # Закриваємо позиції які відповідають критеріям
            for symbol, position, reason, pnl_pct in positions_to_close:
                logging.warning(f"🔥 {symbol}: СПРОБА ЗАКРИТТЯ ПОЗИЦІЇ - {reason}")
                logging.warning(f"🔥 {symbol}: position data = {position}")
                
                # Позначаємо як закриття для уникнення повторних спроб
                with active_positions_lock:
                    if symbol in active_positions:
                        active_positions[symbol]['status'] = 'closing'
                        logging.warning(f"🔥 {symbol}: Позначено як 'closing' в active_positions")
                    else:
                        logging.error(f"❌ {symbol}: НЕ ЗНАЙДЕНО в active_positions під час закриття!")
                
                # 🔒 CRITICAL ORDER PLACEMENT LOCK для закриття (Task 6: уникнення конфліктних closes)
                logging.warning(f"🔥 {symbol}: Викликаємо close_position()...")
                with order_placement_lock:
                    result = close_position(symbol, position)
                
                logging.warning(f"🔥 {symbol}: close_position() повернув result={result}")
                
                if result:
                    # Успішне закриття - видаляємо з активних позицій 🔒 THREAD SAFE
                    position_closed = False # <-- Створюємо флаг
                    with active_positions_lock:
                        if symbol in active_positions:
                            del active_positions[symbol]
                            logging.info(f"🗑️ {symbol}: Видалено з active_positions")
                            position_closed = True # <-- Встановлюємо флаг
                            # ⛔️ Виклик save_positions_to_file() ПРИБРАНО ЗВІДСИ
                    
                    # Зберігаємо оновлені позиції ПІСЛЯ звільнення локу
                    if position_closed:
                        save_positions_to_file() # <--- ПЕРЕМІЩЕНО СЮДИ
                        check_and_update_blacklist(symbol, pnl_pct)

                    # ✅ ВІДПРАВЛЯЄМО ПОВІДОМЛЕННЯ ПРО ЗАКРИТТЯ ПОЗИЦІЇ
                    close_signal = f"✅ **ПОЗИЦІЮ ЗАКРИТО!**\n"\
                                  f"📊 Символ: **{symbol.replace('/USDT:USDT', '')}** ({position['side']})\n"\
                                  f"💰 Розмір: **${position['size_usdt']:.2f}**\n"\
                                  f"💎 P&L: **{pnl_pct:+.1f}%** (${(position['size_usdt'] * pnl_pct / 100):+.2f})\n"\
                                  f"📝 Причина: **{reason}**\n"\
                                  f"⏰ Час: **{time.strftime('%H:%M:%S %d.%m.%Y')}**"
                    send_to_admins_and_group(close_signal)
                    
                    logging.info(f"✅ {symbol}: Позицію успішно закрито, P&L={pnl_pct:+.1f}%")
                else:
                    # Помилка закриття - повертаємо статус
                    with active_positions_lock:
                        if symbol in active_positions:
                            active_positions[symbol]['status'] = 'open'
                    logging.error(f"❌ {symbol}: Помилка закриття позиції")
                    
                time.sleep(1)  # Пауза між закриттями
                
        except Exception as e:
            logging.error(f"❌ Помилка в моніторі позицій: {e}")
            
        # Пауза між циклами моніторингу  
        monitor_stop_event.wait(timeout=MONITOR_INTERVAL_SEC)
    
    logging.warning(f"🚨 MONITOR-{thread_id}: Потік моніторингу завершений! (stop_event={monitor_stop_event.is_set()}, bot_running={bot_running})")
    
    # 🧹 CLEANUP: Обнуляємо глобальний референс при завершенні
    global monitor_thread
    monitor_thread = None

# 🚀 НОВІ ФІШКИ: Розумні індикатори для кращої торгівлі
def calculate_volatility_indicator(symbol, exchange="xt"):
    """📊 Індикатор волатільності - аналізує коливання цін за останні 24 години"""
    try:
        if exchange == "xt" and xt:
            ticker_data = xt_client.fetch_xt_ticker(xt, symbol)
        else:
            ticker_data = fetch_ticker(xt, symbol)
            
        if not ticker_data or not ticker_data.get('high') or not ticker_data.get('low'):
            return {"status": "no_data", "volatility": 0}
            
        high_24h = float(ticker_data['high'])
        low_24h = float(ticker_data['low'])
        current_price = float(ticker_data['last'])
        
        # Розраховуємо волатільність як % від поточної ціни
        volatility_pct = ((high_24h - low_24h) / current_price) * 100
        
        # Класифікуємо волатільність
        if volatility_pct < 2:
            risk_level = "LOW"
            quality_score = 8  # Низька волатільність = хороша стабільність
        elif volatility_pct < 5:
            risk_level = "MEDIUM"  
            quality_score = 6
        elif volatility_pct < 10:
            risk_level = "HIGH"
            quality_score = 4
        else:
            risk_level = "EXTREME"
            quality_score = 1  # Висока волатільність = ризиковано
            
        return {
            "status": "success",
            "volatility": round(volatility_pct, 2),
            "risk_level": risk_level,
            "quality_score": quality_score,
            "high_24h": high_24h,
            "low_24h": low_24h
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e), "volatility": 0}

def analyze_volume_quality(symbol, dex_info, exchange="xt"):
    """📈 Аналіз якості об'ємів торгівлі"""
    try:
        if exchange == "xt" and xt:
            ticker_data = xt_client.fetch_xt_ticker(xt, symbol)
        else:
            ticker_data = fetch_ticker(xt, symbol)
            
        if not ticker_data or not ticker_data.get('quoteVolume'):
            return {"status": "no_data", "quality": 0}
            
        # Об'єм біржі за 24 години в USD
        exchange_volume_24h = float(ticker_data['quoteVolume'])
        
        # Об'єм DEX з dex_info
        dex_volume_24h = dex_info.get('volume_24h', 0) if dex_info else 0
        
        # Рахуємо коефіцієнт якості об'єму
        total_volume = exchange_volume_24h + dex_volume_24h
        
        if total_volume < 10000:  # Менше $10K - низька якість
            quality_score = 1
            volume_grade = "POOR"
        elif total_volume < 100000:  # $10K-100K - середня якість
            quality_score = 4
            volume_grade = "FAIR"
        elif total_volume < 1000000:  # $100K-1M - хороша якість  
            quality_score = 7
            volume_grade = "GOOD"
        else:  # Більше $1M - відмінна якість
            quality_score = 10
            volume_grade = "EXCELLENT"
            
        return {
            "status": "success",
            "exchange_volume": exchange_volume_24h,
            "dex_volume": dex_volume_24h,
            "total_volume": total_volume,
            "quality_score": quality_score,
            "grade": volume_grade
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e), "quality": 0}

def smart_entry_timing(symbol, spread_pct, volatility_data, volume_data):
    """⏰ Розумний тайминг входів - визначає оптимальний момент для торгівлі"""
    try:
        timing_score = 0
        reasons = []
        
        # 1. Аналіз спреду - чим більший, тим краще
        if spread_pct >= 3.0:
            timing_score += 40  # Відмінний спред
            reasons.append(f"Відмінний спред {spread_pct}%")
        elif spread_pct >= 2.0:
            timing_score += 25  # Хороший спред
            reasons.append(f"Хороший спред {spread_pct}%")
        elif spread_pct >= 1.0:
            timing_score += 10  # Мінімальний спред
            reasons.append(f"Мінімальний спред {spread_pct}%")
        
        # 2. Волатільність - низька краща для стабільності
        if volatility_data.get("quality_score", 0) >= 6:
            timing_score += 20  # Стабільна волатільність
            reasons.append(f"Стабільна волатільність {volatility_data.get('volatility', 0)}%")
        elif volatility_data.get("quality_score", 0) >= 4:
            timing_score += 10  # Помірна волатільність
            reasons.append(f"Помірна волатільність {volatility_data.get('volatility', 0)}%")
        
        # 3. Об'єм - високий об'єм краще для ліквідності
        volume_score = volume_data.get("quality_score", 0)
        if volume_score >= 7:
            timing_score += 25  # Відмінний об'єм
            reasons.append(f"Високий об'єм ${volume_data.get('total_volume', 0):,.0f}")
        elif volume_score >= 4:
            timing_score += 15  # Середній об'єм
            reasons.append(f"Середний об'єм ${volume_data.get('total_volume', 0):,.0f}")
        
        # 4. ПІДВИЩЕНІ критерії для якісніших сигналів (як просив користувач)
        if timing_score >= 70:
            timing_grade = "PERFECT"  # 70+ = ідеальний момент
            entry_recommendation = "ENTER_NOW"
        elif timing_score >= 50:
            timing_grade = "GOOD"  # 50+ = хороший момент  
            entry_recommendation = "ENTER_SOON"
        elif timing_score >= 20:
            timing_grade = "FAIR"  # 20+ = середній момент
            entry_recommendation = "CONSIDER"
        else:
            # БЛОКУЄМО тільки найгірші < 20 (дозволяємо МАКСИМУМ сигналів!)  
            timing_grade = "BLOCKED"  # Занадто слабкий сигнал
            entry_recommendation = "SKIP_SIGNAL"
            
        return {
            "status": "success",
            "timing_score": timing_score,
            "grade": timing_grade,
            "recommendation": entry_recommendation,
            "reasons": reasons
        }
        
    except Exception as e:
        return {"status": "error", "error": str(e), "timing_score": 0}

def stop_all_workers():
    """Зупинити всіх воркерів"""
    global bot_running, worker_threads, monitor_thread
    logging.warning("🔴 ADMIN STOP: Зупиняю всіх воркерів через адмін-панель...")
    bot_running = False
    
    # 🛡️ THREAD-SAFE STOP: зупиняємо моніторинг через Event
    monitor_stop_event.set()
    
    # Зупиняємо воркерів
    for thread in worker_threads:
        if thread.is_alive():
            thread.join(timeout=2)
    worker_threads.clear()
    
    # 🎯 ROBUST MONITOR STOP: гарантовано очікуємо завершення
    if monitor_thread and monitor_thread.is_alive():
        logging.warning("🎯 Очікую завершення потоку моніторингу...")
        monitor_thread.join(timeout=5)  # Збільшено таймаут
        if monitor_thread.is_alive():
            logging.error("🚨 КРИТИЧНО: Потік моніторингу не завершився за 5 секунд!")
        else:
            logging.info("✅ Потік моніторингу успішно завершено")
            monitor_thread = None  # 🧹 CLEANUP: Обнуляємо референс
    
    logging.warning("🔴 STOP COMPLETED: Всі воркери зупинено")

def restart_workers():
    """Перезапустити всіх воркерів"""
    global bot_running, active_positions
    logging.warning("🔄 ADMIN RESTART: Перезапуск через адмін-панель...")
    stop_all_workers()
    
    with active_positions_lock:  # 🔒 ЗАХИСТ від race conditions
        active_positions.clear()  # Очищаємо старі позиції
        logging.info(f"🗑️ ОЧИЩЕНО: Всі активні позиції видалено з пам'яті!")
    
    # 🛡️ RESET MONITOR EVENT: підготовка до нового старту
    monitor_stop_event.clear()
    logging.info("🔄 RESET: Monitor stop event скинутий для рестарту")
    bot_running = True
    
    logging.warning("🟢 RESTART: Запускаю воркерів та моніторинг...")
    start_workers()
    start_monitor()  # 🎯 Окремий запуск моніторингу

def sync_positions_from_exchange():
    """Синхронізуємо позиції з біржею при старті"""
    global active_positions
    try:
        # 🔧 ВИКОРИСТОВУЄМО XT БІРЖУ для синхронізації позицій
        try:
            logging.info("🔧 [SAFE WRAPPER] Спроба 1: fetch_positions з settle=usdt")
            raw_positions = xt.fetch_positions(['USDT'], {'settle': 'usdt'}) if xt else []
            exchange_positions = raw_positions if raw_positions is not None else []
            active_exchange_positions = [p for p in exchange_positions if float(p.get('contracts', 0) or 0) > 0]
            logging.info(f"✅ Спроба 1 успішна: {len(active_exchange_positions)} активних позицій")
            exchange_positions = active_exchange_positions
        except Exception as e:
            logging.error(f"❌ Помилка отримання позицій з XT для синхронізації: {e}")
            exchange_positions = []
        logging.info(f"🔍 Отримано {len(exchange_positions)} позицій з XT.com API")
        
        # 🚨 АВТООЧИЩЕННЯ: якщо біржа повертає 0 позицій, очищаємо внутрішню пам'ять
        if len(exchange_positions) == 0:
            with active_positions_lock:
                if len(active_positions) > 0:
                    logging.warning(f"🧹 АВТООЧИЩЕННЯ: Біржа показує 0 позицій, очищаємо {len(active_positions)} внутрішніх позицій")
                    active_positions.clear()
                    # Відправляємо Telegram сповіщення про синхронізацію
                    send_to_admins_and_group(
                                f"🧹 **СИНХРОНІЗАЦІЯ ПОЗИЦІЙ**\n"
                                f"Біржа: 0 позицій\n"
                                f"Очищено внутрішню пам'ять\n"
                                f"⏰ {time.strftime('%H:%M:%S')}")
            return 0
        synced_count = 0
        
        with active_positions_lock:  # 🔒 ЗАХИСТ від race conditions
            for i, pos in enumerate(exchange_positions):
                # Додаткове логування для діагностики
                if i < 3:  # показуємо перші 3 позиції для розуміння формату
                    logging.info(f"📊 Позиція {i}: {pos}")
                
                # Безпечне перетворення з захистом від None
                size_raw = pos.get('size', 0)
                contracts_raw = pos.get('contracts', 0)
                
                size = float(size_raw) if size_raw is not None else 0.0
                contracts = abs(float(str(contracts_raw))) if contracts_raw is not None else 0.0
                
                if size > 0 or contracts > 0:  # активна позиція (один з показників)
                    symbol = pos.get('symbol', '')
                    side_value = pos.get('side', '')
                    side = 'LONG' if (side_value and side_value.lower() == 'long') else 'SHORT'
                    # Безпечне отримання entry_price
                    entry_raw = pos.get('entryPrice') or pos.get('entry_price') or pos.get('markPrice') or 0
                    entry_price = float(entry_raw) if entry_raw is not None and str(entry_raw).replace('.','').replace('-','').isdigit() else 0.0
                    
                    # Безпечне отримання notional
                    notional_raw = pos.get('notional') or pos.get('size_usdt') or 0
                    notional = abs(float(notional_raw)) if notional_raw is not None and str(notional_raw).replace('.','').replace('-','').isdigit() else (contracts * entry_price)
                    
                    # 🛡️ ЗАХИСТ: Якщо notional=0, використовуємо ORDER_AMOUNT
                    safe_notional = notional if notional > 0 else ORDER_AMOUNT
                    logging.info(f"🔧 {symbol}: біржа notional={notional} → safe_notional={safe_notional}")
                    
                    # Створюємо агреговану позицію в новому форматі
                    position = {
                        "side": side,
                        "avg_entry": entry_price,
                        "size_usdt": safe_notional,
                        "adds_done": 0,  # біржа не знає скільки усереднень було
                        "last_add_price": entry_price,
                        # ФІКСОВАНА ЦІЛЬ: +30% прибутку з левериджем (як просив користувач)
                        "tp_price": entry_price * (1 + (0.30/LEVERAGE if side == "LONG" else -0.30/LEVERAGE)),  # 30% прибутку з левериджем
                        "last_add_time": 0,  # давно
                        # 🎯 НОВІ ПОЛЯ ДЛЯ АВТОМАТИЧНОГО ЗАКРИТТЯ
                        "entry_time": time.time() - 3600,  # приблизно годину тому (історична позиція)
                        "exchange": "gate",  # біржа на якій відкрита позиція (завжди Gate.io в цій функції)
                        "arb_pair": "gate-dex",  # тип арбітражу (встановлюємо за замовчуванням)
                        "entry_spread_pct": 0.0,  # початковий спред (невідомо для існуючих позицій)
                        "entry_ref_price": entry_price,  # референтна ціна на час входу
                        "status": "open"  # статус позиції (open/closing/closed)
                    }
                    
                    # 🔒 КРИТИЧНО: ЗАВЖДИ зберігаємо існуючі timestamps (НЕ перезаписуємо!)
                    current_time = time.time()
                    existing_position = active_positions.get(symbol, {})
                    
                    # ФІКС БАГУ: ЗАВЖДИ використовуємо існуючі timestamps якщо вони є
                    if existing_position.get('opened_at') and existing_position.get('opened_at') > 0:
                        position['opened_at'] = existing_position['opened_at']  # ЗБЕРІГАЄМО ІСНУЮЧИЙ!
                        logging.info(f"🔧 {symbol}: Збережено існуючий opened_at={existing_position['opened_at']}")
                    else:
                        position['opened_at'] = current_time - 3600  # приблизно годину тому для історичних позицій
                        logging.info(f"🔧 {symbol}: Встановлено новий opened_at={position['opened_at']}")
                    
                    if existing_position.get('expires_at') and existing_position.get('expires_at') > 0:
                        position['expires_at'] = existing_position['expires_at']  # ЗБЕРІГАЄМО ІСНУЮЧИЙ!
                        logging.info(f"🔧 {symbol}: Збережено існуючий expires_at={existing_position['expires_at']}")
                    else:
                        position['expires_at'] = position['opened_at'] + POSITION_MAX_AGE_SEC
                        logging.info(f"🔧 {symbol}: Встановлено новий expires_at={position['expires_at']}")
                    if 'xt_pair_url' not in position:
                        position['xt_pair_url'] = generate_xt_pair_url(symbol)
                    
                    active_positions[symbol] = position  # один запис на символ
                    synced_count += 1
                
        logging.info(f"🔄 Синхронізовано {synced_count} позицій з біржі")
        
        # 💾 ОБОВ'ЯЗКОВО зберігаємо синхронізовані позиції в файл!
        if synced_count > 0:
            save_positions_to_file()
            logging.info(f"💾 Збережено {synced_count} синхронізованих позицій у positions.json")
        
        return synced_count
        
    except Exception as e:
        logging.error(f"Помилка синхронізації позицій: {type(e).__name__}: {e}")
        return 0

def init_markets():
    global markets, trade_symbols, xt, xt_markets_available
    # ❌ GATE.IO ВІДКЛЮЧЕНО за запитом користувача - тільки XT біржа!
    # markets = load_futures_markets(gate)
    markets = {}  # Порожні Gate.io ринки
    
    # 🚀 ТІЛЬКИ XT БІРЖА - ініціалізуємо XT як основну біржу
    try:
        if XT_API_KEY and XT_API_SECRET:
            xt = create_xt()
            xt_markets = load_xt_futures_markets(xt)
            xt_markets_available = True
            logging.info(f"🚀 XT біржа підключена як ЄДИНА біржа: {len(xt_markets)} ринків")
            
            # Використовуємо XT ринки як основні
            markets = xt_markets
            # включаємо за замовчуванням усі XT ринки
            for s in markets.keys():
                trade_symbols[s] = True
                
            logging.info(f"✅ Знайдено {len(markets)} торгових пар на XT біржі")
        else:
            logging.error("❌ XT API ключі відсутні - система НЕ МОЖЕ ПРАЦЮВАТИ!")
            xt_markets_available = False
            raise Exception("XT біржа обов'язкова - встановіть XT_API_KEY та XT_API_SECRET")
    except Exception as e:
        logging.error(f"❌ Помилка ініціалізації XT біржі: {e}")
        xt_markets_available = False
        raise
    
    # 🎯 Нові фішки для кращої торгівлі:
    # 📊 Індикатори волатильності, 📈 Аналіз об'ємів, ⏰ Розумний тайминг
    logging.info("🎯 Активні фішки: волатильність, об'єми, тайминг входів")
    logging.info("🚀 НОВА СИСТЕМА: XT.com vs DEX арбітраж (Gate.io ВІДКЛЮЧЕНО)")
    
    logging.info(f"Увімкнено торгівлю для {len(trade_symbols)} символів на XT біржі")
    
    # Синхронізуємо існуючі позиції з XT біржі
    sync_positions_from_exchange()

def can_execute_on_orderbook(symbol, order_amount_usdt, depth_levels=ORDER_BOOK_DEPTH, max_slippage_pct=1.0, exchange="xt"):
    """
    Перевіряє бічні обсяги в стакані — строга перевірка ліквідності
    """
    try:
        if exchange == "xt" and xt:
            ob = xt_client.fetch_xt_order_book(xt, symbol, depth_levels)
            ticker = xt_client.fetch_xt_ticker(xt, symbol)
        else:
            ob = fetch_order_book(xt, symbol, depth_levels)
            ticker = fetch_xt_ticker(xt, symbol)
        last = ticker['last']
        
        if last is None or not ob or 'asks' not in ob or 'bids' not in ob:
            logging.info(f"[{symbol}] ⚠️ ІНФО: Немає даних order book але продовжуємо торгувати")
            return True
            
        # Перевіряємо asks і bids окремо
        asks_liquidity = 0.0
        bids_liquidity = 0.0
        
        # Рахуємо ліквідність в asks (для LONG позицій)
        for price, vol in ob['asks'][:depth_levels]:
            asks_liquidity += float(price) * float(vol)
            
        # Рахуємо ліквідність в bids (для SHORT позицій)  
        for price, vol in ob['bids'][:depth_levels]:
            bids_liquidity += float(price) * float(vol)
            
        # БЕЗПЕЧНА ПЕРЕВІРКА: потрібно мінімум в 5 разів більше ліквідності ніж сума ордеру (критично для futures!)
        min_required_liquidity = order_amount_usdt * 5
        
        asks_ok = asks_liquidity >= min_required_liquidity
        bids_ok = bids_liquidity >= min_required_liquidity
        
        # ЗАВЖДИ ЛОГУЄМО ІНФОРМАЦІЮ ПРО ЛІКВІДНІСТЬ
        logging.info(f"[{symbol}] 💧 ЛІКВІДНІСТЬ: asks=${asks_liquidity:.2f} bids=${bids_liquidity:.2f} потрібно>${min_required_liquidity:.2f}")
        
        if not (asks_ok and bids_ok):
            logging.warning(f"[{symbol}] ❌ БЛОКОВАНИЙ ВХІД: Недостатня ліквідність asks=${asks_liquidity:.2f} bids=${bids_liquidity:.2f} < ${min_required_liquidity:.2f}")
            # БЛОКУЄМО торгівлю при недостатній ліквідності як просив користувач
            return False
        else:
            logging.info(f"[{symbol}] ✅ ЛІКВІДНІСТЬ ДОСТАТНЯ - торгівля дозволена")
            return True
            
    except Exception as e:
        logging.error(f"[{symbol}] Помилка перевірки ліквідності: {e}")
        return False



def generate_close_signal(symbol, side, close_price, tp_price, open_price):
    """
    Генерує професійне повідомлення про закриття позиції
    """
    from datetime import datetime
    
    # Розрахунок прибутку
    if side == "LONG":
        profit_pct = ((close_price - open_price) / open_price) * 100
    else:
        profit_pct = ((open_price - close_price) / open_price) * 100
    
    profit_color = "🟢" if profit_pct > 0 else "🔴"
    status_emoji = "✅" if profit_pct > 0 else "❌"
    close_reason = "TP ДОСЯГНУТО" if abs(close_price - tp_price) < 0.00001 else "ПОЗИЦІЮ ЗАКРИТО"
    
    current_time = datetime.now().strftime("%H:%M UTC")
    
    close_signal = f"""
{status_emoji} **ПОЗИЦІЮ ЗАКРИТО** {status_emoji}
━━━━━━━━━━━━━━━━━━━━
📍 **{symbol.replace('/USDT:USDT', '')}** | XT.COM FUTURES
📊 **{side}** | {current_time}

💹 **ВХІД:** ${open_price:.6f}
🏁 **ВИХІД:** ${close_price:.6f}
🎯 **TP:** ${tp_price:.6f}

{profit_color} **РЕЗУЛЬТАТ:** {profit_pct:+.2f}%
📋 **СТАТУС:** {close_reason}

━━━━━━━━━━━━━━━━━━━━
⚡ XT.COM Arbitrage Bot
🤖 Автозакриття позиції
"""
    return close_signal

def open_market_position(symbol, side, usd_amount, leverage, gate_price_ref=None, dex_price_ref=None, spread_ref=None, account_num=1):
    """
    Proxy function to XT.com - replaced Gate.io with XT.com
    Підтримує обидва акаунти через параметр account_num
    """
    # Вибираємо акаунт для торгівлі
    xt_client = xt_account_1 if account_num == 1 else xt_account_2
    return xt_open_market_position(xt_client, symbol, side, usd_amount, leverage, gate_price_ref, dex_price_ref, spread_ref)

def close_position_market(symbol, side, usd_amount, account_num=1):
    """
    Proxy function to XT.com - replaced Gate.io with XT.com
    Підтримує обидва акаунти через параметр account_num
    """
    # Вибираємо акаунт для закриття
    xt_client = xt_account_1 if account_num == 1 else xt_account_2
    return xt_close_position_market(xt_client, symbol, side, usd_amount)

def symbol_worker(symbol):
    """
    Робота по одному символу з усередненням позицій: fetch ticker, dex price via dexscreener, calc spread, check liquidity, open/average/close
    (ОДИН ПРОХІД ЗАМІСТЬ ЦИКЛУ)
    """
    # 🔥 ДОДАНО: Перевірка Чорного Списку
    with blacklist_lock:
        if symbol in blacklist_data["banned_symbols"]:
            logging.debug(f"[{symbol}] ⛔ Пропускаємо (в чорному списку)")
            return

    logging.info(f"Worker starting for {symbol}") # ⬅️ ЗМІНЕНО: логування старту
    # ⛔️ ВИДАЛЕНО: while bot_running:
    try:
        if not trade_symbols.get(symbol, False):
            # time.sleep(1) # ⛔️ ВИДАЛЕНО
            logging.debug(f"[{symbol}] Торгівля вимкнена, воркер завершує роботу.")
            return  # ⬅️ ЗМІНЕНО: з continue на return

        # 1) ТІЛЬКИ XT БІРЖА - отримуємо ціну з XT (як просив користувач)
        xt_price = None
        if not (xt_markets_available and xt):
            logging.debug(f"[{symbol}] ❌ XT біржа недоступна")
            return  # ⬅️ ЗМІНЕНО: з continue на return
            
        try:
            xt_price = get_xt_price(xt, symbol)
            if not xt_price or not is_xt_futures_tradeable(symbol):
                logging.debug(f"[{symbol}] ❌ Неможливо торгувати на XT futures")
                return  # ⬅️ ЗМІНЕНО: з continue на return
            logging.debug(f"[{symbol}] ✅ XT ціна: ${xt_price:.6f}")
        except Exception as e:
            logging.debug(f"[{symbol}] ⚠️ XT ціна недоступна: {e}")
            return  # ⬅️ ЗМІНЕНО: з continue на return

        # 2) ТІЛЬКИ ТОДІ DexScreener - отримуємо РОЗШИРЕНІ МЕТРИКИ
        try:
            # 🔬 РОЗШИРЕНИЙ АНАЛІЗ: ліквідність, FDV, market cap, транзакції, покупці/продавці
            advanced_metrics = get_advanced_token_analysis(symbol)
            if not advanced_metrics:
                logging.debug(f"[{symbol}] ❌ Немає якісної пари на DexScreener")
                return  # ⬅️ ЗМІНЕНО: з continue на return
                
            # Отримуємо базові дані (backward compatibility)
            token_info = {
                'price_usd': advanced_metrics.get('price_usd', 0),
                'liquidity': advanced_metrics.get('liquidity', 0),
                'volume_24h': advanced_metrics.get('volume_24h', 0),
                'dex_link': advanced_metrics.get('exact_pair_url') or get_proper_dexscreener_link(symbol)
            }
            
            # Коротка інформація про токен (зменшено логування)
            logging.info(f"📊 {symbol}: ${advanced_metrics.get('price_usd', 0):.6f} | Vol ${advanced_metrics.get('volume_1h', 0):,.0f}")
                
            if not token_info:
                logging.debug(f"[{symbol}] ❌ Немає якісної пари на DexScreener")
                return  # ⬅️ ЗМІНЕНО: з continue на return
            
            dex_price = token_info['price_usd']
            
            # ЖОРСТКІ ПЕРЕВІРКИ (як у топових арбітражних ботів)
            if not dex_price or dex_price < 0.000001:  # мінімальна ціна $0.000001
                raise Exception(f"Invalid DexScreener price: {dex_price}")
                
        except Exception as e:
            # БЛОКУЄМО токени з поганими DexScreener цінами - як у друга з Bybit
            logging.warning(f"[{symbol}] ❌ Пропускаємо через погану DexScreener ціну: {e}")
            return  # ⬅️ ЗМІНЕНО: з continue на return

        # 3) ТІЛЬКИ XT vs DexScreener АРБІТРАЖ (Gate.io ВІДКЛЮЧЕНО)
        if not xt_price:
            logging.debug(f"[{symbol}] ❌ XT ціна недоступна")
            return  # ⬅️ ЗМІНЕНО: з continue на return
            
        # Розраховуємо спред XT vs DexScreener
        xt_dex_spread = calculate_spread(dex_price, xt_price)
        best_spread = xt_dex_spread
        best_direction = "LONG" if xt_price < dex_price else "SHORT" 
        best_exchange_pair = "XT vs Dex"
        trading_exchange = "xt"  # ЗАВЖДИ торгуємо на XT
        ref_price = xt_price  # ВИПРАВЛЕНО: XT ціна для XT біржі
        
        spread_pct = best_spread
        spread_store.append(spread_pct)
        
        # Покращене логування тільки з XT та DexScreener
        clean_symbol = symbol.replace('/USDT:USDT', '')
        log_info = f"XT: ${xt_price:.6f} | Dex: ${dex_price:.6f} | Спред: {best_spread:.2f}% {best_direction} | Торгуємо на: XT"
        logging.info(f"[{clean_symbol}] {log_info}")
        
        # 🚀 НОВІ ФІШКИ: Розумна аналітика ПІСЛЯ встановлення trading_exchange
        volatility = calculate_volatility_indicator(symbol, trading_exchange)
        volume_analysis = analyze_volume_quality(symbol, token_info, trading_exchange)
        smart_timing = smart_entry_timing(symbol, abs(spread_pct), volatility, volume_analysis)
        
        # Логування нових фішок
        # Аналіз якості токена (логування зменшено)
        if volatility.get('status') == 'success' and smart_timing.get('status') == 'success':
            logging.info(f"[{clean_symbol}] 📊 Волатільність: {volatility['volatility']}% | Тайминг: {smart_timing['grade']}")
        
        # ✅ ПОВНА АВТОМАТИЗАЦІЯ - БЕЗ БЛОКИРОВОК!
        enhanced_entry_check = True
        
        # Інформаційні повідомлення (БЕЗ БЛОКУВАННЯ!)
        # Попередження тільки для критичних випадків
        if volatility.get('risk_level') == 'EXTREME' and volatility.get('volatility', 0) > 30:
            logging.info(f"[{clean_symbol}] ⚠️ Висока волатільність {volatility.get('volatility', 0)}% - торгуємо обережно")
        
        # НЕ спамимо про кожну арбітражну можливість - тільки про реальні торгові операції

        # 3) Перевірка балансу перед торгівлею
        # МАРЖА ЗА НАЛАШТУВАННЯМ (збільшено для торгівлі дорожчими токенами)
        required_margin = float(ORDER_AMOUNT)  # Примусове приведення до float
        
        # 🔒 THREAD-SAFE БАЛАНС (Task 6: захист від одночасних перевірок балансу)
        try:
            with balance_check_lock:  # ЗАХИСТ: тільки один worker перевіряє баланс одночасно
                # Видалено DEBUG логування для чистоти
                
                # ✅ ТІЛЬКИ XT.COM БІРЖА - ОБИДВА АКАУНТИ
                if trading_exchange == "xt":
                    # Баланс акаунта 1
                    balance_1 = get_xt_futures_balance(xt_account_1)
                    available_balance_1 = float(balance_1.get('free', 0.0))
                    # Баланс акаунта 2
                    balance_2 = get_xt_futures_balance(xt_account_2)
                    available_balance_2 = float(balance_2.get('free', 0.0))
                    # Загальний доступний баланс
                    available_balance = available_balance_1 + available_balance_2
                    logging.info(f"💰 XT.com АКАУНТ 1: ${balance_1['total']:.2f} USDT (доступно ${available_balance_1:.2f})")
                    logging.info(f"💰 XT.com АКАУНТ 2: ${balance_2['total']:.2f} USDT (доступно ${available_balance_2:.2f})")
                    logging.info(f"💰 ЗАГАЛОМ: ${balance_1['total'] + balance_2['total']:.2f} USDT (доступно ${available_balance:.2f})")
                else:
                    # Якщо trading_exchange не XT - пропускаємо
                    logging.warning(f"[{symbol}] ⚠️ Підтримуємо тільки XT біржу, пропускаємо: {trading_exchange}")
                    return  # ⬅️ ЗМІНЕНО: з continue на return
                    
                # Детальне логування умов торгівлі
                spread_check = MIN_SPREAD <= abs(spread_pct) <= MAX_SPREAD
                balance_check = available_balance >= required_margin
                
                # 🔒 Перевірка кількості активних позицій з ЗАХИСТОМ (поза balance_check_lock)
                with active_positions_lock:
                    total_positions = len(active_positions)
                    has_position = symbol in active_positions
                positions_check = total_positions < MAX_OPEN_POSITIONS
            
            
            # 🔥 ПОКРАЩЕНІ ФІЛЬТРИ РЕАЛЬНОСТІ - відсіюємо фейкові арбітражі!
            is_realistic = True
            
            # 1. РОЗУМНИЙ спред фільтр: різні ліміти для різних монет
            clean_symbol = symbol.replace('/USDT:USDT', '')
            
            # Основні монети (ETH, BTC тощо) - більш жорсткі ліміти
            major_tokens = ['ETH', 'BTC', 'BNB', 'ADA', 'SOL', 'MATIC', 'AVAX', 'DOT', 'LINK']
            max_spread_limit = 50.0  # ПОЛІПШЕНО: максимум 50% для блокування фейків
            
            # ЖОРСТКА перевірка фейкових спредів  
            if abs(spread_pct) > max_spread_limit:
                logging.warning(f"[{symbol}] ❌ ФЕЙК: Нереальний спред {spread_pct:.2f}% > {max_spread_limit}%")
                is_realistic = False
            
            # БЛОКУВАННЯ НЕГАТИВНИХ СПРЕДІВ (очевидні фейки)
            if spread_pct < -25.0:  # Негативні спреди більше -25% завжди фейкові  
                logging.warning(f"[{symbol}] ❌ ФЕЙК: Негативний спред {spread_pct:.2f}% заблоковано")
                is_realistic = False
            
            # 2. РОЗСЛАБЛЕНА перевірка співвідношення цін для більше можливостей
            price_ratio = max(xt_price, dex_price) / min(xt_price, dex_price)
            max_price_ratio = 2.5  # РОЗСЛАБЛЕНО: 2.5x для всіх монет для більше сигналів
            
            if price_ratio > max_price_ratio:
                logging.warning(f"[{symbol}] ❌ ФЕЙК: Ціни відрізняються в {price_ratio:.2f} разів (макс. {max_price_ratio:.1f}x)")
                is_realistic = False
            
            # 3. АБСОЛЮТНА перевірка цін для топ-монет (як ETH $3701 vs $4601)  
            if clean_symbol in major_tokens:
                # Перевіряємо що цінди в розумних межах для топ-монет
                expected_ranges = {
                    'ETH': (2000, 6000),    # ETH очікується $2000-6000
                    'BTC': (30000, 100000), # BTC очікується $30k-100k  
                    'BNB': (200, 1000),     # BNB очікується $200-1000
                    'SOL': (50, 500),       # SOL очікується $50-500
                    'ADA': (0.2, 3.0),      # ADA очікується $0.2-3.0
                }
                
                if clean_symbol in expected_ranges:
                    min_price, max_price = expected_ranges[clean_symbol]
                    if not (min_price <= xt_price <= max_price) or not (min_price <= dex_price <= max_price):
                        logging.warning(f"[{symbol}] ❌ ФЕЙК: Ціна поза межами для {clean_symbol}: XT=${xt_price:.2f}, Dex=${dex_price:.2f} (очікується ${min_price}-${max_price})")
                        is_realistic = False
            
            # 4. ЖОРСТКІ ФІЛЬТРИ: Мінімальна ліквідність та обсяг для торгівлі (як просив користувач)
            min_liquidity = token_info.get('liquidity', 0)
            min_volume_24h = token_info.get('volume_24h', 0)
            
            if min_liquidity < MIN_POOLED_LIQUIDITY_USD:  # ФІЛЬТР з config.py
                logging.warning(f"[{symbol}] ❌ ФЕЙК: Мала ліквідність ${min_liquidity:,.0f} < ${MIN_POOLED_LIQUIDITY_USD:,}")
                is_realistic = False
                
            if min_volume_24h < MIN_24H_VOLUME_USD:  # ФІЛЬТР з config.py
                logging.warning(f"[{symbol}] ❌ ФЕЙК: Малий обсяг ${min_volume_24h:,.0f} < ${MIN_24H_VOLUME_USD:,}")
                is_realistic = False
            
            # 5. Перевіряємо що це не стейблкоїн або заблоковані токени
            blacklisted_tokens = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'TON']
            if any(token in clean_symbol for token in blacklisted_tokens):
                logging.info(f"[{symbol}] ❌ ЗАБЛОКОВАНО: Токен {clean_symbol} в чорному списку")
                is_realistic = False
            
            # 6. ДОДАТКОВО: Перевірка кратності цін (виявляє деякі фейки)
            if xt_price > 0 and dex_price > 0:
                # Якщо одна ціна є точним кратним іншої (x10, x100), це може бути помилка
                ratio_check = xt_price / dex_price
                if abs(ratio_check - round(ratio_check)) < 0.01 and round(ratio_check) >= 10:
                    logging.warning(f"[{symbol}] ❌ ФЕЙК: Підозрюване кратне співвідношення цін {ratio_check:.1f}x")
                    is_realistic = False
            
            # АВТОСИГНАЛИ: Окремі сигнали для кожної пари бірж >= MIN_SPREAD
            
            # Логування нових фішок
            if volatility.get('status') == 'success':
                # Компактний звіт якості (зменшено логування)
                if volatility.get('status') == 'success' and volume_analysis.get('status') == 'success':
                    logging.info(f"[{symbol}] 📊 Vol: {volatility['volatility']}% | Об'єм: ${volume_analysis['total_volume']:,.0f} | Тайминг: {smart_timing.get('grade', 'N/A')}")
            
            # Підвищуємо вимоги до входу на основі нових фішок
            enhanced_entry_check = True
            
            # 🎯 ДОЗВОЛЕНО: Блокування тільки найгірших сигналів (дозволяємо FAIR тайминг)
            timing_recommendation = smart_timing.get('recommendation', 'WAIT')
            if timing_recommendation in ['SKIP_SIGNAL']:  # Тільки SKIP_SIGNAL, WAIT/CONSIDER дозволені
                logging.warning(f"[{symbol}] ❌ БЛОКОВАНИЙ СИГНАЛ: таймінг {smart_timing.get('grade')} ({smart_timing.get('timing_score', 0)} балів)")
                enhanced_entry_check = False  # БЛОКУЄМО тільки найгірші сигнали
            
            # Блокуємо при екстремальній волатильності
            if volatility.get('risk_level') == 'EXTREME':
                logging.info(f"[{symbol}] 📊 ІНФО: Висока волатільність {volatility.get('volatility', 0)}% але торгуємо далі")
                # БЕЗ БЛОКУВАННЯ enhanced_entry_check залишається True
            
            # Блокуємо при низькому об'ємі
            if volume_analysis.get('quality_score', 0) <= 1:
                logging.warning(f"[{symbol}] 📈 БЛОКОВАНО: Занадто низький об'єм ${volume_analysis.get('total_volume', 0):,.0f}")
                enhanced_entry_check = False
            
            # 🛡️ ПЕРЕВІРЯЄМО ІСНУЮЧІ ПОЗИЦІЇ ПЕРЕД ВІДПРАВКОЮ СИГНАЛІВ
            with active_positions_lock:
                already_has_position = symbol in active_positions

            # 🎯 НОВА ЛОГІКА: ЗБИРАЄМО МОЖЛИВОСТІ БЕЗ БАЛАНСОВИХ ОБМЕЖЕНЬ ДЛЯ НАЙКРАЩИХ СИГНАЛІВ
            logging.info(f"🔍 ПЕРЕВІРКА СИГНАЛУ {symbol}: realistic={is_realistic}, entry_check={enhanced_entry_check}, has_position={already_has_position}")
            if is_realistic and enhanced_entry_check and not already_has_position:
                # 1. XT vs DexScreener (ТІЛЬКИ XT БІРЖА)
                xt_dex_spread_pct = calculate_spread(dex_price, xt_price)
                if MIN_SPREAD <= abs(xt_dex_spread_pct) <= MAX_SPREAD:
                    # ✅ Перевіряємо ліміт відкритих позицій
                    with active_positions_lock:
                        current_positions = len(active_positions)

                    if current_positions >= MAX_OPEN_POSITIONS:
                        logging.warning(f"[{symbol}] 🚫 Досягнуто максимум відкритих позицій ({current_positions}/{MAX_OPEN_POSITIONS}) — пропускаємо сигнал")
                        return  # або continue, якщо всередині циклу
                    
                    current_time = time.time()
                    logging.info(f"🔥 СИГНАЛ ЗНАЙДЕНО: {symbol} спред={xt_dex_spread_pct:.2f}% (мін={MIN_SPREAD}%, макс={MAX_SPREAD}%)")
                    
                    # 🎯 ЗБИРАЄМО ДЛЯ НАЙКРАЩИХ СИГНАЛІВ (БЕЗ КУЛДАУН ПЕРЕВІРКИ ТУТ)
                    # side = "LONG" if xt_dex_spread_pct > 0 else "SHORT"
                    side = "LONG" if xt_price < dex_price else "SHORT"
                    
                    # Розраховуємо рейтинг можливості для пошуку найкращого
                    liquidity = advanced_metrics.get('liquidity', 0)
                    volume_24h = advanced_metrics.get('volume_24h', 0) 
                    score = abs(xt_dex_spread_pct) * 100 + (liquidity / 1000) + (volume_24h / 10000)
                    
                    # ✅ ДОДАЄМО В СИСТЕМУ НАЙКРАЩИХ МОЖЛИВОСТЕЙ (БЕЗ БАЛАНСОВИХ ОБМЕЖЕНЬ)
                    with opportunities_lock:
                        best_opportunities[symbol] = {
                            'spread': xt_dex_spread_pct,
                            'side': side,
                            'score': score,
                            'timestamp': current_time,
                            'xt_price': xt_price,
                            'dex_price': dex_price,
                            'token_info': token_info,
                            'advanced_metrics': advanced_metrics
                        }
                    
                    logging.info(f"[{symbol}] 🏆 ДОДАНО ДО НАЙКРАЩИХ: {side} спред={xt_dex_spread_pct:.2f}% (рейтинг={score:.1f})")
                    
                    # 🚨 НОВА ЛОГІКА: НЕГАЙНЕ ВІДПРАВЛЕННЯ СИГНАЛУ НЕЗАЛЕЖНО ВІД БАЛАНСУ!
                    # Відправляємо сигнал одразу після знаходження можливості (тільки з кулдауном)
                    signal_sent = False
                    
                    with telegram_cooldown_lock:  # КРИТИЧНА СЕКЦІЯ
                        last_signal_time = telegram_cooldown.get(symbol, 0)
                        time_since_last = current_time - last_signal_time
                        
                        if time_since_last >= TELEGRAM_COOLDOWN_SEC:
                            signal_sent = True
                            
                            # 🛡️ ВЕРИФІКАЦІЯ СИГНАЛУ (як просить користувач - блокуємо без DEX адреси!)
                            logging.info(f"🔍 ВЕРИФІКУЮ СИГНАЛ: {symbol} {side} спред={xt_dex_spread_pct:.2f}%")
                            
                            try:
                                # Створюємо ArbitrageSignal об'єкт для верифікації
                                from signal_parser import ArbitrageSignal
                                from signal_verification import verify_arbitrage_signal
                                from telegram_formatter import format_arbitrage_signal_message
                                
                                test_signal = ArbitrageSignal(
                                    asset=clean_symbol,
                                    action=side,
                                    spread_percent=xt_dex_spread_pct,
                                    xt_price=xt_price,
                                    dex_price=dex_price
                                )
                                
                                # КРИТИЧНО: Повна верифікація з блокуванням сигналів без DEX адреси
                                verification_result = verify_arbitrage_signal(test_signal)
                                
                                if verification_result.valid:
                                    # ✅ СИГНАЛ ВАЛІДНИЙ - відправляємо з повною інформацією
                                    signal_message = format_arbitrage_signal_message(test_signal, verification_result)
                                    logging.info(f"✅ СИГНАЛ ВЕРИФІКОВАНО для {symbol}: DEX знайдено!")
                                else:
                                    # 🔄 СИГНАЛ НЕ ВЕРИФІКОВАНО - відправляємо з fallback посиланням
                                    logging.info(f"⚠️ ВІДПРАВЛЯЄМО FALLBACK СИГНАЛ для {symbol}: {'; '.join(verification_result.errors)}")
                                    signal_message = format_arbitrage_signal_message(test_signal, verification_result, for_group=True)
                                    # НЕ блокуємо відправку - відправляємо з fallback посиланнями!
                                
                            except Exception as signal_error:
                                logging.error(f"❌ Помилка верифікації сигналу {symbol}: {signal_error}")
                                signal_sent = False
                                signal_message = None
                    
                    # 📱 ВІДПРАВЛЕННЯ В TELEGRAM (ПОЗА ЛОКОМ) - ТІЛЬКИ ВАЛІДНІ СИГНАЛИ!
                    signal_message = locals().get('signal_message', None)
                    if signal_sent and signal_message:
                        try:
                            # 🎯 ТОРГОВІ СИГНАЛИ ОБОМ АДМІНАМ + ГРУПІ
                            success2 = send_to_admins_and_group(signal_message)
                            
                            if success2:
                                # ТІЛЬКИ ПІСЛЯ УСПІШНОЇ ВІДПРАВКИ встановлюємо кулдаун
                                with telegram_cooldown_lock:
                                    telegram_cooldown[symbol] = current_time
                                logging.info(f"📱 СИГНАЛ ВІДПРАВЛЕНО: {symbol} {side} спред={xt_dex_spread_pct:.2f}% (ігноруємо баланс)")
                            else:
                                logging.error(f"❌ Помилка відправки в обидва чати {symbol}")
                                
                        except Exception as telegram_error:
                            logging.error(f"❌ Помилка Telegram відправки {symbol}: {telegram_error}")
                    
                    # Показуємо кулдаун якщо сигнал заблокований
                    if not signal_sent:
                        with telegram_cooldown_lock:
                            last_signal_time = telegram_cooldown.get(symbol, 0)
                            time_since_last = current_time - last_signal_time
                            if time_since_last < TELEGRAM_COOLDOWN_SEC:
                                time_left = int(TELEGRAM_COOLDOWN_SEC - time_since_last)
                                logging.info(f"[{symbol}] ⏰ КУЛДАУН: ще {time_left}с до наступного сигналу")
                    
                    # 🔄 СТАРА ЛОГІКА: Тільки для безпосереднього торгування (з балансовими обмеженнями)
                    # ПРИМУСОВА МАРЖА $5: купуємо частково для будь-якої монети  
                    # Завжди торгуємо на ФІКСОВАНУ маржу $5.00 (можна купити частину монети)
                    
                    time.sleep(5) # ⬅️ ЗМІНЕНО: Це було у вас в коді, я залишив. Можливо, це для rate-limit? Якщо ні, можна прибрати.
                
                # 2. XT vs DexScreener (якщо XT доступна)
                if xt_price:
                    xt_dex_spread_pct = calculate_spread(dex_price, xt_price)
                    if MIN_SPREAD <= abs(xt_dex_spread_pct) <= MAX_SPREAD:
                        # ПРИМУСОВА МАРЖА $5: купуємо частково для будь-якої монети
                        # Завжди торгуємо на ФІКСОВАНУ маржу $5.00 (можна купити частину монети)
                        # 🕒 THREAD-SAFE КУЛДАУН: синхронізація для багатопоточності
                        current_time = time.time()
                        signal_sent = False
                        
                        with telegram_cooldown_lock:  # КРИТИЧНА СЕКЦІЯ  
                            last_signal_time = telegram_cooldown.get(symbol, 0)
                            time_since_last = current_time - last_signal_time
                            
                            if time_since_last >= TELEGRAM_COOLDOWN_SEC:
                                telegram_cooldown[symbol] = current_time  # Одразу встановлюємо час
                                signal_sent = True
                            else:
                                time_left = int(TELEGRAM_COOLDOWN_SEC - time_since_last)
                                logging.info(f"[{symbol}] ⏰ СПІЛЬНИЙ КУЛДАУН: ще {time_left}с до наступного сигналу")
                        
                        # 🎯 ВИДАЛЕНО ДУБЛІКАТ: цей блок дублював логіку з рядків вище
                        # Залишаємо тільки систему найкращих сигналів
                    
                    # ВИДАЛЕНО: міжбіржовий арбітраж Gate ↔ XT (залишаємо тільки DEX порівняння)
            elif already_has_position:
                logging.info(f"[{symbol}] ⏹️ ПРОПУСКАЄМО СИГНАЛ: вже є активна позиція")
            elif abs(spread_pct) >= MIN_SPREAD and not is_realistic:
                logging.warning(f"[{symbol}] ❌ БЛОКОВАНИЙ ФЕЙК: спред={spread_pct:.2f}%")
            
            # РЕАЛЬНА ТОРГІВЛЯ З УСЕРЕДНЕННЯМ
            if spread_check and balance_check and not DRY_RUN and is_realistic:
                side = "LONG" if spread_pct > 0 else "SHORT"
                
                # Логіка базового входу або усереднення
                if not has_position and positions_check:
                    # БАЗОВИЙ ВХІД: Відкриваємо нову позицію
                    logging.info(f"[{symbol}] 🎯 БАЗОВИЙ ВХІД: spread={abs(spread_pct):.3f}% >= {MIN_SPREAD}%, баланс={available_balance:.4f} >= {required_margin:.4f}, позицій={total_positions} < {MAX_OPEN_POSITIONS}")

                    # СТРОГА перевірка order book ліквідності з правильної біржі
                    ok_liq = can_execute_on_orderbook(symbol, ORDER_AMOUNT, ORDER_BOOK_DEPTH, exchange=trading_exchange)
                    
                    # 🔍 ДОДАТКОВА ПЕРЕВІРКА XT order book ліквідності (спеціальна для XT.com)
                    if ok_liq and trading_exchange == "xt":
                        # ВИПРАВЛЕНО: використовуємо notional size (маржа * леверидж) замість тільки маржі
                        notional_size = ORDER_AMOUNT * LEVERAGE
                        current_side = "LONG" if spread_pct > 0 else "SHORT"  # Явно визначаємо side
                        can_trade_xt, xt_liquidity_info = analyze_xt_order_book_liquidity(xt, symbol, current_side, notional_size, min_liquidity_ratio=2.0)
                        if not can_trade_xt:
                            logging.warning(f"[{symbol}] {xt_liquidity_info}")
                            ok_liq = False
                        else:
                            logging.info(f"[{symbol}] {xt_liquidity_info}")

                    if ok_liq:
                        # ПРИМУСОВЕ встановлення левериджу ПЕРЕД кожною угодою
                        if trading_exchange == "xt":
                            # 🔥 ДОДАНО: Встановлення ІЗОЛЬОВАНОЇ МАРЖІ
                            try:
                                # Спробуємо встановити isolated маржу. 
                                # Це може викликати помилку, якщо позиція вже відкрита або режим вже встановлено, тому try/except
                                xt.set_margin_mode('isolated', symbol)
                                logging.info(f"[{symbol}] 🛡️ XT: Режим маржі переключено на ISOLATED")
                            except Exception as e:
                                # Ігноруємо помилку, якщо режим вже стоїть правильний, або просто логуємо як warning
                                logging.warning(f"[{symbol}] ⚠️ Не вдалося явно встановити ISOLATED (можливо вже активно або є відкриті ордери): {e}")

                            try:
                                # Правильний виклик з positionSide
                                position_side = "LONG" if side == "LONG" else "SHORT"
                                xt.set_leverage(LEVERAGE, symbol, {"positionSide": position_side})
                                logging.info(f"[{symbol}] ⚙️ XT: ПРИМУСОВО встановлено леверидж {LEVERAGE}x ({position_side})")
                            except Exception as e:
                                logging.error(f"[{symbol}] ❌ Помилка встановлення левериджу XT: {e}")
                                pass

                    
                    # if ok_liq:
                    #     # ПРИМУСОВЕ встановлення левериджу ПЕРЕД кожною угодою
                    #     if trading_exchange == "xt":
                    #         try:
                    #             # Правильний виклик з positionSide
                    #             position_side = "LONG" if side == "LONG" else "SHORT"
                    #             xt.set_leverage(LEVERAGE, symbol, {"positionSide": position_side})
                    #             logging.info(f"[{symbol}] ⚙️ XT: ПРИМУСОВО встановлено леверидж {LEVERAGE}x ({position_side})")
                    #         except Exception as e:
                    #             logging.error(f"[{symbol}] ❌ Помилка встановлення левериджу XT: {e}")
                    #             # Не блокуємо торгівлю, продовжуємо
                    #             pass
                                
                            # 🔒 ORDER PLACEMENT LOCK (Task 6: запобігаємо подвійним ордерам)
                            with order_placement_lock:
                                # 🎯 ПАРАЛЕЛЬНА ТОРГІВЛЯ НА ДВОХ АКАУНТАХ
                                order_account_1 = xt_open_market_position(xt_account_1, symbol, side, ORDER_AMOUNT, LEVERAGE, ref_price, dex_price, spread_pct)
                                order_account_2 = xt_open_market_position(xt_account_2, symbol, side, ORDER_AMOUNT, LEVERAGE, ref_price, dex_price, spread_pct)
                                # Вважаємо успішним якщо хоча б один акаунт відкрив позицію
                                order = order_account_1 or order_account_2
                                if order_account_1:
                                    logging.info(f"[{symbol}] ✅ АКАУНТ 1: Відкрито {side} позицію з левериджем {LEVERAGE}x")
                                if order_account_2:
                                    logging.info(f"[{symbol}] ✅ АКАУНТ 2: Відкрито {side} позицію з левериджем {LEVERAGE}x")
                        else:
                            order = None
                        if order:
                                logging.info(f"[{symbol}] 🚀 XT: Відкрито {side} позиції на обох акаунтах з левериджем {LEVERAGE}x")
                        # ❌ GATE.IO ВІДКЛЮЧЕНО - тільки XT біржа!
                        # else:  # gate (ВІДКЛЮЧЕНО)
                        #     order = open_market_position(symbol, side, ORDER_AMOUNT, LEVERAGE, gate_price, dex_price, spread_pct)
                        if order:
                            # Створюємо агреговану позицію
                            entry_price = ref_price  # Завжди XT ціна
                            # ФІКСОВАНА ЦІЛЬ: +30% прибутку з левериджем (як просив користувач)
                            if side == "LONG":
                                tp_price = entry_price * (1 + 0.30 / LEVERAGE)  # 30% прибутку з левериджем
                            else:  # SHORT
                                tp_price = entry_price * (1 - 0.30 / LEVERAGE)  # 30% прибутку з левериджем
                            position = {
                                "side": side,
                                "avg_entry": entry_price,
                                "size_usdt": ORDER_AMOUNT,
                                "adds_done": 0,
                                "last_add_price": entry_price,
                                "tp_price": tp_price,
                                "last_add_time": time.time(),
                                "exchange": trading_exchange,  # Запам'ятовуємо на якій біржі торгуємо
                                # 🎯 НОВІ ПОЛЯ ДЛЯ АВТОМАТИЧНОГО ЗАКРИТТЯ
                                "entry_time": time.time(),  # час входу в позицію
                                "arb_pair": f"{trading_exchange}-dex",  # тип арбітражу (gate-dex або xt-dex)
                                "entry_spread_pct": spread_pct,  # початковий спред
                                "entry_ref_price": dex_price,  # референтна ціна DEX на час входу
                                "status": "open"  # статус позиції (open/closing/closed)
                            }
                            # 🔒 ЗАХИСТ: Тільки для НОВИХ позицій встановлюємо таймери
                            current_time = time.time()
                            existing_position = active_positions.get(symbol, {})
                            if 'opened_at' not in existing_position or existing_position.get('opened_at', 0) <= 0:
                                position['opened_at'] = current_time
                            else:
                                position['opened_at'] = existing_position['opened_at']  # Зберігаємо існуючий!
                            if 'expires_at' not in existing_position or existing_position.get('expires_at', 0) <= 0:
                                position['expires_at'] = position['opened_at'] + POSITION_MAX_AGE_SEC
                            else:
                                position['expires_at'] = existing_position['expires_at']  # Зберігаємо існуючий!
                            position['xt_pair_url'] = generate_xt_pair_url(symbol)
                            
                            with active_positions_lock:
                                active_positions[symbol] = position
                            
                            # Зберігаємо оновлені позиції
                            save_positions_to_file()
                            
                            # 📱 ВІДПРАВЛЯЄМО ПРОФЕСІЙНЕ ПОВІДОМЛЕННЯ ПРО ВІДКРИТТЯ ПОЗИЦІЇ
                            try:
                                from telegram_formatter import format_position_opened_message
                                opened_message = format_position_opened_message(
                                    symbol=symbol,
                                    side=side,
                                    entry_price=ref_price,
                                    size_usd=ORDER_AMOUNT,
                                    leverage=LEVERAGE,
                                    spread_percent=spread_pct
                                )
                                send_to_admins_and_group(opened_message)
                                logging.info(f"📱 Відправлено Telegram про відкриття {symbol}")
                            except Exception as e:
                                logging.error(f"❌ Помилка відправки Telegram: {e}")
                            
                            logging.info("Opened %s on %s avg_entry=%.6f tp=%.6f", side, symbol, ref_price, tp_price)
                
                elif has_position and AVERAGING_ENABLED:
                    # 🔒 УСЕРЕДНЕННЯ: Отримуємо позицію з захистом
                    with active_positions_lock:
                        position = active_positions[symbol].copy()  # Копіюємо для уникнення змін під час роботи
                    current_time = time.time()
                    cooldown_passed = (current_time - position.get('last_add_time', 0)) >= AVERAGING_COOLDOWN_SEC
                    can_add_more = position.get('adds_done', 0) < AVERAGING_MAX_ADDS
                    
                    # 🔍 ДЕТАЛЬНЕ ЛОГУВАННЯ для діагностики
                    logging.info(f"[{symbol}] 🔍 УСЕРЕДНЕННЯ ДІАГНОСТИКА: adds_done={position.get('adds_done', 0)}, max_adds={AVERAGING_MAX_ADDS}, can_add_more={can_add_more}, cooldown_passed={cooldown_passed}")
                    
                    # Перевірка ліміту позиції на символ
                    position_size_ok = position['size_usdt'] < MAX_POSITION_USDT_PER_SYMBOL
                    
                    # 🎯 ЯВНА ПЕРЕВІРКА ВСІХ УМОВ для усереднення (як просив architect)
                    if AVERAGING_ENABLED and can_add_more and cooldown_passed and position_size_ok:
                        # Перевірка чи ціна йде проти позиції
                        avg_entry = position['avg_entry']
                        should_average = False
                        
                        if position['side'] == "LONG" and side == "LONG":
                            # LONG позиція: усереднюємо якщо ціна впала
                            adverse_threshold = avg_entry * (1 - AVERAGING_THRESHOLD_PCT / 100)
                            should_average = xt_price <= adverse_threshold
                        elif position['side'] == "SHORT" and side == "SHORT":
                            # SHORT позиція: усереднюємо якщо ціна виросла
                            adverse_threshold = avg_entry * (1 + AVERAGING_THRESHOLD_PCT / 100)
                            should_average = xt_price >= adverse_threshold
                        
                        if should_average:
                            # 🎯 ЖОРСТКА ПЕРЕВІРКА ЛІМІТІВ: не перевищуємо MAX_POSITION_USDT_PER_SYMBOL
                            remaining_capacity = MAX_POSITION_USDT_PER_SYMBOL - position['size_usdt']
                            
                            if remaining_capacity <= 0:
                                logging.warning(f"[{symbol}] ❌ УСЕРЕДНЕННЯ ЗАБЛОКОВАНО: позиція досягла максимуму ${MAX_POSITION_USDT_PER_SYMBOL:.2f}, поточний розмір=${position['size_usdt']:.2f}")
                                return # ⬅️ ЗМІНЕНО: з continue на return
                            
                            # 🛡️ ТОЧНИЙ РОЗРАХУНОК: використовуємо фіксований ORDER_AMOUNT, але перевіряємо ліміти
                            if remaining_capacity < ORDER_AMOUNT:
                                logging.warning(f"[{symbol}] ❌ УСЕРЕДНЕННЯ СКАСОВАНО: недостатньо місця для ORDER_AMOUNT=${ORDER_AMOUNT:.2f}, залишок=${remaining_capacity:.2f}")
                                return # ⬅️ ЗМІНЕНО: з continue на return
                            if available_balance < ORDER_AMOUNT:
                                logging.warning(f"[{symbol}] ❌ УСЕРЕДНЕННЯ СКАСОВАНО: недостатньо балансу для ORDER_AMOUNT=${ORDER_AMOUNT:.2f}, баланс=${available_balance:.2f}")
                                return # ⬅️ ЗМІНЕНО: з continue на return
                            
                            # 🎯 ЗАВЖДИ ВИКОРИСТОВУЄМО ФІКСОВАНИЙ ORDER_AMOUNT для консистентності
                            add_size = ORDER_AMOUNT
                            
                            logging.info(f"[{symbol}] 📈 УСЕРЕДНЕННЯ РОЗРАХУНОК: поточний_розмір=${position['size_usdt']:.2f}, макс=${MAX_POSITION_USDT_PER_SYMBOL:.2f}, залишок=${remaining_capacity:.2f}, додаємо=${add_size:.2f}")
                            
                            # УСЕРЕДНЕННЯ ТІЛЬКИ ЯКЩО Є ДОСТАТНЬО МІСЦЯ ТА БАЛАНСУ!
                            if add_size >= 1.0:  # Мінімум $1.00 для ордера
                                logging.info(f"[{symbol}] 📈 УСЕРЕДНЕННЯ: {position['side']} add_size=${add_size:.2f}, ціна={xt_price:.6f} vs avg={avg_entry:.6f}, спред={abs(spread_pct):.3f}%")
                                
                                # Перевірка ліквідності для усереднення з правильної біржі
                                ok_liq = can_execute_on_orderbook(symbol, add_size, ORDER_BOOK_DEPTH, exchange=trading_exchange)
                                
                                # 🔍 ДОДАТКОВА ПЕРЕВІРКА XT order book для усереднення
                                if ok_liq and trading_exchange == "xt":
                                    # ВИПРАВЛЕНО: використовуємо notional size для усереднення
                                    avg_notional_size = add_size * LEVERAGE
                                    can_avg_xt, xt_avg_info = analyze_xt_order_book_liquidity(xt, symbol, position['side'], avg_notional_size, min_liquidity_ratio=2.0)
                                    if not can_avg_xt:
                                        logging.warning(f"[{symbol}] УСЕРЕДНЕННЯ: {xt_avg_info}")
                                        ok_liq = False
                                    else:
                                        logging.info(f"[{symbol}] УСЕРЕДНЕННЯ: {xt_avg_info}")


                                # if ok_liq:
                                #     # ПРИМУСОВЕ встановлення левериджу ПЕРЕД усередненням
                                #     if trading_exchange == "xt":
                                #         try:
                                #             xt.set_leverage(LEVERAGE, symbol)
                                #             logging.info(f"[{symbol}] ⚙️ XT: ПРИМУСОВО встановлено леверидж {LEVERAGE}x для усереднення")
                                #         except Exception as e:
                                #             logging.error(f"[{symbol}] ❌ Помилка левериджу XT при усередненні: {e}")
                                #             pass

                                if ok_liq:
                                    # ПРИМУСОВЕ встановлення левериджу ПЕРЕД усередненням
                                    if trading_exchange == "xt":
                                        # 🔥 ДОДАНО: Встановлення ІЗОЛЬОВАНОЇ МАРЖІ для усереднення
                                        try:
                                            xt.set_margin_mode('isolated', symbol)
                                        except Exception as e:
                                            pass

                                        try:
                                            xt.set_leverage(LEVERAGE, symbol)
                                            logging.info(f"[{symbol}] ⚙️ XT: ПРИМУСОВО встановлено леверидж {LEVERAGE}x для усереднення")
                                        except Exception as e:                                
                                            logging.error(f"[{symbol}] ❌ Помилка левериджу XT при усередненні: {e}")
                                            pass
                                        # 🔒 ORDER PLACEMENT LOCK для усереднення (Task 6: запобігаємо конфліктним ордерам)
                                        with order_placement_lock:
                                            order = xt_open_market_position(xt, symbol, position['side'], add_size, LEVERAGE, ref_price, dex_price, spread_pct)
                                        current_price = ref_price  # Завжди XT ціна
                                    else:
                                        order = None
                                        current_price = ref_price
                                    if order:
                                        # 🔒 Оновлення агрегованої позиції з захистом
                                        with active_positions_lock:
                                            if symbol in active_positions:  # Перевіряємо що позиція ще існує
                                                current_position = active_positions[symbol]
                                                new_size = current_position['size_usdt'] + add_size
                                                new_avg_entry = (current_position['avg_entry'] * current_position['size_usdt'] + current_price * add_size) / new_size
                                            else:
                                                logging.warning(f"[{symbol}] Позиція не знайдена для усереднення")
                                                return # ⬅️ ЗМІНЕНО: з continue на return
                                                # ФІКСОВАНА ЦІЛЬ: +30% прибутку з левериджем (як просив користувач)
                                                if current_position['side'] == "LONG":
                                                    new_tp_price = new_avg_entry * (1 + 0.30 / LEVERAGE)  # 30% прибутку з левериджем
                                                else:  # SHORT
                                                    new_tp_price = new_avg_entry * (1 - 0.30 / LEVERAGE)  # 30% прибутку з левериджем
                                                
                                                active_positions[symbol].update({
                                                    'avg_entry': new_avg_entry,
                                                    'size_usdt': new_size,
                                                    'adds_done': current_position['adds_done'] + 1,
                                                    'last_add_price': ref_price,
                                                    'tp_price': new_tp_price,
                                                    'last_add_time': current_time
                                                })
                                                
                                                # 🔍 ДЕТАЛЬНЕ ЛОГУВАННЯ оновлення позиції  
                                                logging.info(f"✅ ПОЗИЦІЯ ОНОВЛЕНА: adds_done {current_position['adds_done']} -> {current_position['adds_done'] + 1}, розмір ${current_position['size_usdt']:.2f} -> ${new_size:.2f}")
                                        
                                        # 🔍 ВИПРАВЛЕНО: використовуємо оновлене значення adds_done
                                        updated_adds = current_position['adds_done'] + 1
                                        logging.info(f"✅ УСЕРЕДНЕННЯ ЗАВЕРШЕНО {position['side']} на {symbol}: нова avg_entry={new_avg_entry:.6f}, розмір=${new_size:.2f}, додавань={updated_adds}/{AVERAGING_MAX_ADDS}")
            else:
                if not spread_check:
                    logging.debug(f"[{symbol}] Спред {abs(spread_pct):.3f}% < {MIN_SPREAD}%")
                elif not positions_check and not has_position:
                    logging.info(f"[{symbol}] ❌ Занадто багато позицій: {total_positions} >= {MAX_OPEN_POSITIONS}")
                elif not balance_check:
                    logging.info(f"[{symbol}] ❌ Недостатньо балансу: потрібно {required_margin:.4f} USDT, є {available_balance:.4f} USDT")
        except Exception as balance_error:
            logging.exception("Balance check error with full traceback")

        # 4) 🔒 АВТОМАТИЧНЕ ЗАКРИТТЯ ПРИ СПРЕДІ 30% З ЗАХИСТОМ
        with active_positions_lock:
            if symbol in active_positions:
                position = active_positions[symbol].copy()  # Копіюємо для роботи поза локом
            else:
                position = None
        
        if position:
            
            # ✅ НОВІ УМОВИ ВИХОДУ (як просив користувач):
            # 1) Основна ціль: +30% прибутку
            # 2) При зникненні спреду: дострокове закриття на +10-15%
            
            current_price = ref_price  # Завжди XT ціна
            entry_price = position['avg_entry']
            
            # Розрахунок поточного P&L у відсотках
            if position['side'] == "LONG":
                pnl_pct = ((current_price - entry_price) / entry_price) * 100 * LEVERAGE
            else:  # SHORT  
                pnl_pct = ((entry_price - current_price) / entry_price) * 100 * LEVERAGE
            
            should_close = False
            close_reason = ""
            
            if pnl_pct >= TAKE_PROFIT_PCT:
                should_close = True
                close_reason = f"🎯 ДОСЯГНУТО ЦІЛЬ +{TAKE_PROFIT_PCT}%! P&L={pnl_pct:.1f}%"
                
            # 2) ДОСТРОКОВЕ ЗАКРИТТЯ: спред зникає + є хоча б половина від бажаного профіту
            # Наприклад, якщо TP=5%, то закриє при зникненні спреду якщо є хоча б 2.5% профіту
            elif abs(spread_pct) < 0.3 and (TAKE_PROFIT_PCT / 2) <= pnl_pct: 
                should_close = True
                close_reason = f"⚡ ДОСТРОКОВЕ ЗАКРИТТЯ: спред зник + прибуток {pnl_pct:.1f}%"
                
            # 3) ЗАХИСТ: спред > 30% (аномалія)
            elif abs(spread_pct) >= 30.0:
                should_close = True 
                close_reason = f"🚨 АВАРІЙНЕ ЗАКРИТТЯ: спред {abs(spread_pct):.2f}% >= 30%"
                
            # # 1) ОСНОВНА ЦІЛЬ: +30% прибутку (примусове закриття)
            # if pnl_pct >= 30.0:
            #     should_close = True
            #     close_reason = f"🎯 ДОСЯГНУТО ЦІЛЬ +30%! P&L={pnl_pct:.1f}%"
                
            # # 2) ДОСТРОКОВЕ ЗАКРИТТЯ: спред зникає + прибуток 10-15%
            # elif abs(spread_pct) < 0.3 and 10.0 <= pnl_pct < 30.0:  # спред < 0.3% вважається "зниклим"
            #     should_close = True
            #     close_reason = f"⚡ ДОСТРОКОВЕ ЗАКРИТТЯ: спред зник ({abs(spread_pct):.2f}% < 0.3%) + прибуток {pnl_pct:.1f}% (в межах 10-30%)"
                
            # # 3) ЗАХИСТ: спред > 30% (як було раніше)
            # elif abs(spread_pct) >= 30.0:
            #     should_close = True 
            #     close_reason = f"🚨 АВАРІЙНЕ ЗАКРИТТЯ: спред {abs(spread_pct):.2f}% >= 30%"
            
            if should_close:
                logging.warning(f"🚨 АВТОЗАКРИТТЯ {position['side']} {symbol}: {close_reason}")
                
                # БЕЗПЕЧНЕ ЗАКРИТТЯ: спочатку закриваємо на біржі, потім видаляємо з системи
                try:
                    # Отримуємо свіжу ціну для точного закриття
                    fresh_ticker = fetch_ticker(xt, symbol)
                    if fresh_ticker:
                        current_xt_price = float(fresh_ticker['last'])
                    else:
                        current_xt_price = ref_price  # fallback
                    
                    # ПЕРЕВІРЯЄМО ЧИ ІСНУЄ ПОЗИЦІЯ ПЕРЕД ЗАКРИТТЯМ
                    # Отримуємо свіжі позиції з біржі
                    try:
                        # 🔧 ВИКОРИСТОВУЄМО БЕЗПЕЧНИЙ WRAPPER
                        # Gate.io відключено - використовуємо тільки XT  
                        # Gate.io відключено - використовуємо тільки XT positions
                        current_positions = []
                        has_real_position = False
                        for pos in current_positions:
                            if pos['symbol'] == symbol and float(pos.get('contracts', 0)) > 0:
                                has_real_position = True
                                break
                        
                        if not has_real_position:
                            logging.warning(f"🚨 ПОЗИЦІЯ {symbol} УЖЕ ЗАКРИТА НА БІРЖІ - видаляємо з системи")
                            with active_positions_lock:
                                if symbol in active_positions:
                                    del active_positions[symbol]
                            return # ⬅️ ЗМІНЕНО: з continue на return
                    except:
                        logging.warning(f"⚠️ Не вдалося перевірити позиції - пробуємо закрити")
                    
                    # Пробуємо закрити позицію на біржі
                    close_success = close_position_market(symbol, position['side'], position['size_usdt'])
                    
                    if close_success:
                        # 🔒 ТІЛЬКИ якщо закриття успішне - видаляємо з системи
                        with active_positions_lock:
                            if symbol in active_positions:
                                del active_positions[symbol]
                        
                        # ДОДАЄМО ДО ІСТОРІЇ ТОРГІВЛІ
                        try:
                            import telegram_admin
                            telegram_admin.add_to_trade_history(
                                symbol=symbol,
                                side=position['side'],
                                entry_price=position['avg_entry'],
                                close_price=current_xt_price,
                                pnl=(position['size_usdt'] * pnl_pct / 100),
                                close_reason=close_reason,
                                exchange="Gate.io"
                            )
                            logging.info(f"📚 Додано до історії: {symbol} P&L={pnl_pct:+.1f}%")
                        except Exception as history_error:
                            logging.error(f"❌ Помилка додавання до історії: {history_error}")
                        
                        # Визначаємо емодзі результату
                        if pnl_pct > 0:
                            result_emoji = "💚"
                            result_text = f"+${(position['size_usdt'] * pnl_pct / 100):+.2f}"
                        elif pnl_pct < 0:
                            result_emoji = "❤️"
                            result_text = f"${(position['size_usdt'] * pnl_pct / 100):+.2f}"
                        else:
                            result_emoji = "💙"
                            result_text = "$0.00"
                        
                        # 🎯 РОЗШИРЕНЕ ДЕТАЛЬНЕ СПОВІЩЕННЯ ПРО АВТОЗАКРИТТЯ (як просив користувач!)
                        close_signal = f"🎯 **АВТОЗАКРИТТЯ ПОЗИЦІЇ** {result_emoji}\n"\
                                     f"📊 **{symbol.replace('/USDT:USDT', '')}** ({position['side']}) | ⚡ XT.COM\n"\
                                     f"💰 Розмір: **${position['size_usdt']:.2f} USDT** | Леверидж: **{LEVERAGE}x**\n"\
                                     f"📈 Вхід: **${position['avg_entry']:.6f}**\n"\
                                     f"📉 Вихід: **${current_xt_price:.6f}**\n"\
                                     f"💎 P&L: **{pnl_pct:+.1f}%** ({result_text})\n"\
                                     f"📊 Спред: **{abs(spread_pct):.2f}%**\n"\
                                     f"🎯 Причина: **{close_reason}**\n"\
                                     f"⏰ Час: {datetime.now().strftime('%H:%M:%S')}\n"\
                                     f"✅ Статус: **УСПІШНО ЗАКРИТО** | #ArbitrageBot"
                        
                        # 📊 ПОЗИЦІЇ ОБОМ АДМІНАМ + ГРУПІ
                        send_to_admins_and_group(close_signal)
                        logging.info(f"✅ АВТОЗАКРИТО {position['side']} {symbol}: спред={abs(spread_pct):.2f}%, розмір=${position['size_usdt']:.2f}")
                        return  # ⬅️ ЗМІНЕНО: з continue на return
                    else:
                        # 🔥 КРИТИЧНЕ ВИПРАВЛЕННЯ: НЕ відправляємо Telegram для нормальних помилок автозакриття
                        logging.info(f"⚠️ Автозакриття {position['side']} {symbol} не вдалося - це може бути нормально (позиція вже закрита)")
                        # Позиція залишається в active_positions для подальшого управління
                        
                except Exception as close_error:
                    # 🔥 КРИТИЧНЕ ВИПРАВЛЕННЯ: Використовуємо ту саму логіку фільтрації як у close_position_market
                    error_str = str(close_error).lower()
                    normal_errors = [
                        "reduce_exceeded", "empty position", "position not found",
                        "insufficient margin", "position already closed", "order not found",
                        "rate limit", "timeout", "connection", "network"
                    ]
                    is_normal_error = any(err in error_str for err in normal_errors)
                    
                    if is_normal_error:
                        logging.info(f"⚠️ Нормальна помилка автозакриття {symbol}: {error_str[:50]}... (без сповіщення)")
                    else:
                        logging.error(f"❌ КРИТИЧНА ПОМИЛКА при автозакритті {symbol}: {close_error}")
                        # ТІЛЬКИ для справді критичних помилок відправляємо в Telegram
                        error_signal = f"🚨 **КРИТИЧНА СИСТЕМНА ПОМИЛКА!**\n"\
                                     f"📊 Символ: **{symbol.replace('/USDT:USDT', '')}** ({position['side']})\n"\
                                     f"💰 Розмір позиції: **${position['size_usdt']:.2f}**\n"\
                                     f"📈 Вхід: **${position['avg_entry']:.6f}**\n"\
                                     f"📉 Поточна ціна: **${ref_price:.6f}**\n"\
                                     f"📊 P&L: **{pnl_pct:+.1f}%**\n"\
                                     f"⚠️ Спред: **{abs(spread_pct):.2f}%**\n"\
                                     f"🎯 Причина: {close_reason}\n"\
                                     f"❌ **ПОМИЛКА API**: `{str(close_error)[:100]}...`\n"\
                                     f"🏪 Біржа: **{position.get('exchange', 'gate').upper()}**\n"\
                                     f"⏰ Час: **{time.strftime('%H:%M:%S %d.%m.%Y')}**\n"\
                                     f"🚨 **ТЕРМІНОВО ПОТРІБНЕ РУЧНЕ ВТРУЧАННЯ!**"
                        # 🚨 КРИТИЧНІ ПОМИЛКИ ОБОМ АДМІНАМ + ГРУПІ
                        send_to_admins_and_group(error_signal)
                    # Позиція залишається в системі для подальшого управління
            
            # ВИДАЛЕНО: стара логіка 25% TP - замінена на нову логіку 30% вище

    except Exception as e:
        # ДЕТАЛЬНЕ ЛОГУВАННЯ ГЛОБАЛЬНИХ ПОМИЛОК ВОРКЕРА
        error_msg = f"⚠️ **ПОМИЛКА ВОРКЕРА СИМВОЛУ**\n"\
                   f"📊 Символ: **{symbol.replace('/USDT:USDT', '')}**\n"\
                   f"❌ Помилка: `{str(e)[:150]}...`\n"\
                   f"🔧 Воркер продовжує роботу через 30 сек\n"\
                   f"⏰ Час: **{time.strftime('%H:%M:%S')}**"
        # Відправляємо тільки у випадку серйозних помилок (не часті дрібниці)  
        if "timeout" not in str(e).lower() and "rate limit" not in str(e).lower():
            # 🚨 ПОМИЛКИ ВОРКЕРА ОБОМ АДМІНАМ + ГРУПІ
            send_to_admins_and_group(error_msg)
        logging.error("Symbol worker error %s %s", symbol, e)

    # ⛔️ ВИДАЛЕНО: time.sleep(SCAN_INTERVAL)
    logging.info(f"Worker finished for {symbol}") # ⬅️ ЗМІНЕНО: логування завершення

# def symbol_worker(symbol):
#     """
#     Робота по одному символу з усередненням позицій: fetch ticker, dex price via dexscreener, calc spread, check liquidity, open/average/close
#     """
#     logging.info("Worker started for %s", symbol)
#     while bot_running:
#         try:
#             if not trade_symbols.get(symbol, False):
#                 time.sleep(1)
#                 continue

#             # 1) ТІЛЬКИ XT БІРЖА - отримуємо ціну з XT (як просив користувач)
#             xt_price = None
#             if not (xt_markets_available and xt):
#                 logging.debug(f"[{symbol}] ❌ XT біржа недоступна")
#                 time.sleep(SCAN_INTERVAL)
#                 continue
                
#             try:
#                 xt_price = get_xt_price(xt, symbol)
#                 if not xt_price or not is_xt_futures_tradeable(symbol):
#                     logging.debug(f"[{symbol}] ❌ Неможливо торгувати на XT futures")
#                     time.sleep(SCAN_INTERVAL)
#                     continue
#                 logging.debug(f"[{symbol}] ✅ XT ціна: ${xt_price:.6f}")
#             except Exception as e:
#                 logging.debug(f"[{symbol}] ⚠️ XT ціна недоступна: {e}")
#                 time.sleep(SCAN_INTERVAL)
#                 continue

#             # 2) ТІЛЬКИ ТОДІ DexScreener - отримуємо РОЗШИРЕНІ МЕТРИКИ
#             try:
#                 # 🔬 РОЗШИРЕНИЙ АНАЛІЗ: ліквідність, FDV, market cap, транзакції, покупці/продавці
#                 advanced_metrics = get_advanced_token_analysis(symbol)
#                 if not advanced_metrics:
#                     logging.debug(f"[{symbol}] ❌ Немає якісної пари на DexScreener")
#                     time.sleep(SCAN_INTERVAL)
#                     continue
                    
#                 # Отримуємо базові дані (backward compatibility)
#                 token_info = {
#                     'price_usd': advanced_metrics.get('price_usd', 0),
#                     'liquidity': advanced_metrics.get('liquidity', 0),
#                     'volume_24h': advanced_metrics.get('volume_24h', 0),
#                     'dex_link': advanced_metrics.get('exact_pair_url') or get_proper_dexscreener_link(symbol)
#                 }
                
#                 # Коротка інформація про токен (зменшено логування)
#                 logging.info(f"📊 {symbol}: ${advanced_metrics.get('price_usd', 0):.6f} | Vol ${advanced_metrics.get('volume_1h', 0):,.0f}")
                    
#                 if not token_info:
#                     logging.debug(f"[{symbol}] ❌ Немає якісної пари на DexScreener")
#                     time.sleep(SCAN_INTERVAL)
#                     continue
                
#                 dex_price = token_info['price_usd']
                
#                 # ЖОРСТКІ ПЕРЕВІРКИ (як у топових арбітражних ботів)
#                 if not dex_price or dex_price < 0.000001:  # мінімальна ціна $0.000001
#                     raise Exception(f"Invalid DexScreener price: {dex_price}")
                    
#             except Exception as e:
#                 # БЛОКУЄМО токени з поганими DexScreener цінами - як у друга з Bybit
#                 logging.warning(f"[{symbol}] ❌ Пропускаємо через погану DexScreener ціну: {e}")
#                 time.sleep(SCAN_INTERVAL)
#                 continue

#             # 3) ТІЛЬКИ XT vs DexScreener АРБІТРАЖ (Gate.io ВІДКЛЮЧЕНО)
#             if not xt_price:
#                 logging.debug(f"[{symbol}] ❌ XT ціна недоступна")
#                 time.sleep(SCAN_INTERVAL)
#                 continue
                
#             # Розраховуємо спред XT vs DexScreener
#             xt_dex_spread = calculate_spread(dex_price, xt_price)
#             best_spread = xt_dex_spread
#             best_direction = "LONG" if xt_price < dex_price else "SHORT" 
#             best_exchange_pair = "XT vs Dex"
#             trading_exchange = "xt"  # ЗАВЖДИ торгуємо на XT
#             ref_price = xt_price  # ВИПРАВЛЕНО: XT ціна для XT біржі
            
#             spread_pct = best_spread
#             spread_store.append(spread_pct)
            
#             # Покращене логування тільки з XT та DexScreener
#             clean_symbol = symbol.replace('/USDT:USDT', '')
#             log_info = f"XT: ${xt_price:.6f} | Dex: ${dex_price:.6f} | Спред: {best_spread:.2f}% {best_direction} | Торгуємо на: XT"
#             logging.info(f"[{clean_symbol}] {log_info}")
            
#             # 🚀 НОВІ ФІШКИ: Розумна аналітика ПІСЛЯ встановлення trading_exchange
#             volatility = calculate_volatility_indicator(symbol, trading_exchange)
#             volume_analysis = analyze_volume_quality(symbol, token_info, trading_exchange)
#             smart_timing = smart_entry_timing(symbol, abs(spread_pct), volatility, volume_analysis)
            
#             # Логування нових фішок
#             # Аналіз якості токена (логування зменшено)
#             if volatility.get('status') == 'success' and smart_timing.get('status') == 'success':
#                 logging.info(f"[{clean_symbol}] 📊 Волатільність: {volatility['volatility']}% | Тайминг: {smart_timing['grade']}")
            
#             # ✅ ПОВНА АВТОМАТИЗАЦІЯ - БЕЗ БЛОКИРОВОК!
#             enhanced_entry_check = True
            
#             # Інформаційні повідомлення (БЕЗ БЛОКУВАННЯ!)
#             # Попередження тільки для критичних випадків
#             if volatility.get('risk_level') == 'EXTREME' and volatility.get('volatility', 0) > 30:
#                 logging.info(f"[{clean_symbol}] ⚠️ Висока волатільність {volatility.get('volatility', 0)}% - торгуємо обережно")
            
#             # НЕ спамимо про кожну арбітражну можливість - тільки про реальні торгові операції

#             # 3) Перевірка балансу перед торгівлею
#             # МАРЖА ЗА НАЛАШТУВАННЯМ (збільшено для торгівлі дорожчими токенами)
#             required_margin = float(ORDER_AMOUNT)  # Примусове приведення до float
            
#             # 🔒 THREAD-SAFE БАЛАНС (Task 6: захист від одночасних перевірок балансу)
#             try:
#                 with balance_check_lock:  # ЗАХИСТ: тільки один worker перевіряє баланс одночасно
#                     # Видалено DEBUG логування для чистоти
                    
#                     # ✅ ТІЛЬКИ XT.COM БІРЖА - ОБИДВА АКАУНТИ
#                     if trading_exchange == "xt":
#                         # Баланс акаунта 1
#                         balance_1 = get_xt_futures_balance(xt_account_1)
#                         available_balance_1 = float(balance_1.get('free', 0.0))
#                         # Баланс акаунта 2
#                         balance_2 = get_xt_futures_balance(xt_account_2)
#                         available_balance_2 = float(balance_2.get('free', 0.0))
#                         # Загальний доступний баланс
#                         available_balance = available_balance_1 + available_balance_2
#                         logging.info(f"💰 XT.com АКАУНТ 1: ${balance_1['total']:.2f} USDT (доступно ${available_balance_1:.2f})")
#                         logging.info(f"💰 XT.com АКАУНТ 2: ${balance_2['total']:.2f} USDT (доступно ${available_balance_2:.2f})")
#                         logging.info(f"💰 ЗАГАЛОМ: ${balance_1['total'] + balance_2['total']:.2f} USDT (доступно ${available_balance:.2f})")
#                     else:
#                         # Якщо trading_exchange не XT - пропускаємо
#                         logging.warning(f"[{symbol}] ⚠️ Підтримуємо тільки XT біржу, пропускаємо: {trading_exchange}")
#                         continue
                        
#                     # Детальне логування умов торгівлі
#                     spread_check = abs(spread_pct) >= MIN_SPREAD
#                     balance_check = available_balance >= required_margin
                    
#                     # 🔒 Перевірка кількості активних позицій з ЗАХИСТОМ (поза balance_check_lock)
#                     with active_positions_lock:
#                         total_positions = len(active_positions)
#                         has_position = symbol in active_positions
#                     positions_check = total_positions < MAX_OPEN_POSITIONS
                
                
#                 # 🔥 ПОКРАЩЕНІ ФІЛЬТРИ РЕАЛЬНОСТІ - відсіюємо фейкові арбітражі!
#                 is_realistic = True
                
#                 # 1. РОЗУМНИЙ спред фільтр: різні ліміти для різних монет
#                 clean_symbol = symbol.replace('/USDT:USDT', '')
                
#                 # Основні монети (ETH, BTC тощо) - більш жорсткі ліміти
#                 major_tokens = ['ETH', 'BTC', 'BNB', 'ADA', 'SOL', 'MATIC', 'AVAX', 'DOT', 'LINK']
#                 max_spread_limit = 50.0  # ПОЛІПШЕНО: максимум 50% для блокування фейків
                
#                 # ЖОРСТКА перевірка фейкових спредів  
#                 if abs(spread_pct) > max_spread_limit:
#                     logging.warning(f"[{symbol}] ❌ ФЕЙК: Нереальний спред {spread_pct:.2f}% > {max_spread_limit}%")
#                     is_realistic = False
                
#                 # БЛОКУВАННЯ НЕГАТИВНИХ СПРЕДІВ (очевидні фейки)
#                 if spread_pct < -25.0:  # Негативні спреди більше -25% завжди фейкові  
#                     logging.warning(f"[{symbol}] ❌ ФЕЙК: Негативний спред {spread_pct:.2f}% заблоковано")
#                     is_realistic = False
                
#                 # 2. РОЗСЛАБЛЕНА перевірка співвідношення цін для більше можливостей
#                 price_ratio = max(xt_price, dex_price) / min(xt_price, dex_price)
#                 max_price_ratio = 2.5  # РОЗСЛАБЛЕНО: 2.5x для всіх монет для більше сигналів
                
#                 if price_ratio > max_price_ratio:
#                     logging.warning(f"[{symbol}] ❌ ФЕЙК: Ціни відрізняються в {price_ratio:.2f} разів (макс. {max_price_ratio:.1f}x)")
#                     is_realistic = False
                
#                 # 3. АБСОЛЮТНА перевірка цін для топ-монет (як ETH $3701 vs $4601)  
#                 if clean_symbol in major_tokens:
#                     # Перевіряємо що цінди в розумних межах для топ-монет
#                     expected_ranges = {
#                         'ETH': (2000, 6000),    # ETH очікується $2000-6000
#                         'BTC': (30000, 100000), # BTC очікується $30k-100k  
#                         'BNB': (200, 1000),     # BNB очікується $200-1000
#                         'SOL': (50, 500),       # SOL очікується $50-500
#                         'ADA': (0.2, 3.0),      # ADA очікується $0.2-3.0
#                     }
                    
#                     if clean_symbol in expected_ranges:
#                         min_price, max_price = expected_ranges[clean_symbol]
#                         if not (min_price <= xt_price <= max_price) or not (min_price <= dex_price <= max_price):
#                             logging.warning(f"[{symbol}] ❌ ФЕЙК: Ціна поза межами для {clean_symbol}: XT=${xt_price:.2f}, Dex=${dex_price:.2f} (очікується ${min_price}-${max_price})")
#                             is_realistic = False
                
#                 # 4. ЖОРСТКІ ФІЛЬТРИ: Мінімальна ліквідність та обсяг для торгівлі (як просив користувач)
#                 min_liquidity = token_info.get('liquidity', 0)
#                 min_volume_24h = token_info.get('volume_24h', 0)
                
#                 if min_liquidity < MIN_POOLED_LIQUIDITY_USD:  # ФІЛЬТР з config.py
#                     logging.warning(f"[{symbol}] ❌ ФЕЙК: Мала ліквідність ${min_liquidity:,.0f} < ${MIN_POOLED_LIQUIDITY_USD:,}")
#                     is_realistic = False
                    
#                 if min_volume_24h < MIN_24H_VOLUME_USD:  # ФІЛЬТР з config.py
#                     logging.warning(f"[{symbol}] ❌ ФЕЙК: Малий обсяг ${min_volume_24h:,.0f} < ${MIN_24H_VOLUME_USD:,}")
#                     is_realistic = False
                
#                 # 5. Перевіряємо що це не стейблкоїн або заблоковані токени
#                 blacklisted_tokens = ['USDT', 'USDC', 'BUSD', 'DAI', 'TUSD', 'FDUSD', 'TON']
#                 if any(token in clean_symbol for token in blacklisted_tokens):
#                     logging.info(f"[{symbol}] ❌ ЗАБЛОКОВАНО: Токен {clean_symbol} в чорному списку")
#                     is_realistic = False
                
#                 # 6. ДОДАТКОВО: Перевірка кратності цін (виявляє деякі фейки)
#                 if xt_price > 0 and dex_price > 0:
#                     # Якщо одна ціна є точним кратним іншої (x10, x100), це може бути помилка
#                     ratio_check = xt_price / dex_price
#                     if abs(ratio_check - round(ratio_check)) < 0.01 and round(ratio_check) >= 10:
#                         logging.warning(f"[{symbol}] ❌ ФЕЙК: Підозрюване кратне співвідношення цін {ratio_check:.1f}x")
#                         is_realistic = False
                
#                 # АВТОСИГНАЛИ: Окремі сигнали для кожної пари бірж >= MIN_SPREAD
                
#                 # Логування нових фішок
#                 if volatility.get('status') == 'success':
#                     # Компактний звіт якості (зменшено логування)
#                     if volatility.get('status') == 'success' and volume_analysis.get('status') == 'success':
#                         logging.info(f"[{symbol}] 📊 Vol: {volatility['volatility']}% | Об'єм: ${volume_analysis['total_volume']:,.0f} | Тайминг: {smart_timing.get('grade', 'N/A')}")
                
#                 # Підвищуємо вимоги до входу на основі нових фішок
#                 enhanced_entry_check = True
                
#                 # 🎯 ДОЗВОЛЕНО: Блокування тільки найгірших сигналів (дозволяємо FAIR тайминг)
#                 timing_recommendation = smart_timing.get('recommendation', 'WAIT')
#                 if timing_recommendation in ['SKIP_SIGNAL']:  # Тільки SKIP_SIGNAL, WAIT/CONSIDER дозволені
#                     logging.warning(f"[{symbol}] ❌ БЛОКОВАНИЙ СИГНАЛ: таймінг {smart_timing.get('grade')} ({smart_timing.get('timing_score', 0)} балів)")
#                     enhanced_entry_check = False  # БЛОКУЄМО тільки найгірші сигнали
                
#                 # Блокуємо при екстремальній волатильності
#                 if volatility.get('risk_level') == 'EXTREME':
#                     logging.info(f"[{symbol}] 📊 ІНФО: Висока волатільність {volatility.get('volatility', 0)}% але торгуємо далі")
#                     # БЕЗ БЛОКУВАННЯ enhanced_entry_check залишається True
                
#                 # Блокуємо при низькому об'ємі
#                 if volume_analysis.get('quality_score', 0) <= 1:
#                     logging.warning(f"[{symbol}] 📈 БЛОКОВАНО: Занадто низький об'єм ${volume_analysis.get('total_volume', 0):,.0f}")
#                     enhanced_entry_check = False
                
#                 # 🛡️ ПЕРЕВІРЯЄМО ІСНУЮЧІ ПОЗИЦІЇ ПЕРЕД ВІДПРАВКОЮ СИГНАЛІВ
#                 with active_positions_lock:
#                     already_has_position = symbol in active_positions

#                 # 🎯 НОВА ЛОГІКА: ЗБИРАЄМО МОЖЛИВОСТІ БЕЗ БАЛАНСОВИХ ОБМЕЖЕНЬ ДЛЯ НАЙКРАЩИХ СИГНАЛІВ
#                 logging.info(f"🔍 ПЕРЕВІРКА СИГНАЛУ {symbol}: realistic={is_realistic}, entry_check={enhanced_entry_check}, has_position={already_has_position}")
#                 if is_realistic and enhanced_entry_check and not already_has_position:
#                     # 1. XT vs DexScreener (ТІЛЬКИ XT БІРЖА)
#                     xt_dex_spread_pct = calculate_spread(dex_price, xt_price)
#                     if abs(xt_dex_spread_pct) >= MIN_SPREAD:
#                         current_time = time.time()
#                         logging.info(f"🔥 СИГНАЛ ЗНАЙДЕНО: {symbol} спред={xt_dex_spread_pct:.2f}% (мін={MIN_SPREAD}%, макс={MAX_SPREAD}%)")
                        
#                         # 🎯 ЗБИРАЄМО ДЛЯ НАЙКРАЩИХ СИГНАЛІВ (БЕЗ КУЛДАУН ПЕРЕВІРКИ ТУТ)
#                         side = "LONG" if xt_dex_spread_pct > 0 else "SHORT"
                        
#                         # Розраховуємо рейтинг можливості для пошуку найкращого
#                         liquidity = advanced_metrics.get('liquidity', 0)
#                         volume_24h = advanced_metrics.get('volume_24h', 0) 
#                         score = abs(xt_dex_spread_pct) * 100 + (liquidity / 1000) + (volume_24h / 10000)
                        
#                         # ✅ ДОДАЄМО В СИСТЕМУ НАЙКРАЩИХ МОЖЛИВОСТЕЙ (БЕЗ БАЛАНСОВИХ ОБМЕЖЕНЬ)
#                         with opportunities_lock:
#                             best_opportunities[symbol] = {
#                                 'spread': xt_dex_spread_pct,
#                                 'side': side,
#                                 'score': score,
#                                 'timestamp': current_time,
#                                 'xt_price': xt_price,
#                                 'dex_price': dex_price,
#                                 'token_info': token_info,
#                                 'advanced_metrics': advanced_metrics
#                             }
                        
#                         logging.info(f"[{symbol}] 🏆 ДОДАНО ДО НАЙКРАЩИХ: {side} спред={xt_dex_spread_pct:.2f}% (рейтинг={score:.1f})")
                        
#                         # 🚨 НОВА ЛОГІКА: НЕГАЙНЕ ВІДПРАВЛЕННЯ СИГНАЛУ НЕЗАЛЕЖНО ВІД БАЛАНСУ!
#                         # Відправляємо сигнал одразу після знаходження можливості (тільки з кулдауном)
#                         signal_sent = False
                        
#                         with telegram_cooldown_lock:  # КРИТИЧНА СЕКЦІЯ
#                             last_signal_time = telegram_cooldown.get(symbol, 0)
#                             time_since_last = current_time - last_signal_time
                            
#                             if time_since_last >= TELEGRAM_COOLDOWN_SEC:
#                                 signal_sent = True
                                
#                                 # 🛡️ ВЕРИФІКАЦІЯ СИГНАЛУ (як просить користувач - блокуємо без DEX адреси!)
#                                 logging.info(f"🔍 ВЕРИФІКУЮ СИГНАЛ: {symbol} {side} спред={xt_dex_spread_pct:.2f}%")
                                
#                                 try:
#                                     # Створюємо ArbitrageSignal об'єкт для верифікації
#                                     from signal_parser import ArbitrageSignal
#                                     from signal_verification import verify_arbitrage_signal
#                                     from telegram_formatter import format_arbitrage_signal_message
                                    
#                                     test_signal = ArbitrageSignal(
#                                         asset=clean_symbol,
#                                         action=side,
#                                         spread_percent=xt_dex_spread_pct,
#                                         xt_price=xt_price,
#                                         dex_price=dex_price
#                                     )
                                    
#                                     # КРИТИЧНО: Повна верифікація з блокуванням сигналів без DEX адреси
#                                     verification_result = verify_arbitrage_signal(test_signal)
                                    
#                                     if verification_result.valid:
#                                         # ✅ СИГНАЛ ВАЛІДНИЙ - відправляємо з повною інформацією
#                                         signal_message = format_arbitrage_signal_message(test_signal, verification_result)
#                                         logging.info(f"✅ СИГНАЛ ВЕРИФІКОВАНО для {symbol}: DEX знайдено!")
#                                     else:
#                                         # 🔄 СИГНАЛ НЕ ВЕРИФІКОВАНО - відправляємо з fallback посиланням
#                                         logging.info(f"⚠️ ВІДПРАВЛЯЄМО FALLBACK СИГНАЛ для {symbol}: {'; '.join(verification_result.errors)}")
#                                         signal_message = format_arbitrage_signal_message(test_signal, verification_result, for_group=True)
#                                         # НЕ блокуємо відправку - відправляємо з fallback посиланнями!
                                    
#                                 except Exception as signal_error:
#                                     logging.error(f"❌ Помилка верифікації сигналу {symbol}: {signal_error}")
#                                     signal_sent = False
#                                     signal_message = None
                        
#                         # 📱 ВІДПРАВЛЕННЯ В TELEGRAM (ПОЗА ЛОКОМ) - ТІЛЬКИ ВАЛІДНІ СИГНАЛИ!
#                         signal_message = locals().get('signal_message', None)
#                         if signal_sent and signal_message:
#                             try:
#                                 # 🎯 ТОРГОВІ СИГНАЛИ ОБОМ АДМІНАМ + ГРУПІ
#                                 success2 = send_to_admins_and_group(signal_message)
                                
#                                 if success2:
#                                     # ТІЛЬКИ ПІСЛЯ УСПІШНОЇ ВІДПРАВКИ встановлюємо кулдаун
#                                     with telegram_cooldown_lock:
#                                         telegram_cooldown[symbol] = current_time
#                                     logging.info(f"📱 СИГНАЛ ВІДПРАВЛЕНО: {symbol} {side} спред={xt_dex_spread_pct:.2f}% (ігноруємо баланс)")
#                                 else:
#                                     logging.error(f"❌ Помилка відправки в обидва чати {symbol}")
                                    
#                             except Exception as telegram_error:
#                                 logging.error(f"❌ Помилка Telegram відправки {symbol}: {telegram_error}")
                        
#                         # Показуємо кулдаун якщо сигнал заблокований
#                         if not signal_sent:
#                             with telegram_cooldown_lock:
#                                 last_signal_time = telegram_cooldown.get(symbol, 0)
#                                 time_since_last = current_time - last_signal_time
#                                 if time_since_last < TELEGRAM_COOLDOWN_SEC:
#                                     time_left = int(TELEGRAM_COOLDOWN_SEC - time_since_last)
#                                     logging.info(f"[{symbol}] ⏰ КУЛДАУН: ще {time_left}с до наступного сигналу")
                        
#                         # 🔄 СТАРА ЛОГІКА: Тільки для безпосереднього торгування (з балансовими обмеженнями)
#                         # ПРИМУСОВА МАРЖА $5: купуємо частково для будь-якої монети  
#                         # Завжди торгуємо на ФІКСОВАНУ маржу $5.00 (можна купити частину монети)
                        
#                         time.sleep(5)
                    
#                     # 2. XT vs DexScreener (якщо XT доступна)
#                     if xt_price:
#                         xt_dex_spread_pct = calculate_spread(dex_price, xt_price)
#                         if abs(xt_dex_spread_pct) >= MIN_SPREAD:
#                             # ПРИМУСОВА МАРЖА $5: купуємо частково для будь-якої монети
#                             # Завжди торгуємо на ФІКСОВАНУ маржу $5.00 (можна купити частину монети)
#                             # 🕒 THREAD-SAFE КУЛДАУН: синхронізація для багатопоточності
#                             current_time = time.time()
#                             signal_sent = False
                            
#                             with telegram_cooldown_lock:  # КРИТИЧНА СЕКЦІЯ  
#                                 last_signal_time = telegram_cooldown.get(symbol, 0)
#                                 time_since_last = current_time - last_signal_time
                                
#                                 if time_since_last >= TELEGRAM_COOLDOWN_SEC:
#                                     telegram_cooldown[symbol] = current_time  # Одразу встановлюємо час
#                                     signal_sent = True
#                                 else:
#                                     time_left = int(TELEGRAM_COOLDOWN_SEC - time_since_last)
#                                     logging.info(f"[{symbol}] ⏰ СПІЛЬНИЙ КУЛДАУН: ще {time_left}с до наступного сигналу")
                            
#                             # 🎯 ВИДАЛЕНО ДУБЛІКАТ: цей блок дублював логіку з рядків вище
#                             # Залишаємо тільки систему найкращих сигналів
                        
#                         # ВИДАЛЕНО: міжбіржовий арбітраж Gate ↔ XT (залишаємо тільки DEX порівняння)
#                 elif already_has_position:
#                     logging.info(f"[{symbol}] ⏹️ ПРОПУСКАЄМО СИГНАЛ: вже є активна позиція")
#                 elif abs(spread_pct) >= MIN_SPREAD and not is_realistic:
#                     logging.warning(f"[{symbol}] ❌ БЛОКОВАНИЙ ФЕЙК: спред={spread_pct:.2f}%")
                
#                 # РЕАЛЬНА ТОРГІВЛЯ З УСЕРЕДНЕННЯМ
#                 if spread_check and balance_check and not DRY_RUN and is_realistic:
#                     side = "LONG" if spread_pct > 0 else "SHORT"
                    
#                     # Логіка базового входу або усереднення
#                     if not has_position and positions_check:
#                         # БАЗОВИЙ ВХІД: Відкриваємо нову позицію
#                         logging.info(f"[{symbol}] 🎯 БАЗОВИЙ ВХІД: spread={abs(spread_pct):.3f}% >= {MIN_SPREAD}%, баланс={available_balance:.4f} >= {required_margin:.4f}, позицій={total_positions} < {MAX_OPEN_POSITIONS}")

#                         # СТРОГА перевірка order book ліквідності з правильної біржі
#                         ok_liq = can_execute_on_orderbook(symbol, ORDER_AMOUNT, ORDER_BOOK_DEPTH, exchange=trading_exchange)
                        
#                         # 🔍 ДОДАТКОВА ПЕРЕВІРКА XT order book ліквідності (спеціальна для XT.com)
#                         if ok_liq and trading_exchange == "xt":
#                             # ВИПРАВЛЕНО: використовуємо notional size (маржа * леверидж) замість тільки маржі
#                             notional_size = ORDER_AMOUNT * LEVERAGE
#                             current_side = "LONG" if spread_pct > 0 else "SHORT"  # Явно визначаємо side
#                             can_trade_xt, xt_liquidity_info = analyze_xt_order_book_liquidity(xt, symbol, current_side, notional_size, min_liquidity_ratio=2.0)
#                             if not can_trade_xt:
#                                 logging.warning(f"[{symbol}] {xt_liquidity_info}")
#                                 ok_liq = False
#                             else:
#                                 logging.info(f"[{symbol}] {xt_liquidity_info}")
                        
#                         if ok_liq:
#                             # ПРИМУСОВЕ встановлення левериджу ПЕРЕД кожною угодою
#                             if trading_exchange == "xt":
#                                 try:
#                                     # Правильний виклик з positionSide
#                                     position_side = "LONG" if side == "LONG" else "SHORT"
#                                     xt.set_leverage(LEVERAGE, symbol, {"positionSide": position_side})
#                                     logging.info(f"[{symbol}] ⚙️ XT: ПРИМУСОВО встановлено леверидж {LEVERAGE}x ({position_side})")
#                                 except Exception as e:
#                                     logging.error(f"[{symbol}] ❌ Помилка встановлення левериджу XT: {e}")
#                                     # Не блокуємо торгівлю, продовжуємо
#                                     pass
                                    
#                                 # 🔒 ORDER PLACEMENT LOCK (Task 6: запобігаємо подвійним ордерам)
#                                 with order_placement_lock:
#                                     # 🎯 ПАРАЛЕЛЬНА ТОРГІВЛЯ НА ДВОХ АКАУНТАХ
#                                     order_account_1 = xt_open_market_position(xt_account_1, symbol, side, ORDER_AMOUNT, LEVERAGE, ref_price, dex_price, spread_pct)
#                                     order_account_2 = xt_open_market_position(xt_account_2, symbol, side, ORDER_AMOUNT, LEVERAGE, ref_price, dex_price, spread_pct)
#                                     # Вважаємо успішним якщо хоча б один акаунт відкрив позицію
#                                     order = order_account_1 or order_account_2
#                                     if order_account_1:
#                                         logging.info(f"[{symbol}] ✅ АКАУНТ 1: Відкрито {side} позицію з левериджем {LEVERAGE}x")
#                                     if order_account_2:
#                                         logging.info(f"[{symbol}] ✅ АКАУНТ 2: Відкрито {side} позицію з левериджем {LEVERAGE}x")
#                             else:
#                                 order = None
#                             if order:
#                                     logging.info(f"[{symbol}] 🚀 XT: Відкрито {side} позиції на обох акаунтах з левериджем {LEVERAGE}x")
#                             # ❌ GATE.IO ВІДКЛЮЧЕНО - тільки XT біржа!
#                             # else:  # gate (ВІДКЛЮЧЕНО)
#                             #     order = open_market_position(symbol, side, ORDER_AMOUNT, LEVERAGE, gate_price, dex_price, spread_pct)
#                             if order:
#                                 # Створюємо агреговану позицію
#                                 entry_price = ref_price  # Завжди XT ціна
#                                 # ФІКСОВАНА ЦІЛЬ: +30% прибутку з левериджем (як просив користувач)
#                                 if side == "LONG":
#                                     tp_price = entry_price * (1 + 0.30 / LEVERAGE)  # 30% прибутку з левериджем
#                                 else:  # SHORT
#                                     tp_price = entry_price * (1 - 0.30 / LEVERAGE)  # 30% прибутку з левериджем
#                                 position = {
#                                     "side": side,
#                                     "avg_entry": entry_price,
#                                     "size_usdt": ORDER_AMOUNT,
#                                     "adds_done": 0,
#                                     "last_add_price": entry_price,
#                                     "tp_price": tp_price,
#                                     "last_add_time": time.time(),
#                                     "exchange": trading_exchange,  # Запам'ятовуємо на якій біржі торгуємо
#                                     # 🎯 НОВІ ПОЛЯ ДЛЯ АВТОМАТИЧНОГО ЗАКРИТТЯ
#                                     "entry_time": time.time(),  # час входу в позицію
#                                     "arb_pair": f"{trading_exchange}-dex",  # тип арбітражу (gate-dex або xt-dex)
#                                     "entry_spread_pct": spread_pct,  # початковий спред
#                                     "entry_ref_price": dex_price,  # референтна ціна DEX на час входу
#                                     "status": "open"  # статус позиції (open/closing/closed)
#                                 }
#                                 # 🔒 ЗАХИСТ: Тільки для НОВИХ позицій встановлюємо таймери
#                                 current_time = time.time()
#                                 existing_position = active_positions.get(symbol, {})
#                                 if 'opened_at' not in existing_position or existing_position.get('opened_at', 0) <= 0:
#                                     position['opened_at'] = current_time
#                                 else:
#                                     position['opened_at'] = existing_position['opened_at']  # Зберігаємо існуючий!
#                                 if 'expires_at' not in existing_position or existing_position.get('expires_at', 0) <= 0:
#                                     position['expires_at'] = position['opened_at'] + POSITION_MAX_AGE_SEC
#                                 else:
#                                     position['expires_at'] = existing_position['expires_at']  # Зберігаємо існуючий!
#                                 position['xt_pair_url'] = generate_xt_pair_url(symbol)
                                
#                                 with active_positions_lock:
#                                     active_positions[symbol] = position
                                
#                                 # Зберігаємо оновлені позиції
#                                 save_positions_to_file()
                                
#                                 # 📱 ВІДПРАВЛЯЄМО ПРОФЕСІЙНЕ ПОВІДОМЛЕННЯ ПРО ВІДКРИТТЯ ПОЗИЦІЇ
#                                 try:
#                                     from telegram_formatter import format_position_opened_message
#                                     opened_message = format_position_opened_message(
#                                         symbol=symbol,
#                                         side=side,
#                                         entry_price=ref_price,
#                                         size_usd=ORDER_AMOUNT,
#                                         leverage=LEVERAGE,
#                                         spread_percent=spread_pct
#                                     )
#                                     send_to_admins_and_group(opened_message)
#                                     logging.info(f"📱 Відправлено Telegram про відкриття {symbol}")
#                                 except Exception as e:
#                                     logging.error(f"❌ Помилка відправки Telegram: {e}")
                                
#                                 logging.info("Opened %s on %s avg_entry=%.6f tp=%.6f", side, symbol, ref_price, tp_price)
                    
#                     elif has_position and AVERAGING_ENABLED:
#                         # 🔒 УСЕРЕДНЕННЯ: Отримуємо позицію з захистом
#                         with active_positions_lock:
#                             position = active_positions[symbol].copy()  # Копіюємо для уникнення змін під час роботи
#                         current_time = time.time()
#                         cooldown_passed = (current_time - position.get('last_add_time', 0)) >= AVERAGING_COOLDOWN_SEC
#                         can_add_more = position.get('adds_done', 0) < AVERAGING_MAX_ADDS
                        
#                         # 🔍 ДЕТАЛЬНЕ ЛОГУВАННЯ для діагностики
#                         logging.info(f"[{symbol}] 🔍 УСЕРЕДНЕННЯ ДІАГНОСТИКА: adds_done={position.get('adds_done', 0)}, max_adds={AVERAGING_MAX_ADDS}, can_add_more={can_add_more}, cooldown_passed={cooldown_passed}")
                        
#                         # Перевірка ліміту позиції на символ
#                         position_size_ok = position['size_usdt'] < MAX_POSITION_USDT_PER_SYMBOL
                        
#                         # 🎯 ЯВНА ПЕРЕВІРКА ВСІХ УМОВ для усереднення (як просив architect)
#                         if AVERAGING_ENABLED and can_add_more and cooldown_passed and position_size_ok:
#                             # Перевірка чи ціна йде проти позиції
#                             avg_entry = position['avg_entry']
#                             should_average = False
                            
#                             if position['side'] == "LONG" and side == "LONG":
#                                 # LONG позиція: усереднюємо якщо ціна впала
#                                 adverse_threshold = avg_entry * (1 - AVERAGING_THRESHOLD_PCT / 100)
#                                 should_average = xt_price <= adverse_threshold
#                             elif position['side'] == "SHORT" and side == "SHORT":
#                                 # SHORT позиція: усереднюємо якщо ціна виросла
#                                 adverse_threshold = avg_entry * (1 + AVERAGING_THRESHOLD_PCT / 100)
#                                 should_average = xt_price >= adverse_threshold
                            
#                             if should_average:
#                                 # 🎯 ЖОРСТКА ПЕРЕВІРКА ЛІМІТІВ: не перевищуємо MAX_POSITION_USDT_PER_SYMBOL
#                                 remaining_capacity = MAX_POSITION_USDT_PER_SYMBOL - position['size_usdt']
                                
#                                 if remaining_capacity <= 0:
#                                     logging.warning(f"[{symbol}] ❌ УСЕРЕДНЕННЯ ЗАБЛОКОВАНО: позиція досягла максимуму ${MAX_POSITION_USDT_PER_SYMBOL:.2f}, поточний розмір=${position['size_usdt']:.2f}")
#                                     continue  # Пропускаємо усереднення
                                
#                                 # 🛡️ ТОЧНИЙ РОЗРАХУНОК: використовуємо фіксований ORDER_AMOUNT, але перевіряємо ліміти
#                                 if remaining_capacity < ORDER_AMOUNT:
#                                     logging.warning(f"[{symbol}] ❌ УСЕРЕДНЕННЯ СКАСОВАНО: недостатньо місця для ORDER_AMOUNT=${ORDER_AMOUNT:.2f}, залишок=${remaining_capacity:.2f}")
#                                     continue
#                                 if available_balance < ORDER_AMOUNT:
#                                     logging.warning(f"[{symbol}] ❌ УСЕРЕДНЕННЯ СКАСОВАНО: недостатньо балансу для ORDER_AMOUNT=${ORDER_AMOUNT:.2f}, баланс=${available_balance:.2f}")
#                                     continue
                                
#                                 # 🎯 ЗАВЖДИ ВИКОРИСТОВУЄМО ФІКСОВАНИЙ ORDER_AMOUNT для консистентності
#                                 add_size = ORDER_AMOUNT
                                
#                                 logging.info(f"[{symbol}] 📈 УСЕРЕДНЕННЯ РОЗРАХУНОК: поточний_розмір=${position['size_usdt']:.2f}, макс=${MAX_POSITION_USDT_PER_SYMBOL:.2f}, залишок=${remaining_capacity:.2f}, додаємо=${add_size:.2f}")
                                
#                                 # УСЕРЕДНЕННЯ ТІЛЬКИ ЯКЩО Є ДОСТАТНЬО МІСЦЯ ТА БАЛАНСУ!
#                                 if add_size >= 1.0:  # Мінімум $1.00 для ордера
#                                     logging.info(f"[{symbol}] 📈 УСЕРЕДНЕННЯ: {position['side']} add_size=${add_size:.2f}, ціна={xt_price:.6f} vs avg={avg_entry:.6f}, спред={abs(spread_pct):.3f}%")
                                    
#                                     # Перевірка ліквідності для усереднення з правильної біржі
#                                     ok_liq = can_execute_on_orderbook(symbol, add_size, ORDER_BOOK_DEPTH, exchange=trading_exchange)
                                    
#                                     # 🔍 ДОДАТКОВА ПЕРЕВІРКА XT order book для усереднення
#                                     if ok_liq and trading_exchange == "xt":
#                                         # ВИПРАВЛЕНО: використовуємо notional size для усереднення
#                                         avg_notional_size = add_size * LEVERAGE
#                                         can_avg_xt, xt_avg_info = analyze_xt_order_book_liquidity(xt, symbol, position['side'], avg_notional_size, min_liquidity_ratio=2.0)
#                                         if not can_avg_xt:
#                                             logging.warning(f"[{symbol}] УСЕРЕДНЕННЯ: {xt_avg_info}")
#                                             ok_liq = False
#                                         else:
#                                             logging.info(f"[{symbol}] УСЕРЕДНЕННЯ: {xt_avg_info}")
                                    
#                                     if ok_liq:
#                                         # ПРИМУСОВЕ встановлення левериджу ПЕРЕД усередненням
#                                         if trading_exchange == "xt":
#                                             try:
#                                                 xt.set_leverage(LEVERAGE, symbol)
#                                                 logging.info(f"[{symbol}] ⚙️ XT: ПРИМУСОВО встановлено леверидж {LEVERAGE}x для усереднення")
#                                             except Exception as e:
#                                                 logging.error(f"[{symbol}] ❌ Помилка левериджу XT при усередненні: {e}")
#                                                 pass
                                                
#                                             # 🔒 ORDER PLACEMENT LOCK для усереднення (Task 6: запобігаємо конфліктним ордерам)
#                                             with order_placement_lock:
#                                                 order = xt_open_market_position(xt, symbol, position['side'], add_size, LEVERAGE, ref_price, dex_price, spread_pct)
#                                             current_price = ref_price  # Завжди XT ціна
#                                         else:
#                                             order = None
#                                             current_price = ref_price
#                                         # ❌ GATE.IO ВІДКЛЮЧЕНО - тільки XT біржа!
#                                         # else:  # gate (ВІДКЛЮЧЕНО)
#                                         #     order = open_market_position(symbol, position['side'], add_size, LEVERAGE, gate_price, dex_price, spread_pct)
#                                         if order:
#                                             # 🔒 Оновлення агрегованої позиції з захистом
#                                             with active_positions_lock:
#                                                 if symbol in active_positions:  # Перевіряємо що позиція ще існує
#                                                     current_position = active_positions[symbol]
#                                                     new_size = current_position['size_usdt'] + add_size
#                                                     new_avg_entry = (current_position['avg_entry'] * current_position['size_usdt'] + current_price * add_size) / new_size
#                                                 else:
#                                                     logging.warning(f"[{symbol}] Позиція не знайдена для усереднення")
#                                                     continue
#                                                     # ФІКСОВАНА ЦІЛЬ: +30% прибутку з левериджем (як просив користувач)
#                                                     if current_position['side'] == "LONG":
#                                                         new_tp_price = new_avg_entry * (1 + 0.30 / LEVERAGE)  # 30% прибутку з левериджем
#                                                     else:  # SHORT
#                                                         new_tp_price = new_avg_entry * (1 - 0.30 / LEVERAGE)  # 30% прибутку з левериджем
                                                    
#                                                     active_positions[symbol].update({
#                                                         'avg_entry': new_avg_entry,
#                                                         'size_usdt': new_size,
#                                                         'adds_done': current_position['adds_done'] + 1,
#                                                         'last_add_price': ref_price,
#                                                         'tp_price': new_tp_price,
#                                                         'last_add_time': current_time
#                                                     })
                                                    
#                                                     # 🔍 ДЕТАЛЬНЕ ЛОГУВАННЯ оновлення позиції  
#                                                     logging.info(f"✅ ПОЗИЦІЯ ОНОВЛЕНА: adds_done {current_position['adds_done']} -> {current_position['adds_done'] + 1}, розмір ${current_position['size_usdt']:.2f} -> ${new_size:.2f}")
                                            
#                                             # 🔍 ВИПРАВЛЕНО: використовуємо оновлене значення adds_done
#                                             updated_adds = current_position['adds_done'] + 1
#                                             logging.info(f"✅ УСЕРЕДНЕННЯ ЗАВЕРШЕНО {position['side']} на {symbol}: нова avg_entry={new_avg_entry:.6f}, розмір=${new_size:.2f}, додавань={updated_adds}/{AVERAGING_MAX_ADDS}")
#                 else:
#                     if not spread_check:
#                         logging.debug(f"[{symbol}] Спред {abs(spread_pct):.3f}% < {MIN_SPREAD}%")
#                     elif not positions_check and not has_position:
#                         logging.info(f"[{symbol}] ❌ Занадто багато позицій: {total_positions} >= {MAX_OPEN_POSITIONS}")
#                     elif not balance_check:
#                         logging.info(f"[{symbol}] ❌ Недостатньо балансу: потрібно {required_margin:.4f} USDT, є {available_balance:.4f} USDT")
#             except Exception as balance_error:
#                 logging.exception("Balance check error with full traceback")

#             # 4) 🔒 АВТОМАТИЧНЕ ЗАКРИТТЯ ПРИ СПРЕДІ 30% З ЗАХИСТОМ
#             with active_positions_lock:
#                 if symbol in active_positions:
#                     position = active_positions[symbol].copy()  # Копіюємо для роботи поза локом
#                 else:
#                     position = None
            
#             if position:
                
#                 # ✅ НОВІ УМОВИ ВИХОДУ (як просив користувач):
#                 # 1) Основна ціль: +30% прибутку
#                 # 2) При зникненні спреду: дострокове закриття на +10-15%
                
#                 current_price = ref_price  # Завжди XT ціна
#                 entry_price = position['avg_entry']
                
#                 # Розрахунок поточного P&L у відсотках
#                 if position['side'] == "LONG":
#                     pnl_pct = ((current_price - entry_price) / entry_price) * 100 * LEVERAGE
#                 else:  # SHORT  
#                     pnl_pct = ((entry_price - current_price) / entry_price) * 100 * LEVERAGE
                
#                 should_close = False
#                 close_reason = ""
                
#                 # 1) ОСНОВНА ЦІЛЬ: +30% прибутку (примусове закриття)
#                 if pnl_pct >= 30.0:
#                     should_close = True
#                     close_reason = f"🎯 ДОСЯГНУТО ЦІЛЬ +30%! P&L={pnl_pct:.1f}%"
                    
#                 # 2) ДОСТРОКОВЕ ЗАКРИТТЯ: спред зникає + прибуток 10-15%
#                 elif abs(spread_pct) < 0.3 and 10.0 <= pnl_pct < 30.0:  # спред < 0.3% вважається "зниклим"
#                     should_close = True
#                     close_reason = f"⚡ ДОСТРОКОВЕ ЗАКРИТТЯ: спред зник ({abs(spread_pct):.2f}% < 0.3%) + прибуток {pnl_pct:.1f}% (в межах 10-30%)"
                    
#                 # 3) ЗАХИСТ: спред > 30% (як було раніше)
#                 elif abs(spread_pct) >= 30.0:
#                     should_close = True 
#                     close_reason = f"🚨 АВАРІЙНЕ ЗАКРИТТЯ: спред {abs(spread_pct):.2f}% >= 30%"
                
#                 if should_close:
#                     logging.warning(f"🚨 АВТОЗАКРИТТЯ {position['side']} {symbol}: {close_reason}")
                    
#                     # БЕЗПЕЧНЕ ЗАКРИТТЯ: спочатку закриваємо на біржі, потім видаляємо з системи
#                     try:
#                         # Отримуємо свіжу ціну для точного закриття
#                         fresh_ticker = fetch_ticker(xt, symbol)
#                         if fresh_ticker:
#                             current_xt_price = float(fresh_ticker['last'])
#                         else:
#                             current_xt_price = ref_price  # fallback
                        
#                         # ПЕРЕВІРЯЄМО ЧИ ІСНУЄ ПОЗИЦІЯ ПЕРЕД ЗАКРИТТЯМ
#                         # Отримуємо свіжі позиції з біржі
#                         try:
#                             # 🔧 ВИКОРИСТОВУЄМО БЕЗПЕЧНИЙ WRAPPER
#                             # Gate.io відключено - використовуємо тільки XT  
#                             # Gate.io відключено - використовуємо тільки XT positions
#                             current_positions = []
#                             has_real_position = False
#                             for pos in current_positions:
#                                 if pos['symbol'] == symbol and float(pos.get('contracts', 0)) > 0:
#                                     has_real_position = True
#                                     break
                            
#                             if not has_real_position:
#                                 logging.warning(f"🚨 ПОЗИЦІЯ {symbol} УЖЕ ЗАКРИТА НА БІРЖІ - видаляємо з системи")
#                                 with active_positions_lock:
#                                     if symbol in active_positions:
#                                         del active_positions[symbol]
#                                 continue
#                         except:
#                             logging.warning(f"⚠️ Не вдалося перевірити позиції - пробуємо закрити")
                        
#                         # Пробуємо закрити позицію на біржі
#                         close_success = close_position_market(symbol, position['side'], position['size_usdt'])
                        
#                         if close_success:
#                             # 🔒 ТІЛЬКИ якщо закриття успішне - видаляємо з системи
#                             with active_positions_lock:
#                                 if symbol in active_positions:
#                                     del active_positions[symbol]
                            
#                             # ДОДАЄМО ДО ІСТОРІЇ ТОРГІВЛІ
#                             try:
#                                 import telegram_admin
#                                 telegram_admin.add_to_trade_history(
#                                     symbol=symbol,
#                                     side=position['side'],
#                                     entry_price=position['avg_entry'],
#                                     close_price=current_xt_price,
#                                     pnl=(position['size_usdt'] * pnl_pct / 100),
#                                     close_reason=close_reason,
#                                     exchange="Gate.io"
#                                 )
#                                 logging.info(f"📚 Додано до історії: {symbol} P&L={pnl_pct:+.1f}%")
#                             except Exception as history_error:
#                                 logging.error(f"❌ Помилка додавання до історії: {history_error}")
                            
#                             # Визначаємо емодзі результату
#                             if pnl_pct > 0:
#                                 result_emoji = "💚"
#                                 result_text = f"+${(position['size_usdt'] * pnl_pct / 100):+.2f}"
#                             elif pnl_pct < 0:
#                                 result_emoji = "❤️"
#                                 result_text = f"${(position['size_usdt'] * pnl_pct / 100):+.2f}"
#                             else:
#                                 result_emoji = "💙"
#                                 result_text = "$0.00"
                            
#                             # 🎯 РОЗШИРЕНЕ ДЕТАЛЬНЕ СПОВІЩЕННЯ ПРО АВТОЗАКРИТТЯ (як просив користувач!)
#                             close_signal = f"🎯 **АВТОЗАКРИТТЯ ПОЗИЦІЇ** {result_emoji}\n"\
#                                          f"📊 **{symbol.replace('/USDT:USDT', '')}** ({position['side']}) | ⚡ XT.COM\n"\
#                                          f"💰 Розмір: **${position['size_usdt']:.2f} USDT** | Леверидж: **{LEVERAGE}x**\n"\
#                                          f"📈 Вхід: **${position['avg_entry']:.6f}**\n"\
#                                          f"📉 Вихід: **${current_xt_price:.6f}**\n"\
#                                          f"💎 P&L: **{pnl_pct:+.1f}%** ({result_text})\n"\
#                                          f"📊 Спред: **{abs(spread_pct):.2f}%**\n"\
#                                          f"🎯 Причина: **{close_reason}**\n"\
#                                          f"⏰ Час: {datetime.now().strftime('%H:%M:%S')}\n"\
#                                          f"✅ Статус: **УСПІШНО ЗАКРИТО** | #ArbitrageBot"
                            
#                             # 📊 ПОЗИЦІЇ ОБОМ АДМІНАМ + ГРУПІ
#                             send_to_admins_and_group(close_signal)
#                             logging.info(f"✅ АВТОЗАКРИТО {position['side']} {symbol}: спред={abs(spread_pct):.2f}%, розмір=${position['size_usdt']:.2f}")
#                             continue  # Пропускаємо перевірку TP
#                         else:
#                             # 🔥 КРИТИЧНЕ ВИПРАВЛЕННЯ: НЕ відправляємо Telegram для нормальних помилок автозакриття
#                             logging.info(f"⚠️ Автозакриття {position['side']} {symbol} не вдалося - це може бути нормально (позиція вже закрита)")
#                             # Позиція залишається в active_positions для подальшого управління
                            
#                     except Exception as close_error:
#                         # 🔥 КРИТИЧНЕ ВИПРАВЛЕННЯ: Використовуємо ту саму логіку фільтрації як у close_position_market
#                         error_str = str(close_error).lower()
#                         normal_errors = [
#                             "reduce_exceeded", "empty position", "position not found",
#                             "insufficient margin", "position already closed", "order not found",
#                             "rate limit", "timeout", "connection", "network"
#                         ]
#                         is_normal_error = any(err in error_str for err in normal_errors)
                        
#                         if is_normal_error:
#                             logging.info(f"⚠️ Нормальна помилка автозакриття {symbol}: {error_str[:50]}... (без сповіщення)")
#                         else:
#                             logging.error(f"❌ КРИТИЧНА ПОМИЛКА при автозакритті {symbol}: {close_error}")
#                             # ТІЛЬКИ для справді критичних помилок відправляємо в Telegram
#                             error_signal = f"🚨 **КРИТИЧНА СИСТЕМНА ПОМИЛКА!**\n"\
#                                          f"📊 Символ: **{symbol.replace('/USDT:USDT', '')}** ({position['side']})\n"\
#                                          f"💰 Розмір позиції: **${position['size_usdt']:.2f}**\n"\
#                                          f"📈 Вхід: **${position['avg_entry']:.6f}**\n"\
#                                          f"📉 Поточна ціна: **${ref_price:.6f}**\n"\
#                                          f"📊 P&L: **{pnl_pct:+.1f}%**\n"\
#                                          f"⚠️ Спред: **{abs(spread_pct):.2f}%**\n"\
#                                          f"🎯 Причина: {close_reason}\n"\
#                                          f"❌ **ПОМИЛКА API**: `{str(close_error)[:100]}...`\n"\
#                                          f"🏪 Біржа: **{position.get('exchange', 'gate').upper()}**\n"\
#                                          f"⏰ Час: **{time.strftime('%H:%M:%S %d.%m.%Y')}**\n"\
#                                          f"🚨 **ТЕРМІНОВО ПОТРІБНЕ РУЧНЕ ВТРУЧАННЯ!**"
#                             # 🚨 КРИТИЧНІ ПОМИЛКИ ОБОМ АДМІНАМ + ГРУПІ
#                             send_to_admins_and_group(error_signal)
#                         # Позиція залишається в системі для подальшого управління
                
#                 # ВИДАЛЕНО: стара логіка 25% TP - замінена на нову логіку 30% вище

#         except Exception as e:
#             # ДЕТАЛЬНЕ ЛОГУВАННЯ ГЛОБАЛЬНИХ ПОМИЛОК ВОРКЕРА
#             error_msg = f"⚠️ **ПОМИЛКА ВОРКЕРА СИМВОЛУ**\n"\
#                        f"📊 Символ: **{symbol.replace('/USDT:USDT', '')}**\n"\
#                        f"❌ Помилка: `{str(e)[:150]}...`\n"\
#                        f"🔧 Воркер продовжує роботу через 30 сек\n"\
#                        f"⏰ Час: **{time.strftime('%H:%M:%S')}**"
#             # Відправляємо тільки у випадку серйозних помилок (не часті дрібниці)  
#             if "timeout" not in str(e).lower() and "rate limit" not in str(e).lower():
#                 # 🚨 ПОМИЛКИ ВОРКЕРА ОБОМ АДМІНАМ + ГРУПІ
#                 send_to_admins_and_group(error_msg)
#             logging.error("Symbol worker error %s %s", symbol, e)

#         # невелика пауза
#         time.sleep(SCAN_INTERVAL)

def send_balance_monitoring_thread():
    """Окремий потік для періодичного моніторингу балансу"""
    import threading
    import time
    
    def monitor_balance():
        while True:
            try:
                # Отримуємо баланс futures рахунку
                balance_data = get_xt_futures_balance(xt)
                if balance_data and isinstance(balance_data, dict) and balance_data.get('USDT'):
                    usdt_data = balance_data['USDT']
                    if isinstance(usdt_data, dict):
                        total = usdt_data.get('total', 0)
                        available = usdt_data.get('available', 0) 
                        used = usdt_data.get('used', 0)
                    else:
                        total = available = used = 0
                    
                    # Підрахунок активних позицій
                    try:
                        # 🔧 ВИКОРИСТОВУЄМО БЕЗПЕЧНИЙ WRAPPER  
                        # Use XT.com positions instead
                        active_positions_list = get_xt_open_positions(xt)
                        position_count = len([pos for pos in active_positions_list if float(pos.get('contracts', 0)) > 0])
                    except:
                        position_count = 0
                    
                    # Send balance update via telegram (using simple send_telegram)
                    balance_msg = f"💰 Баланс XT.com:\n• Загалом: {total:.2f} USDT\n• Доступно: {available:.2f} USDT\n• У позиціях: {used:.2f} USDT\n• Позицій: {position_count}"
                    send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, balance_msg)
                    
                time.sleep(300)  # Кожні 5 хвилин
            except Exception as e:
                logging.error(f"Balance monitoring error: {e}")
                time.sleep(60)  # При помилці - через хвилину
    
    balance_thread = threading.Thread(target=monitor_balance, daemon=True)
    balance_thread.start()
    logging.info("Balance monitoring thread started")

def start_position_monitoring_thread():
    """🎯 ЗАХИЩЕНА СИСТЕМА АВТОМАТИЧНОГО ЗАКРИТТЯ ПОЗИЦІЙ"""
    return start_monitor()  # 🛡️ Делегуємо новій захищеній функції

def start_monitor():
    """🛡️ THREAD-SAFE ЗАХИЩЕНИЙ ЗАПУСК МОНІТОРИНГУ (ідемпотентний)"""
    global monitor_thread
    
    with monitor_lifecycle_lock:  # 🔒 SINGLE-INSTANCE PROTECTION
        logging.warning("🚀 PROTECTED MONITOR: Запуск thread-safe системи моніторингу...")
        
        # 🛡️ IDEMPOTENT CHECK: перевіряємо чи не запущений вже
        if monitor_thread and monitor_thread.is_alive():
            logging.warning(f"🎯 Моніторинг вже запущений (thread-{monitor_thread.ident}), пропускаємо")
            return monitor_thread
        
        # 🎯 CLEAN START: переконуємося що Event скинутий
        if monitor_stop_event.is_set():
            monitor_stop_event.clear()
            logging.info("🔄 Event скинутий для нового старту")
        
        # 🚀 LAUNCH: запускаємо новий потік з унікальним іменем
        monitor_thread = threading.Thread(
            target=monitor_open_positions, 
            daemon=True,
            name="MonitorThread"
        )
        monitor_thread.start()
        
        logging.warning(f"✅ PROTECTED MONITOR: Thread-safe моніторинг запущено! (thread-{monitor_thread.ident})")
        logging.info(f"   • Take Profit: +{TAKE_PROFIT_PCT}%")
        logging.info(f"   • Конвергенція: ≤{CONVERGENCE_SPREAD_PCT}%")
        logging.info(f"   • Таймер: {POSITION_MAX_AGE_SEC}с")
        logging.info(f"   • Інтервал: {MONITOR_INTERVAL_SEC}с")
        
        return monitor_thread

# def close_position_by_contracts(exchange, symbol, contracts, side):
#     """Закриває позицію за кількістю контрактів (НЕ USD!)"""
#     if DRY_RUN:
#         logging.info(f"DRY RUN: закрити {contracts} контрактів {symbol} {side}")
#         return
    
#     try:
#         # Визначаємо протилежну сторону
#         opposite_side = 'sell' if side.upper() == 'LONG' else 'buy'
        
#         # Розміщуємо ринковий ордер на закриття
#         order = exchange.create_market_order(symbol, opposite_side, contracts)
#         logging.info(f"✅ Закрито позицію: {symbol} {contracts} контрактів ({opposite_side})")
#         return order
        
#     except Exception as e:
#         logging.error(f"❌ Помилка закриття позиції {symbol}: {e}")
#         raise

# def start_workers():
#     global _plot_thread, worker_threads # ⬅️ ЗМІНЕНО: переконуємося, що worker_threads глобальний
#     logging.info("🚨 DEBUG: start_workers() ВИКЛИКАЄТЬСЯ!")
    
#     # 🎯 КРИТИЧНО: Запускаємо моніторинг ПЕРШИМ (до всіх інших ініціалізацій)
#     try:
#         logging.info("🚨 DEBUG: ПРІОРИТЕТ 1 - Запуск моніторингу позицій...")
#         logging.info("🎯 СТАРТ: Готуюся запустити моніторинг позицій...")
#         start_position_monitoring_thread()
#         logging.info("🎯 СТАРТ: Моніторинг позицій запущений успішно!")
#     except Exception as e:
#         logging.error(f"🚨 DEBUG: ПОМИЛКА в start_position_monitoring_thread(): {e}")
#         # Не raise - продовжуємо навіть якщо моніторинг не запустився
    
#     try:
#         logging.info("🚨 DEBUG: Початок init_markets()...")
#         init_markets()
#         logging.info("🚨 DEBUG: init_markets() завершено!")
#     except Exception as e:
#         logging.error(f"🚨 DEBUG: ПОМИЛКА в init_markets(): {e}")
#         raise
    
#     try:
#         logging.info("🚨 DEBUG: Початок send_balance_monitoring_thread()...")
#         # Запуск моніторингу балансу
#         send_balance_monitoring_thread()
#         logging.info("🚨 DEBUG: send_balance_monitoring_thread() завершено!")
#     except Exception as e:
#         logging.error(f"🚨 DEBUG: ПОМИЛКА в send_balance_monitoring_thread(): {e}")
#         raise
    
#     # 🎯 ЗАПУСК: Нова система найкращих сигналів (замість багатьох)
#     best_signal_thread = threading.Thread(target=send_best_opportunity_signal, daemon=True)
#     best_signal_thread.start()
#     logging.info("🏆 СТАРТ: Система ОДНОГО найкращого сигналу запущена!")
    
#     # старт plot треда
#     _plot_thread = threading.Thread(target=plot_spread_live, args=(spread_store,), daemon=True)
#     _plot_thread.start()

#     # 🚀 ВИПРАВЛЕНО: Батч-обробка ВСІХ 733 пар по 50 паралельно
#     # ⬅️ ЗМІНЕНО: Додано головний цикл while bot_running:
#     while bot_running:
#         try:
#             symbols = list(markets.keys())
#             batch_size = MAX_CONCURRENT_SYMBOLS
#             total_symbols = len(symbols)
            
#             logging.info(f"🔄 РОЗПОЧИНАЄМО НОВИЙ ЦИКЛ СКАНУВАННЯ: {total_symbols} символів, батчами по {batch_size}")
            
#             # 🧹 Очищаємо глобальний список воркерів перед новим циклом
#             worker_threads = [] 
            
#             # Розбиваємо символи на батчі
#             for batch_start in range(0, total_symbols, batch_size):
#                 if not bot_running: # ⬅️ ДОДАНО: Перевірка зупинки між батчами
#                     logging.info("🔴 Отримано сигнал зупинки, перериваємо цикл сканування.")
#                     break
                    
#                 batch_end = min(batch_start + batch_size, total_symbols)
#                 batch_symbols = symbols[batch_start:batch_end]
                
#                 logging.info(f"📦 Батч {batch_start//batch_size + 1}: запускаємо {len(batch_symbols)} символів (від {batch_start} до {batch_end-1})")
                
#                 current_batch_threads = [] # ⬅️ ДОДАНО: Локальний список для очікування
                
#                 # Запускаємо всі символи з поточного батчу
#                 for sym in batch_symbols:
#                     if not bot_running: break # ⬅️ ДОДАНО: Перевірка зупинки під час запуску
#                     t = threading.Thread(target=symbol_worker, args=(sym,), daemon=True)
#                     t.start()
#                     worker_threads.append(t) # ⬅️ ДОДАНО: Для функції stop_all_workers
#                     current_batch_threads.append(t) # ⬅️ ДОДАНО: Для .join()
#                     # ⛔️ ВИДАЛЕНО: time.sleep(1) (це занадто повільно для запуску батчу)
                
#                 # ⏳ ЧЕКАЄМО ЗАВЕРШЕННЯ ПОТОЧНОГО БАТЧУ 
#                 logging.info(f"⏳ Очікуємо завершення {len(current_batch_threads)} воркерів з батчу...")
#                 for t in current_batch_threads:
#                     if not bot_running: break # ⬅️ ДОДАНО: Можна перервати очікування
#                     t.join() # ⬅️ ДОДАНО: Чекаємо, поки воркер завершить 1 прохід
                
#                 if not bot_running: break # ⬅️ ДОДАНО: Вихід з циклу батчів
                
#                 logging.info(f"✅ Батч {batch_start//batch_size + 1} завершено.")

#                 # Чекаємо трохи між батчами для розподілу навантаження
#                 if batch_end < total_symbols and bot_running:
#                     logging.info(f"⏸️  Пауза 5 секунди між батчами...")
#                     monitor_stop_event.wait(timeout=5) # ⬅️ ЗМІНЕНО: Використовуємо .wait() для швидкої зупинки
            
#             if not bot_running:
#                 logging.info("🔴 Цикл сканування зупинено.")
#                 break # Вихід з головного циклу while

#             logging.info(f"✅✅✅ УСІ БАТЧІ ЗАВЕРШЕНО. Повний цикл сканування завершено.")
#             logging.info(f"🔄 Пауза 30 секунд перед початком нового циклу сканування...")
            
#             # ⬅️ ДОДАНО: Пауза 60 секунд перед новим повним скануванням
#             monitor_stop_event.wait(timeout=30) 

#         except Exception as e:
#             logging.error(f"❌ КРИТИЧНА ПОМИЛКА в головному циклі start_workers: {e}")
#             logging.info("Пауза 30 секунд після помилки...")
#             if bot_running:
#                 monitor_stop_event.wait(timeout=30) # ⬅️ ЗМІНЕНО: Пауза на випадок помилки

def start_workers():
    global _plot_thread, worker_threads # ⬅️ ЗМІНЕНО: переконуємося, що worker_threads глобальний
    logging.info("🚨 DEBUG: start_workers() ВИКЛИКАЄТЬСЯ!")
    
    # 🎯 КРИТИЧНО: Запускаємо моніторинг ПЕРШИМ (до всіх інших ініціалізацій)
    try:
        logging.info("🚨 DEBUG: ПРІОРИТЕТ 1 - Запуск моніторингу позицій...")
        logging.info("🎯 СТАРТ: Готуюся запустити моніторинг позицій...")
        start_position_monitoring_thread()
        logging.info("🎯 СТАРТ: Моніторинг позицій запущений успішно!")
    except Exception as e:
        logging.error(f"🚨 DEBUG: ПОМИЛКА в start_position_monitoring_thread(): {e}")
        # Не raise - продовжуємо навіть якщо моніторинг не запустився
    
    try:
        logging.info("🚨 DEBUG: Початок init_markets()...")
        init_markets()
        logging.info("🚨 DEBUG: init_markets() завершено!")
    except Exception as e:
        logging.error(f"🚨 DEBUG: ПОМИЛКА в init_markets(): {e}")
        raise
    
    try:
        logging.info("🚨 DEBUG: Початок send_balance_monitoring_thread()...")
        # Запуск моніторингу балансу
        send_balance_monitoring_thread()
        logging.info("🚨 DEBUG: send_balance_monitoring_thread() завершено!")
    except Exception as e:
        logging.error(f"🚨 DEBUG: ПОМИЛКА в send_balance_monitoring_thread(): {e}")
        raise
    
    # 🎯 ЗАПУСК: Нова система найкращих сигналів (замість багатьох)
    best_signal_thread = threading.Thread(target=send_best_opportunity_signal, daemon=True)
    best_signal_thread.start()
    logging.info("🏆 СТАРТ: Система ОДНОГО найкращого сигналу запущена!")
    
    # старт plot треда
    _plot_thread = threading.Thread(target=plot_spread_live, args=(spread_store,), daemon=True)
    _plot_thread.start()

    # 🚀 ВИПРАВЛЕНО: Батч-обробка ВСІХ 733 пар по 50 паралельно
    # ⬅️ ЗМІНЕНО: Додано головний цикл while bot_running:
    while bot_running:
        try:
            symbols = list(markets.keys())
            batch_size = MAX_CONCURRENT_SYMBOLS
            total_symbols = len(symbols)
            
            logging.info(f"🔄 РОЗПОЧИНАЄМО НОВИЙ ЦИКЛ СКАНУВАННЯ: {total_symbols} символів, батчами по {batch_size}")
            
            # 🧹 Очищаємо глобальний список воркерів перед новим циклом
            worker_threads = [] 
            
            # Розбиваємо символи на батчі
            for batch_start in range(0, total_symbols, batch_size):
                if not bot_running: # ⬅️ ДОДАНО: Перевірка зупинки між батчами
                    logging.info("🔴 Отримано сигнал зупинки, перериваємо цикл сканування.")
                    break
                    
                batch_end = min(batch_start + batch_size, total_symbols)
                batch_symbols = symbols[batch_start:batch_end]
                
                logging.info(f"📦 Батч {batch_start//batch_size + 1}: запускаємо {len(batch_symbols)} символів (від {batch_start} до {batch_end-1})")
                
                current_batch_threads = [] # ⬅️ ДОДАНО: Локальний список для очікування
                
                # Запускаємо всі символи з поточного батчу
                for sym in batch_symbols:
                    if not bot_running: break # ⬅️ ДОДАНО: Перевірка зупинки під час запуску
                    t = threading.Thread(target=symbol_worker, args=(sym,), daemon=True)
                    t.start()
                    worker_threads.append(t) # ⬅️ ДОДАНО: Для функції stop_all_workers
                    current_batch_threads.append(t) # ⬅️ ДОДАНО: Для .join()
                    # ⛔️ ВИДАЛЕНО: time.sleep(1) (це занадто повільно для запуску батчу)
                
                # ⏳ ЧЕКАЄМО ЗАВЕРШЕННЯ ПОТОЧНОГО БАТЧУ 
                logging.info(f"⏳ Очікуємо завершення {len(current_batch_threads)} воркерів з батчу...")
                for t in current_batch_threads:
                    if not bot_running: break # ⬅️ ДОДАНО: Можна перервати очікування
                    
                    t.join(timeout=60.0) # ⬅️ НОВИЙ КОД: Чекаємо максимум 60 секунд
                
                if not bot_running: break # ⬅️ ДОДАНО: Вихід з циклу батчів
                
                logging.info(f"✅ Батч {batch_start//batch_size + 1} завершено.")

                # Чекаємо трохи між батчами для розподілу навантаження
                if batch_end < total_symbols and bot_running:
                    logging.info(f"⏸️  Пауза 5 секунди між батчами...")
                    monitor_stop_event.wait(timeout=5) # ⬅️ ЗМІНЕНО: Використовуємо .wait() для швидкої зупинки
            
            if not bot_running:
                logging.info("🔴 Цикл сканування зупинено.")
                break # Вихід з головного циклу while

            logging.info(f"✅✅✅ УСІ БАТЧІ ЗАВЕРШЕНО. Повний цикл сканування завершено.")
            logging.info(f"🔄 Пауза 30 секунд перед початком нового циклу сканування...")
            
            # ⬅️ ДОДАНО: Пауза 30 секунд перед новим повним скануванням
            monitor_stop_event.wait(timeout=30) 

        except Exception as e:
            logging.error(f"❌ КРИТИЧНА ПОМИЛКА в головному циклі start_workers: {e}")
            logging.info("Пауза 30 секунд після помилки...")
            if bot_running:
                monitor_stop_event.wait(timeout=30) # ⬅️ ЗМІНЕНО: Пауза на випадок помилки

# def start_workers():
#     global _plot_thread
#     logging.info("🚨 DEBUG: start_workers() ВИКЛИКАЄТЬСЯ!")
    
#     # 🎯 КРИТИЧНО: Запускаємо моніторинг ПЕРШИМ (до всіх інших ініціалізацій)
#     try:
#         logging.info("🚨 DEBUG: ПРІОРИТЕТ 1 - Запуск моніторингу позицій...")
#         logging.info("🎯 СТАРТ: Готуюся запустити моніторинг позицій...")
#         start_position_monitoring_thread()
#         logging.info("🎯 СТАРТ: Моніторинг позицій запущений успішно!")
#     except Exception as e:
#         logging.error(f"🚨 DEBUG: ПОМИЛКА в start_position_monitoring_thread(): {e}")
#         # Не raise - продовжуємо навіть якщо моніторинг не запустився
    
#     try:
#         logging.info("🚨 DEBUG: Початок init_markets()...")
#         init_markets()
#         logging.info("🚨 DEBUG: init_markets() завершено!")
#     except Exception as e:
#         logging.error(f"🚨 DEBUG: ПОМИЛКА в init_markets(): {e}")
#         raise
    
#     try:
#         logging.info("🚨 DEBUG: Початок send_balance_monitoring_thread()...")
#         # Запуск моніторингу балансу
#         send_balance_monitoring_thread()
#         logging.info("🚨 DEBUG: send_balance_monitoring_thread() завершено!")
#     except Exception as e:
#         logging.error(f"🚨 DEBUG: ПОМИЛКА в send_balance_monitoring_thread(): {e}")
#         raise
    
#     # 🎯 ЗАПУСК: Нова система найкращих сигналів (замість багатьох)
#     best_signal_thread = threading.Thread(target=send_best_opportunity_signal, daemon=True)
#     best_signal_thread.start()
#     logging.info("🏆 СТАРТ: Система ОДНОГО найкращого сигналу запущена!")
    
#     # старт plot треда
#     _plot_thread = threading.Thread(target=plot_spread_live, args=(spread_store,), daemon=True)
#     _plot_thread.start()

#     # 🚀 ВИПРАВЛЕНО: Батч-обробка ВСІХ 733 пар по 50 паралельно
#     # Замість обмеження активних потоків, розбиваємо на батчі
#     symbols = list(markets.keys())
#     batch_size = MAX_CONCURRENT_SYMBOLS
#     total_symbols = len(symbols)
    
#     logging.info(f"🚀 Запускаємо {total_symbols} символів батчами по {batch_size}")
    
#     # Розбиваємо символи на батчі
#     for batch_start in range(0, total_symbols, batch_size):
#         batch_end = min(batch_start + batch_size, total_symbols)
#         batch_symbols = symbols[batch_start:batch_end]
        
#         logging.info(f"📦 Батч {batch_start//batch_size + 1}: запускаємо {len(batch_symbols)} символів (від {batch_start} до {batch_end-1})")
        
#         # Запускаємо всі символи з поточного батчу
#         for sym in batch_symbols:
#             t = threading.Thread(target=symbol_worker, args=(sym,), daemon=True)
#             t.start()
#             worker_threads.append(t)
#             time.sleep(1)  # Невелика затримка між запусками
#         # Чекаємо трохи між батчами для розподілу навантаження
#         if batch_end < total_symbols:
#             logging.info(f"⏸️  Пауза 10 секунди між батчами...")
#             time.sleep(10)

if __name__ == "__main__":
    test_telegram_configuration()  # Тестуємо Telegram перед стартом
    
    # 💾 ЗАВАНТАЖУЄМО ЗБЕРЕЖЕНІ ПОЗИЦІЇ при старті
    logging.info("💾 Завантаження збережених позицій...")
    load_positions_from_file()

    logging.info("💾 Завантаження чорного списку...")
    load_blacklist()
    # 🤖 Запуск Telegram адмін-бота в окремому процесі
    try:
        from multiprocessing import Process
        telegram_process = Process(target=run_telegram_bot)
        telegram_process.start()
        logging.info("🤖 Запуск Telegram бота в окремому процесі...")
    except ImportError:
        logging.warning("❌ Telegram admin bot недоступний")
    
    # 🎯 ВЕБІНТЕРФЕЙС ВІДКЛЮЧЕНО ДЛЯ ПОТУЖНОСТІ (користувач не просив)
    try:
        try:
            # from admin import create_admin_app  # ВІДКЛЮЧЕНО
            # admin_app = create_admin_app()  # ВІДКЛЮЧЕНО
            from threading import Thread
            # admin_thread = Thread(target=lambda: admin_app.run(host='0.0.0.0', port=5000, debug=False))  # ВІДКЛЮЧЕНО
            # admin_thread.daemon = True  # ВІДКЛЮЧЕНО (admin_thread не створюється)
            # admin_thread.start()  # ВІДКЛЮЧЕНО: тільки Telegram бот
            logging.info("📱 Працює тільки Telegram бот (веб інтерфейс відключено)")
        except ImportError:
            logging.warning("❌ Admin module недоступний")
    except Exception as e:
        logging.warning(f"❌ Flask адмін панель недоступна: {e}")
        
    start_workers()
