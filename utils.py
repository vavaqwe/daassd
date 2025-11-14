import logging
import requests
import matplotlib.pyplot as plt
import threading
import time
import json
from datetime import datetime
from typing import Optional

# 🔗 НОВА ІНТЕГРАЦІЯ: DEX Link Generator для прямих посилань на торгові пари
# Simple fallback instead of dex_link_generator

# Configure logging and HIDE sensitive HTTP requests with tokens
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# CRITICAL SECURITY: Hide HTTP requests with tokens from urllib3, httpx, and telegram library
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING) 
logging.getLogger('telegram').setLevel(logging.WARNING)
logging.getLogger('telegram.ext').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('requests').setLevel(logging.WARNING)

def calculate_spread(dex_price, xt_price, fee=0.06):
    # повертає відсотковий spread (в %)
    try:
        return ((dex_price - xt_price) / dex_price * 100.0) - fee
    except Exception:
        return 0.0

# Простий plotting (в окремому треді) - відключено в Replit
_plot_lock = threading.Lock()
def plot_spread_live(spread_store):
    # Matplotlib plotting відключено для уникнення GUI проблем у веб-середовищі
    logging.info("Plotting thread started (GUI disabled for web environment)")
    while True:
        time.sleep(5)  # просто тримаємо тред живим

def send_telegram(bot_token, chat_id, text):
    """Базова функція відправки в телеграм з детальною діагностикою"""
    if not bot_token:
        logging.warning("❌ TELEGRAM: Bot token не налаштований")
        return False
    if not chat_id:
        logging.warning(f"❌ TELEGRAM: Chat ID порожній, пропускаємо відправку")
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        # Обмежуємо довжину повідомлення
        if len(text) > 4000:
            text = text[:4000] + "..."
        
        # Відправляємо запит з HTML форматом БЕЗ web page preview
        response = requests.post(url, data={
            "chat_id": chat_id, 
            "text": text, 
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                logging.info(f"✅ Telegram повідомлення відправлено до chat_id={chat_id}")
                return True
            else:
                # Логуємо помилки Telegram API для діагностики
                logging.error(f"❌ Telegram API error для chat_id={chat_id}: {result}")
                return False
        else:
            # Логуємо HTTP помилки Telegram для діагностики
            logging.error(f"❌ Telegram HTTP error {response.status_code} для chat_id={chat_id}: {response.text[:200]}")
            return False
            
    except Exception as e:
        # Логуємо мережеві помилки Telegram для діагностики
        logging.error(f"❌ Telegram network error для chat_id={chat_id}: {str(e)}")
        return False

def send_to_admins_and_group(text):
    """
    🎯 ЦЕНТРАЛІЗОВАНА ФУНКЦІЯ: Відправляє повідомлення обом адмінам + групі
    Гарантує що всі адміністратори та група отримають однакові повідомлення
    """
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_ADMIN_2_ID, TELEGRAM_GROUP_CHAT_ID
    
    results = []
    
    # Відправляємо адміну 1
    if TELEGRAM_CHAT_ID:
        result = send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, text)
        results.append(("Адмін 1", result))
        
    # Відправляємо адміну 2
    if TELEGRAM_ADMIN_2_ID:
        result = send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_2_ID, text)
        results.append(("Адмін 2", result))
        
    # Відправляємо в групу
    if TELEGRAM_GROUP_CHAT_ID:
        result = send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_CHAT_ID, text)
        results.append(("Група", result))
        
    # Логуємо результати
    successful = sum(1 for _, success in results if success)
    logging.info(f"📤 Відправлено {successful}/{len(results)} повідомлень (Адміни + Група)")
    
    return any(success for _, success in results)  # True якщо хоча б одне відправилось

def send_telegram_trade_notification(symbol, side, amount, price, profit=None, action="OPENED", spread=None, exchange_price=None, dex_price=None):
    """Відправляє сповіщення про торгові операції обом адмінам + групі через централізовану функцію"""
    
    # Визначаємо біржу з action
    exchange_name = "🌐 Gate.io"
    if "(XT)" in action:
        exchange_name = "⚡ XT.COM"
    
    # 🚨 ДЕТАЛЬНИЙ ФОРМАТ сигналу як у прикладі користувача
    if action.startswith("OPENED"):
        clean_symbol = symbol.replace('/USDT:USDT', '')
        
        # Розраховуємо торгові параметри
        leverage = 7  # Плече 7x як у користувача
        margin = 5.0  # Фіксована маржа $5
        
        # Захист від None значень
        if exchange_price is None or dex_price is None:
            exchange_price = price if price else 1.0
            dex_price = price if price else 1.0
        if spread is None:
            spread = 1.0
            
        # Розраховуємо TP/SL/R&R
        if side == "LONG":
            tp_price = exchange_price * 1.017  # TP +1.7%
            sl_price = exchange_price * 0.90   # SL -10%
        else:
            tp_price = exchange_price * 0.983  # TP -1.7%
            sl_price = exchange_price * 1.10   # SL +10%
            
        tp_percent = ((tp_price - exchange_price) / exchange_price) * 100
        sl_percent = ((sl_price - exchange_price) / exchange_price) * 100
        risk_reward = abs(tp_percent) / abs(sl_percent) if abs(sl_percent) > 0 else 0.17
        
        # Визначаємо рівень ризику
        if abs(spread) >= 2.0:
            risk_level = "🟡 СЕРЕДНІЙ"
        elif abs(spread) >= 1.5:
            risk_level = "🟢 НИЗЬКИЙ"
        else:
            risk_level = "🔴 ВИСОКИЙ"
        
        # Формуємо повідомлення про відкриття позиції
        text = "💰 <b>ПОЗИЦІЯ ВІДКРИТА</b> 💰\n\n"
        text += f"📊 <b>{clean_symbol}</b> {side}\n"
        text += f"🎯 <b>XT.COM</b>: ${exchange_price:.6f}\n"
        text += f"📊 <b>DexScreener</b>: ${dex_price:.6f}\n"
        text += f"💎 <b>Спред</b>: +{abs(spread):.2f}%\n\n"
        
        text += "📈 <b>ТОРГОВІ НАЛАШТУВАННЯ</b>\n"
        text += f"⚡ Плече: {leverage}x\n"
        text += f"💵 Розмір: ${margin:.1f}\n"
        text += f"🎯 TP: ${tp_price:.6f} ({tp_percent:+.1f}%)\n"
        text += f"🛑 SL: ${sl_price:.6f} ({sl_percent:+.1f}%)\n"
        text += f"⚖️ R/R: {risk_reward:.2f}\n"
        text += f"🔥 Ризик: {risk_level}\n\n"
        
        # Додаємо ліквідність та обсяг якщо є
        try:
            dex_pair_info = get_exact_dex_pair_info(symbol)
            if dex_pair_info:
                liquidity = dex_pair_info.get('liquidity_usd', 0)
                volume_24h = dex_pair_info.get('volume_24h', 0)
                text += f"💧 Ліквідність: ${liquidity:,.0f}\n"
                text += f"📊 Обсяг 24г: ${volume_24h:,.0f}\n\n"
        except:
            pass
            
        # 🚀 НОВА СИСТЕМА DEX ПОСИЛАНЬ: Додаємо прямі посилання на топові DEX
        text += f"🔗 <b>ТОРГІВЛЯ:</b>\n"
        text += f"• <a href=\"{xt_pair_link(symbol)}\">📊 XT Торгувати</a>\n"
        
        # Генеруємо топові DEX посилання
        try:
            # Спробуємо отримати адреси токена
            exact_pair_info = get_exact_dex_pair_info(symbol)
            token_addresses = {}
            
            if exact_pair_info and exact_pair_info.get('token_address') and exact_pair_info.get('chain_name'):
                chain = exact_pair_info['chain_name'].lower()
                token_addresses[chain] = exact_pair_info['token_address']
            
            # Якщо немає точних даних, пробуємо token_addresses.json
            if not token_addresses:
                try:
                    with open('token_addresses.json', 'r', encoding='utf-8') as f:
                        token_data = json.load(f)
                        token_info = token_data.get(clean_symbol, {})
                        if token_info.get('address') and token_info.get('chain'):
                            token_addresses[token_info['chain']] = token_info['address']
                except Exception:
                    pass
            
            # 🎯 ПРОСТИЙ DEX LINK: базовий fallback без додаткових модулів
            if token_addresses:
                # Простий fallback: використовуємо DexScreener
                try:
                    exact_pair_info = get_exact_dex_pair_info(symbol)
                    if exact_pair_info and exact_pair_info.get('exact_pair_url'):
                        text += f"• <a href=\"{exact_pair_info['exact_pair_url']}\">📈 DexScreener - ПАРА</a>\n"
                    else:
                        dexscreener_link = get_proper_dexscreener_link(clean_symbol)
                        text += f"• <a href=\"{dexscreener_link}\">📈 DexScreener</a>\n"
                except Exception:
                    dexscreener_link = get_proper_dexscreener_link(clean_symbol)
                    text += f"• <a href=\"{dexscreener_link}\">📈 DexScreener</a>\n"
            else:
                # Fallback до DexScreener якщо немає адрес токена
                dexscreener_link = get_proper_dexscreener_link(clean_symbol)
                text += f"• <a href=\"{dexscreener_link}\">📈 DexScreener</a>\n"
                
        except Exception as e:
            logging.error(f"❌ Помилка генерації DEX посилань: {e}")
            # Безпечний fallback
            dexscreener_link = get_proper_dexscreener_link(clean_symbol)
            text += f"• <a href=\"{dexscreener_link}\">📈 DexScreener</a>\n"
        
        text += "\n"
        
        # Додаємо інформацію про відкриття
        import time
        text += f"⚡ <b>Біржа:</b> {exchange_name}\n"
        text += f"💰 <b>Маржа:</b> ${margin:.2f}\n"  
        text += f"⏰ <b>Час:</b> {time.strftime('%H:%M:%S')}\n"
        text += f"✅ <b>Статус:</b> ПОЗИЦІЯ ВІДКРИТА"
        
        # ✅ ЦЕНТРАЛІЗОВАНА ВІДПРАВКА: обом адмінам + групі
        send_to_admins_and_group(text)
        
    elif action.startswith("CLOSED"):
        clean_symbol = symbol.replace('/USDT:USDT', '')
        
        # 🔥 ВИПРАВЛЕННЯ P&L: використовуємо реальні дані якщо є, інакше передані параметри
        if profit is not None:
            # Якщо profit передано, розраховуємо відсоток від суми
            profit_pct = (profit / amount) * 100 if amount > 0 and profit != 0 else 0.0
            profit_dollars = profit
        else:
            # Якщо profit не передано, встановлюємо 0
            profit_pct = 0.0
            profit_dollars = 0.0
            
        # Визначаємо емодзі та текст результату
        if profit_dollars > 0:
            result_emoji = "💚"
            result_text = f"+${profit_dollars:.2f}"
        elif profit_dollars < 0:
            result_emoji = "❤️" 
            result_text = f"${profit_dollars:.2f}"
        else:
            result_emoji = "💙"
            result_text = "$0.00"
            
        # 🎯 ПОВНОЦІННИЙ ДЕТАЛЬНИЙ ФОРМАТ ЗАКРИТТЯ (як запитав користувач!)
        text = f"🏁 **ПОЗИЦІЯ ЗАКРИТА** {result_emoji}\n"
        text += f"📊 **{clean_symbol}** ({side.upper() if side else '—'}) | {exchange_name}\n"
        text += f"💰 Розмір: **${amount:.2f} USDT**\n"
        text += f"📈 Ціна закриття: **${price:.6f}**\n"
        text += f"💎 P&L: **{profit_pct:+.1f}%** ({result_text})\n"
        
        # Додаємо спред якщо є
        if spread is not None:
            text += f"📊 Спред: **{abs(spread):.2f}%**\n"
            
        # Додаємо порівняння цін якщо є
        if exchange_price and dex_price:
            exchange_short = "XT" if "(XT)" in action else exchange_name
            text += f"⚖️ {exchange_short}: ${exchange_price:.3f} | DEX: ${dex_price:.3f}\n"
            
        # Завершення з хештегом  
        text += f"✅ Статус: **УСПІШНО ЗАКРИТО** | #ArbitrageBot"
        
        # ✅ ЦЕНТРАЛІЗОВАНА ВІДПРАВКА: обом адмінам + групі
        send_to_admins_and_group(text)


def generate_crypto_signal(symbol, side, entry_price, tp_price, spread_percentage, leverage, order_amount, token_info=None, exchange="XT.COM", signal_id=None, dex_price=None, comparison_source="DexScreener"):
    """
    Генерує професійний криптовалютний сигнал у стилі як у друга з ByBit
    АРХІТЕКТОР: Переписано для XT.com з РЕАЛЬНИМИ цінами і спредами
    ✅ ВИПРАВЛЕНО: Додано HTML екранування для безпечного відправлення в Telegram
    """
    import html
    
    # Clean symbol name з безпечним екрануванням
    clean_symbol = symbol.replace('/USDT:USDT', '').replace('/USDT', '').upper()
    safe_symbol = html.escape(clean_symbol, quote=False)
    safe_exchange = html.escape(exchange, quote=False)
    
    # Визначаємо емодзі для сторони
    if side == "LONG":
        side_emoji = "🟢"
        action = "КУПИТИ"
    else:
        side_emoji = "🔴"
        action = "ПРОДАТИ"
        
    # Розраховуємо TP відстань
    tp_distance = abs((tp_price - entry_price) / entry_price * 100)
    
    # Розраховуємо SL (2% від входу)
    sl_distance = 2.0
    if side == "LONG":
        sl_price = entry_price * (1 - sl_distance / 100)
    else:
        sl_price = entry_price * (1 + sl_distance / 100)
    
    # R/R розрахунок
    risk_reward = tp_distance / sl_distance if sl_distance > 0 else 1.0
    
    # Визначаємо рівень ризику
    if abs(spread_percentage) >= 1.0:
        risk_level = "🔥 ВИСОКА ЯКІСТЬ"
        risk_color = "🟢"
    elif abs(spread_percentage) >= 0.5:
        risk_level = "⚡ СЕРЕДНЯ ЯКІСТЬ"
        risk_color = "🟡"
    else:
        risk_level = "⚠️ НИЗЬКА ЯКІСТЬ"
        risk_color = "🔴"
    
    # Розрахунок потенційного прибутку
    potential_profit = (order_amount * leverage * tp_distance / 100)
    potential_loss = (order_amount * leverage * sl_distance / 100)
    
    # Отримуємо додаткову інформацію
    token_name = safe_symbol
    if token_info and isinstance(token_info, dict):
        token_name = html.escape(token_info.get('name', clean_symbol), quote=False)
    
    # ✅ ВИПРАВЛЕНО: Форматуємо сигнал з правильними HTML тегами для Telegram
    signal = f"""🔥 <b>АРБІТРАЖНИЙ СИГНАЛ</b> 🔥

━━━━━━━━━━━━━━━━━━━━
{side_emoji} <b>{safe_symbol}/USDT PERP</b>
🏦 Біржа: ⚡ <b>{safe_exchange}</b>
📍 Дія: <b>{action} {side}</b>
━━━━━━━━━━━━━━━━━━━━

💰 <b>ТОРГОВІ ПАРАМЕТРИ:</b>
📊 Ціна входу: <b>${entry_price:.6f}</b>
🎯 Take Profit: <b>${tp_price:.6f}</b>
🛡️ Stop Loss: <b>${sl_price:.6f}</b>
⚖️ Плече: <b>{leverage}x</b>
💵 Розмір позиції: <b>${order_amount:.0f} USDT</b>

📈 <b>АНАЛІЗ:</b>"""

    # ✅ ВИПРАВЛЕНО: Додаємо порівняння з DEX ціною з HTML форматуванням
    safe_comparison_source = html.escape(comparison_source, quote=False)
    if dex_price:
        signal += f"""
💲 XT.com: <b>${entry_price:.6f}</b>
📊 {safe_comparison_source}: <b>${dex_price:.6f}</b>
🎯 Спред: <b>{spread_percentage:+.2f}%</b>"""
    
    signal += f"""
🎯 TP Дистанція: <b>{tp_distance:.2f}%</b>
🛡️ SL Дистанція: <b>{sl_distance:.2f}%</b>
⚖️ R/R Ratio: <b>{risk_reward:.1f}:1</b>

💰 <b>ПРОГНОЗИ:</b>
✅ Потенційний прибуток: <b>${potential_profit:.2f}</b>
❌ Максимальний ризик: <b>${potential_loss:.2f}</b>

{risk_color} Рівень якості: <b>{risk_level}</b>

🔗 <b>ПОСИЛАННЯ:</b>"""

    # 🎯 ЦЕНТРАЛІЗОВАНА СИСТЕМА: Прямі посилання на топові 3 DEX
    try:
        # Отримуємо адреси токена з точних DEX даних
        exact_pair_info = get_exact_dex_pair_info(symbol)
        token_addresses = {}
        
        if exact_pair_info and exact_pair_info.get('token_address') and exact_pair_info.get('chain_name'):
            chain = exact_pair_info['chain_name'].lower()
            token_addresses[chain] = exact_pair_info['token_address']
        
        # Якщо немає точних даних, пробуємо token_addresses.json
        if not token_addresses:
            try:
                with open('token_addresses.json', 'r', encoding='utf-8') as f:
                    token_data = json.load(f)
                    token_info = token_data.get(clean_symbol, {})
                    if token_info.get('address') and token_info.get('chain'):
                        token_addresses[token_info['chain']] = token_info['address']
            except Exception:
                pass
        
        # 🎯 ТОПОВИЙ DEX: тільки ОДИН найкращий DEX (згідно з вимогами користувача)
        if token_addresses:
            from dex_link_generator import build_top_dex_links
            
            # Генеруємо посилання для всіх доступних мереж
            top_dex_links = []
            for chain, address in token_addresses.items():
                chain_links = build_top_dex_links(clean_symbol, chain, address)
                top_dex_links.extend(chain_links)
            
            # 🚀 НОВИЙ ФОРМАТ: тільки ОДИН топовий DEX (не всі 3) + XT посилання
            if top_dex_links:
                # Беремо перший/найкращий DEX зі списку
                dex_name, dex_link = top_dex_links[0]
                xt_link = xt_pair_link(symbol)
                safe_dex_name = html.escape(dex_name, quote=False)
                signal += f"""
• <a href="{xt_link}">📊 XT.com Торгувати</a>
• <a href="{dex_link}">🚀 {safe_dex_name} Торгувати</a>"""
            else:
                # Fallback до DexScreener якщо немає DEX посилань
                proper_link = get_proper_dexscreener_link(clean_symbol)
                xt_link = xt_pair_link(symbol)
                signal += f"""
• <a href="{xt_link}">📊 XT.com Торгувати</a>
• <a href="{proper_link}">🔍 DexScreener {safe_symbol}</a>"""
        else:
            # Fallback до DexScreener якщо немає адрес токена
            proper_link = get_proper_dexscreener_link(clean_symbol)
            signal += f"""
• <a href="{proper_link}">🔍 DexScreener {safe_symbol}</a>"""
            
    except Exception as e:
        logging.error(f"❌ Помилка генерації DEX посилань для {symbol}: {e}")
        # Безпечний fallback з правильним посиланням
        proper_link = get_proper_dexscreener_link(clean_symbol)
        signal += f"""
• <a href="{proper_link}">🔍 DexScreener {safe_symbol}</a>"""
    
    signal += f"""

━━━━━━━━━━━━━━━━━━━━
⚡ <b>XT.COM Arbitrage Bot</b>
🤖 Автоматичний пошук арбітражів

⚠️ <b>РИЗИК:</b> Завжди використовуйте управління ризиками!
"""
    
    return signal

# Глобальна змінна для shared instance
_shared_dex_client_instance = None

def get_shared_dex_client():
    """Отримує shared instance DexClient для консистентності даних"""
    global _shared_dex_client_instance
    
    if _shared_dex_client_instance is None:
        try:
            # Import нового DexCheckClient замість старого DexScreenerClient
            from dex_client import DexCheckClient
            _shared_dex_client_instance = DexCheckClient()
        except ImportError as e:
            logging.error(f"Не вдалося імпортувати DexCheckClient: {e}")
            return None
    
    return _shared_dex_client_instance

def get_exact_dex_pair_info(symbol: str) -> Optional[dict]:
    """
    🔗 НОВА ФУНКЦІЯ: Отримує точну інформацію про DEX пару (не пошук!)
    Повертає pair_address, dex_name, exact_url, contract_address
    """
    try:
        dex_client = get_shared_dex_client()
        if not dex_client:
            return None
            
        clean_symbol = symbol.replace('/USDT:USDT', '').replace('/USDT', '').upper()
        
        # Отримуємо найкращу пару з кешем або свіжими даними
        best_pair = dex_client.resolve_best_pair(clean_symbol)
        if best_pair and best_pair.get('exact_pair_url'):
            return {
                'exact_pair_url': best_pair['exact_pair_url'],
                'pair_address': best_pair.get('pair_address', ''),
                'dex_name': best_pair.get('dex_name', 'DEX'),
                'token_address': best_pair.get('token_address', ''),
                'chain_name': best_pair.get('chain_name', best_pair.get('chain', 'ethereum'))
            }
            
        return None
        
    except Exception as e:
        logging.debug(f"Error getting exact DEX pair info for {symbol}: {e}")
        return None

def dex_link_for_symbol(symbol: str) -> Optional[str]:
    """
    Universal function to get direct DexScreener link
    Uses SHARED instance for consistency with main bot
    ALWAYS returns fallback link even when API unavailable
    """
    try:
        dex_client = get_shared_dex_client()
        if dex_client and hasattr(dex_client, 'get_dex_link'):
            dex_link = dex_client.get_dex_link(symbol)
            if dex_link and "dexscreener.com" in dex_link:
                logging.debug(f"🔗 DexScreener точна пара: {symbol} → {dex_link}")
                return dex_link
        
        # FALLBACK: пробуємо отримати токен адресу та створити точне посилання
        clean_symbol = symbol.replace('/USDT:USDT', '').replace('/USDT', '').upper()
        
        # Спробуємо знайти токен адресу в кеші
        if dex_client and hasattr(dex_client, 'token_addresses'):
            cached_info = dex_client.token_addresses.get(clean_symbol, {})
            if cached_info.get('contract_address') and cached_info.get('chain'):
                chain = cached_info['chain'].lower()
                token_address = cached_info['contract_address']
                exact_link = f"https://dexscreener.com/{chain}/{token_address}"
                logging.debug(f"🔗 DexScreener з кешу: {symbol} → {exact_link}")
                return exact_link
        
        # Use new proper link generation function
        return get_proper_dexscreener_link(symbol)
        
    except Exception as e:
        logging.error(f"Error getting DexScreener link for {symbol}: {e}")
        # FALLBACK: Use new proper link generation function
        return get_proper_dexscreener_link(symbol)

def xt_pair_link(symbol):
    """
    🔗 Генерує клікабельне посилання на торгову пару XT.com
    
    Args:
        symbol: символ торгової пари (наприклад: 'ETH/USDT:USDT' або 'BTC/USDT')
    
    Returns:
        str: URL посилання на XT.com futures trading
    """
    try:
        # Очищаємо символ: ETH/USDT:USDT → ETH
        clean_symbol = symbol.replace('/USDT:USDT', '').replace('/USDT', '').upper()
        
        # ✅ ПРАВИЛЬНИЙ ФОРМАТ XT.com futures trading
        pair_url = f"https://www.xt.com/en/trade/futures_{clean_symbol}USDT"
        
        logging.debug(f"🔗 XT посилання: {symbol} → {pair_url}")
        return pair_url
    except Exception as e:
        logging.error(f"❌ Помилка створення XT посилання для {symbol}: {e}")
        return "https://www.xt.com/en/trade"

def get_proper_dexscreener_link(symbol: str) -> str:
    """
    ✅ FIXED: Generate proper DexScreener links using contract addresses
    
    Priority:
    1. Direct contract address link: https://dexscreener.com/{chain}/{contract_address}
    2. Fallback to search only if no contract address available
    
    Args:
        symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT' or 'ETH')
    
    Returns:
        str: Proper DexScreener link
    """
    import json  # Move import to top to fix LSP error
    try:
        # Clean symbol to match token_addresses.json format
        clean_symbol = symbol.replace('/USDT:USDT', '').replace('/USDT', '').upper()
        
        # Load token addresses mapping
        try:
            with open('token_addresses.json', 'r', encoding='utf-8') as f:
                token_addresses = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logging.warning(f"🚨 Cannot load token_addresses.json: {e}")
            token_addresses = {}
        
        # Try to get contract address from mapping
        token_info = token_addresses.get(clean_symbol, {})
        if token_info.get('address') and token_info.get('chain'):
            contract_address = token_info['address']
            chain = token_info['chain'].lower()
            
            # Map chain names to DexScreener format
            chain_mapping = {
                'ethereum': 'ethereum',
                'bsc': 'bsc', 
                'polygon': 'polygon',
                'avalanche': 'avalanche',
                'solana': 'solana',
                'arbitrum': 'arbitrum',
                'optimism': 'optimism'
            }
            
            dexscreener_chain = chain_mapping.get(chain, chain)
            direct_link = f"https://dexscreener.com/{dexscreener_chain}/{contract_address}"
            logging.info(f"✅ Direct DexScreener link: {clean_symbol} → {direct_link}")
            return direct_link
        
        # Fallback to search only if no contract address
        search_link = f"https://dexscreener.com/search?q={clean_symbol}"
        logging.info(f"⚠️ No contract address for {clean_symbol}, using search: {search_link}")
        return search_link
        
    except Exception as e:
        logging.error(f"❌ Error generating DexScreener link for {symbol}: {e}")
        # Safe fallback
        clean_symbol = symbol.replace('/USDT:USDT', '').replace('/USDT', '').upper()
        return f"https://dexscreener.com/search?q={clean_symbol}"

def save_config_to_file(config_data):
    """Зберігає runtime конфігурацію в JSON файл"""
    try:
        with open('runtime_config.json', 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
        logging.info("✅ Runtime конфігурацію збережено")
    except Exception as e:
        logging.error(f"❌ Помилка збереження конфігурації: {e}")

def load_config_from_file():
    """Завантажує runtime конфігурацію з JSON файлу"""
    try:
        with open('runtime_config.json', 'r', encoding='utf-8') as f:
            config_data = json.load(f)
        logging.info("✅ Runtime конфігурацію завантажено")
        return config_data
    except FileNotFoundError:
        logging.info("⚠️ Runtime конфігурація не знайдена, використовуємо defaults")
        return {}
    except Exception as e:
        logging.error(f"❌ Помилка завантаження конфігурації: {e}")
        return {}

# 🧪 ТЕСТОВА ФУНКЦІЯ
def test_telegram_configuration():
    """Тестує Telegram конфігурацію при старті бота"""
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_GROUP_CHAT_ID
    import time
    
    logging.info("🧪 ТЕСТУВАННЯ TELEGRAM КОНФІГУРАЦІЇ...")
    
    if not TELEGRAM_BOT_TOKEN:
        logging.error("❌ TELEGRAM_BOT_TOKEN не налаштований!")
        return False
    
    timestamp = time.strftime("%H:%M:%S")
    test_message = f"🤖 TEST MESSAGE | {timestamp}\n✅ Бот працює і може відправляти повідомлення!"
    
    success_count = 0
    
    # Тестуємо приватний чат
    if TELEGRAM_CHAT_ID:
        logging.info(f"🧪 Тестуємо приватний чат: {TELEGRAM_CHAT_ID}")
        private_result = send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, test_message)
        if private_result:
            logging.info("✅ Приватний чат працює!")
            success_count += 1
        else:
            logging.error("❌ Приватний чат НЕ працює!")
    else:
        logging.warning("⚠️ TELEGRAM_CHAT_ID не налаштований")
    
    # Тестуємо групу
    if TELEGRAM_GROUP_CHAT_ID:
        logging.info(f"🧪 Тестуємо групу: {TELEGRAM_GROUP_CHAT_ID}")
        group_result = send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_GROUP_CHAT_ID, test_message)
        if group_result:
            logging.info("✅ Група працює!")
            success_count += 1
        else:
            logging.error("❌ Група НЕ працює! Перевірте:\n- Чи бот доданий в групу?\n- Чи має бот права відправляти повідомлення?\n- Чи правильний chat_id групи?")
    else:
        logging.warning("⚠️ TELEGRAM_GROUP_CHAT_ID (група) не налаштований")
    
    logging.info(f"🧪 РЕЗУЛЬТАТ ТЕСТУ: {success_count} з 2 чатів працюють")
    return success_count > 0

# 🚫 ВИДАЛЕНО: _get_primary_dexscreener_link_simple застаріла функція
# Замінена на нову систему DEX Link Generator з прямими посиланнями на топові DEX провайдери
