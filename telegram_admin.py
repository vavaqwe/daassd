import logging
import threading
import os
import time
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
import bot, config, utils
import json

# Authorized users (додайте свої Telegram ID)
AUTHORIZED_USERS = set()

# Додаємо першого адміністратора
if config.TELEGRAM_CHAT_ID:
    try:
        AUTHORIZED_USERS.add(int(config.TELEGRAM_CHAT_ID))
        logging.info(f"✅ Авторизовано адміністратора 1: {config.TELEGRAM_CHAT_ID}")
    except ValueError:
        logging.error(f"❌ Невірний TELEGRAM_CHAT_ID: {config.TELEGRAM_CHAT_ID}")

# Додаємо другого адміністратора
if config.TELEGRAM_ADMIN_2_ID:
    try:
        AUTHORIZED_USERS.add(int(config.TELEGRAM_ADMIN_2_ID))
        logging.info(f"✅ Авторизовано адміністратора 2: {config.TELEGRAM_ADMIN_2_ID}")
    except ValueError:
        logging.error(f"❌ Невірний TELEGRAM_ADMIN_2_ID: {config.TELEGRAM_ADMIN_2_ID}")

if config.TELEGRAM_ADMIN_3_ID:
    try:
        AUTHORIZED_USERS.add(int(config.TELEGRAM_ADMIN_3_ID))
        logging.info(f"✅ Авторизовано адміністратора 3: {config.TELEGRAM_ADMIN_3_ID}")
    except ValueError:
        logging.error(f"❌ Невірний TELEGRAM_ADMIN_3_ID: {config.TELEGRAM_ADMIN_3_ID}")

def is_authorized(user_id: int) -> bool:
    """Перевіряє чи авторизований користувач - БЕЗПЕЧНА авторизація"""
    # БЕЗПЕКА: Якщо список порожній, блокуємо всіх (default-deny)
    if not AUTHORIZED_USERS:
        logging.warning(f"🚫 ЗАБЛОКОВАНИЙ доступ для {user_id}: AUTHORIZED_USERS порожній")
        return False
    
    # Перевіряємо чи користувач у списку авторизованих
    authorized = user_id in AUTHORIZED_USERS
    if authorized:
        logging.info(f"✅ Авторизований доступ для {user_id}")
    else:
        logging.warning(f"🚫 НЕАВТОРИЗОВАНИЙ доступ для {user_id}")
    
    return authorized

async def chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує ID поточного чату (групи або приватного)"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    chat_title = getattr(update.effective_chat, 'title', 'Приватний чат')
    
    # Логуємо для налагодження
    logging.info(f"🆔 ID Request: chat_id={chat_id}, user_id={user_id}, type={chat_type}, title={chat_title}")
    
    if chat_type == 'group' or chat_type == 'supergroup':
        message = f"👥 ЦЕ ГРУПА!\n\n"
        message += f"🆔 ID ГРУПИ: {chat_id}\n\n"
        message += f"🏷️ Назва групи: {chat_title}\n"
        message += f"👤 Ваш особистий ID: {user_id}\n\n"
        message += f"🔧 ВАЖЛИВО! Використовуйте ID групи:\n"
        message += f"TELEGRAM_CHAT_ID_2 = {chat_id}\n\n"
        message += f"❗️ НЕ плутайте з особистим ID {user_id}"
    else:
        message = f"💬 ЦЕ ПРИВАТНИЙ ЧАТ\n\n"
        message += f"🆔 ID приватного чату: {chat_id}\n"
        message += f"👤 Ваш User ID: {user_id}\n\n"
        message += f"🔧 Для налаштування приватного чату:\n"
        message += f"TELEGRAM_CHAT_ID = {chat_id}"
    
    await update.message.reply_text(message)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command with main menu"""
    # Логуємо всі повідомлення для знаходження группового Chat ID
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    chat_type = update.effective_chat.type
    logging.info(f"🔍 Повідомлення: chat_id={chat_id}, user_id={user_id}, type={chat_type}")
    
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("❌ У вас немає доступу до цього бота")
        return
    
    keyboard = [
        [KeyboardButton("📊 Статус"), KeyboardButton("💰 Баланс")],
        [KeyboardButton("💼 Позиції"), KeyboardButton("💰 Заробіток")],
        [KeyboardButton("📋 Символи"), KeyboardButton("📡 Сигнали")],
        [KeyboardButton("📚 Історія"), KeyboardButton("💱 DRY RUN")],
        [KeyboardButton("⚙️ Налаштування"), KeyboardButton("🔴 Стоп бот")],
        [KeyboardButton("📈 Торгівля")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    welcome_text = f"""
🤖 Вітаю в адмін-панелі {config.BOT_NAME}!
    
📍 Поточний режим: {'🔒 DRY RUN (Безпечно)' if config.DRY_RUN else '🔥 LIVE TRADING'}
📊 Активних символів: {len([s for s, enabled in bot.trade_symbols.items() if enabled])}
💼 Активних позицій: {len([pos for pos in bot.active_positions.values() if pos])}

Використовуйте кнопки меню для керування ботом 👇
"""
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show bot status"""
    if not is_authorized(update.effective_user.id):
        return
    
    active_symbols = len([s for s, enabled in bot.trade_symbols.items() if enabled])
    total_symbols = len(bot.trade_symbols)
    active_positions_count = len([pos for pos in bot.active_positions.values() if pos])
    
    status_text = f"""
📊 **СТАТУС БОТА**

🔧 Режим: {'🔒 DRY RUN' if config.DRY_RUN else '🔥 LIVE TRADING'}
📈 Активних символів: {active_symbols}/{total_symbols}
💼 Відкритих позицій: {active_positions_count}

⚙️ **НАЛАШТУВАННЯ:**
💰 Сума ордера: {config.ORDER_AMOUNT} USDT
📊 Мін. спред: {config.MIN_SPREAD}%
🎯 Леверидж: {config.LEVERAGE}x
📚 Макс. позицій: {config.MAX_OPEN_POSITIONS}
📖 Глибина стакану: {config.ORDER_BOOK_DEPTH}

🔄 Інтервал сканування: {config.SCAN_INTERVAL}с
"""
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show active positions from both XT.com accounts"""
    if not is_authorized(update.effective_user.id):
        return
    
    try:
        positions_text = "💼 **АКТИВНІ ПОЗИЦІЇ (РЕАЛЬНІ):**\n\n"
        has_positions = False
        total_positions = 0
        
        # XT.com АКАУНТ 1
        try:
            import bot
            from xt_client import get_xt_open_positions
            from bot import calculate_pnl_percentage
            
            xt_positions_1 = get_xt_open_positions(bot.xt_account_1)
            logging.info(f"📊 XT.com АКАУНТ 1: знайдено {len(xt_positions_1)} позицій")
            
            positions_text += "⚡ **АКАУНТ 1:**\n"
            if xt_positions_1:
                for pos in xt_positions_1:
                    has_positions = True
                    total_positions += 1
                    clean_symbol = pos['symbol'].replace('/USDT:USDT', '')
                    side_emoji = "🟢" if pos['side'].upper() == "LONG" else "🔴"
                    
                    percentage = calculate_pnl_percentage(pos)
                    size_contracts = float(pos.get('contracts', 0) or pos.get('size', 0) or 0)
                    size_usdt = float(pos.get('notional', 0) or pos.get('size_usdt', 0) or 5.0)
                    unrealized_pnl = (percentage / 100) * size_usdt if percentage != 0 else 0.0
                    pnl_emoji = "💚" if percentage >= 0 else "❤️"
                    
                    positions_text += f"📈 **{clean_symbol}**\n"
                    positions_text += f"{side_emoji} {pos['side'].upper()} | 💵 {size_contracts:.4f} контрактів\n"
                    positions_text += f"💰 Розмір: **${size_usdt:.2f} USDT** | 📋 Баланс: **{size_contracts:.4f} {clean_symbol}**\n"
                    positions_text += f"{pnl_emoji} PnL: **${unrealized_pnl:.2f}** ({percentage:.2f}%)\n\n"
            else:
                positions_text += "❌ Немає позицій\n\n"
        except Exception as e:
            positions_text += f"❌ Помилка: {str(e)}\n\n"
            logging.error(f"XT.com АКАУНТ 1 позиції помилка: {e}")
        
        # XT.com АКАУНТ 2
        try:
            import bot
            from xt_client import get_xt_open_positions
            from bot import calculate_pnl_percentage
            
            xt_positions_2 = get_xt_open_positions(bot.xt_account_2)
            logging.info(f"📊 XT.com АКАУНТ 2: знайдено {len(xt_positions_2)} позицій")
            
            positions_text += "⚡ **АКАУНТ 2:**\n"
            if xt_positions_2:
                for pos in xt_positions_2:
                    has_positions = True
                    total_positions += 1
                    clean_symbol = pos['symbol'].replace('/USDT:USDT', '')
                    side_emoji = "🟢" if pos['side'].upper() == "LONG" else "🔴"
                    
                    percentage = calculate_pnl_percentage(pos)
                    size_contracts = float(pos.get('contracts', 0) or pos.get('size', 0) or 0)
                    size_usdt = float(pos.get('notional', 0) or pos.get('size_usdt', 0) or 5.0)
                    unrealized_pnl = (percentage / 100) * size_usdt if percentage != 0 else 0.0
                    pnl_emoji = "💚" if percentage >= 0 else "❤️"
                    
                    positions_text += f"📈 **{clean_symbol}**\n"
                    positions_text += f"{side_emoji} {pos['side'].upper()} | 💵 {size_contracts:.4f} контрактів\n"
                    positions_text += f"💰 Розмір: **${size_usdt:.2f} USDT** | 📋 Баланс: **{size_contracts:.4f} {clean_symbol}**\n"
                    positions_text += f"{pnl_emoji} PnL: **${unrealized_pnl:.2f}** ({percentage:.2f}%)\n\n"
            else:
                positions_text += "❌ Немає позицій\n\n"
        except Exception as e:
            positions_text += f"❌ Помилка: {str(e)}\n\n"
            logging.error(f"XT.com АКАУНТ 2 позиції помилка: {e}")
        
        if not has_positions:
            positions_text += "━━━━━━━━━━━━━━━━━━━━\n"
            positions_text += "📊 **ПІДСУМОК:**\n"
            positions_text += "❌ Немає відкритих позицій на жодному акаунті\n"
            positions_text += "🤖 Бот активно сканує можливості для торгівлі..."
        else:
            positions_text += "━━━━━━━━━━━━━━━━━━━━\n"
            positions_text += f"📊 **ЗАГАЛОМ: {total_positions} позицій**"
    
    except Exception as e:
        positions_text = f"❌ **ПОМИЛКА ОТРИМАННЯ ПОЗИЦІЙ:**\n\n{str(e)}"
        logging.error(f"Глобальна помилка позицій: {e}")
    
    await update.message.reply_text(positions_text, parse_mode='Markdown')

async def signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current arbitrage signals"""
    if not is_authorized(update.effective_user.id):
        return
    
    # Отримуємо поточні спреди з бота
    current_signals = []
    
    # Проходимось по активних символах і показуємо топ арбітражні можливості
    from utils import get_shared_dex_client
    from xt_client import create_xt, fetch_xt_ticker
    
    try:
        xt = create_xt()
        signals_text = "📡 **АРБІТРАЖНІ СИГНАЛИ** (DexScreener)\n\n"
        
        # Беремо перші 10 символів для швидкого огляду
        active_symbols = [s for s, enabled in bot.trade_symbols.items() if enabled][:10]
        
        for symbol in active_symbols:
            try:
                # Отримуємо ціни
                ticker = fetch_xt_ticker(xt, symbol)
                if not ticker:
                    continue
                    
                xt_price = float(ticker['last'])
                
                # Отримуємо повну інформацію про токен
                dex_client = get_shared_dex_client()
                # Отримуємо інформацію через resolve_best_pair
                token_info = dex_client.resolve_best_pair(symbol.replace('/USDT:USDT', ''))
                if not token_info:
                    continue
                    
                dex_price = token_info.get('price_usd', 0)
                
                if dex_price and dex_price > 0.000001:
                    # Розраховуємо спред
                    spread_pct = ((dex_price - xt_price) / xt_price) * 100
                    
                    # Фільтруємо фейки
                    is_realistic = True
                    price_ratio = max(xt_price, dex_price) / min(xt_price, dex_price)
                    min_liquidity = token_info.get('liquidity_usd', 0)
                    
                    if abs(spread_pct) > 10 or price_ratio > 1.15 or min_liquidity < 100000:
                        is_realistic = False
                    
                    # Показуємо тільки реальні цікаві спреди (>= 0.3%)
                    if abs(spread_pct) >= 0.3 and is_realistic:
                        clean_symbol = symbol.replace('/USDT:USDT', '')
                        direction = "🟢 LONG" if spread_pct > 0 else "🔴 SHORT"
                        
                        # Використовуємо функцію для отримання точного посилання на пару
                        try:
                            from utils import get_exact_dex_pair_info, get_proper_dexscreener_link
                            exact_pair_info = get_exact_dex_pair_info(clean_symbol)
                            if exact_pair_info and exact_pair_info.get('exact_pair_url'):
                                dex_link = exact_pair_info['exact_pair_url']
                            else:
                                dex_link = get_proper_dexscreener_link(clean_symbol)
                        except:
                            dex_link = get_proper_dexscreener_link(clean_symbol)
                        
                        signals_text += f"**{clean_symbol}** {direction}\n"
                        signals_text += f"📊 XT: ${xt_price:.4f} | DexScreener: ${dex_price:.4f}\n"
                        signals_text += f"💰 Спред: **{spread_pct:+.2f}%**\n"
                        signals_text += f"💧 Ліквідність: ${min_liquidity:,.0f}\n"
                        signals_text += f"🔍 [Графік DexScreener]({dex_link})\n"
                        signals_text += "━━━━━━━━━━━━━━━━━━━━\n"
                        current_signals.append((clean_symbol, spread_pct))
                        
            except Exception as e:
                continue
        
        if not current_signals:
            signals_text += "❌ Зараз немає сигналів з спредом >= 0.3%\n"
            signals_text += "📈 Бот сканує 596+ токенів автоматично...\n"
        else:
            signals_text += f"\n✅ Знайдено {len(current_signals)} можливостей!"
            signals_text += f"\n🤖 Автосигнали надсилаються при спреді >= 0.5%"
        
    except Exception as e:
        signals_text = f"❌ **ПОМИЛКА СИГНАЛІВ:**\n\n{str(e)}"
    
    await update.message.reply_text(signals_text, parse_mode='Markdown')

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show account balance with position counts"""
    if not is_authorized(update.effective_user.id):
        return
    
    try:
        # Отримуємо баланс з ОБОХ акаунтів XT.com
        import bot
        from xt_client import get_xt_futures_balance, get_xt_open_positions
        
        # Акаунт 1
        xt_balance_1 = get_xt_futures_balance(bot.xt_account_1)
        xt_positions_1 = get_xt_open_positions(bot.xt_account_1)
        xt_pos_count_1 = len(xt_positions_1)
        
        # Акаунт 2
        xt_balance_2 = get_xt_futures_balance(bot.xt_account_2)
        xt_positions_2 = get_xt_open_positions(bot.xt_account_2)
        xt_pos_count_2 = len(xt_positions_2)
        
        balance_text = "💰 **БАЛАНС XT.COM:**\n\n"
        total_balance = 0
        has_balance = False
        
        # XT.com АКАУНТ 1
        balance_text += f"⚡ **АКАУНТ 1** ({xt_pos_count_1} позицій):\n"
        if xt_balance_1.get('total', 0) > 0:
            has_balance = True
            available_1 = float(xt_balance_1.get('free', 0))
            used_1 = float(xt_balance_1.get('used', 0))
            total_1 = float(xt_balance_1.get('total', 0))
            
            balance_text += f"💵 Доступно: {available_1:.2f} USDT\n"
            if used_1 > 0:
                balance_text += f"📊 В позиціях: {used_1:.2f} USDT\n"
            balance_text += f"🎯 Загалом: {total_1:.2f} USDT\n"
            total_balance += total_1
        else:
            balance_text += "💵 USDT: 0.00 USDT доступно\n"
        
        balance_text += "\n"
        
        # XT.com АКАУНТ 2
        balance_text += f"⚡ **АКАУНТ 2** ({xt_pos_count_2} позицій):\n"
        if xt_balance_2.get('total', 0) > 0:
            has_balance = True
            available_2 = float(xt_balance_2.get('free', 0))
            used_2 = float(xt_balance_2.get('used', 0))
            total_2 = float(xt_balance_2.get('total', 0))
            
            balance_text += f"💵 Доступно: {available_2:.2f} USDT\n"
            if used_2 > 0:
                balance_text += f"📊 В позиціях: {used_2:.2f} USDT\n"
            balance_text += f"🎯 Загалом: {total_2:.2f} USDT\n"
            total_balance += total_2
        else:
            balance_text += "💵 USDT: 0.00 USDT доступно\n"
        
        if has_balance:
            total_positions = xt_pos_count_1 + xt_pos_count_2
            balance_text += f"\n━━━━━━━━━━━━━━━━━━━━\n"
            balance_text += f"💰 **ЗАГАЛЬНИЙ БАЛАНС: {total_balance:.2f} USDT**\n"
            balance_text += f"📊 **ВСЬОГО ПОЗИЦІЙ: {total_positions}**"
        else:
            balance_text += "❌ Баланс пустий або помилка отримання даних"
    
    except Exception as e:
        balance_text = f"❌ **ПОМИЛКА БАЛАНСУ:**\n\n{str(e)}"
    
    await update.message.reply_text(balance_text, parse_mode='Markdown')

# Глобальна змінна для зберігання історії позицій
trade_history_data = []

def add_to_trade_history(symbol, side, entry_price, close_price=None, pnl=None, close_reason="Manual", timestamp=None, exchange="XT.com"):
    """Додає запис до історії торгівлі"""
    if timestamp is None:
        timestamp = datetime.now()
    
    history_record = {
        "timestamp": timestamp,
        "symbol": symbol.replace('/USDT:USDT', ''),
        "side": side,
        "entry_price": float(entry_price),
        "close_price": float(close_price) if close_price else None,
        "pnl": float(pnl) if pnl else None,
        "close_reason": close_reason,
        "exchange": exchange
    }
    
    trade_history_data.append(history_record)
    
    # Зберігаємо тільки останні 100 записів
    if len(trade_history_data) > 100:
        trade_history_data.pop(0)

async def trade_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує історію торгівлі з прибутком/збитком"""
    if not is_authorized(update.effective_user.id):
        return
    
    try:
        history_text = "📚 **ІСТОРІЯ ТОРГІВЛІ:**\n\n"
        
        if not trade_history_data:
            history_text += "❌ Історія торгівлі порожня\n"
            history_text += "💡 Позиції будуть додаватися автоматично після торгівлі"
        else:
            # Показуємо останні 10 записів
            recent_trades = sorted(trade_history_data, key=lambda x: x['timestamp'], reverse=True)[:10]
            
            total_pnl = 0.0
            profitable_trades = 0
            
            history_text += f"📊 **ОСТАННІ {len(recent_trades)} ОПЕРАЦІЙ:**\n\n"
            
            for trade in recent_trades:
                symbol = trade['symbol']
                side = trade['side']
                entry_price = trade['entry_price']
                close_price = trade['close_price']
                pnl = trade['pnl']
                close_reason = trade['close_reason']
                exchange = trade['exchange']
                
                # Форматування часу
                trade_time = trade['timestamp'].strftime("%d.%m %H:%M")
                
                side_emoji = "🟢" if side == "LONG" else "🔴"
                
                if pnl is not None:
                    total_pnl += pnl
                    if pnl > 0:
                        profitable_trades += 1
                        pnl_emoji = "💚"
                    else:
                        pnl_emoji = "❤️"
                    
                    history_text += f"**{symbol}** {side_emoji}\n"
                    history_text += f"🕐 {trade_time} | 🏪 {exchange}\n"
                    history_text += f"📈 ${entry_price:.6f} → ${close_price:.6f}\n"
                    history_text += f"{pnl_emoji} P&L: ${pnl:.2f}\n"
                    history_text += f"📝 {close_reason}\n\n"
                else:
                    # Активна позиція
                    history_text += f"**{symbol}** {side_emoji} (активна)\n"
                    history_text += f"🕐 {trade_time} | 🏪 {exchange}\n"
                    history_text += f"📈 Вхід: ${entry_price:.6f}\n\n"
            
            # Статистика
            win_rate = (profitable_trades / len(recent_trades)) * 100 if recent_trades else 0
            avg_pnl = total_pnl / len(recent_trades) if recent_trades else 0
            
            history_text += "📊 **СТАТИСТИКА:**\n"
            history_text += f"💰 Загальний P&L: ${total_pnl:.2f}\n"
            history_text += f"📈 Прибуткових: {profitable_trades}/{len(recent_trades)} ({win_rate:.1f}%)\n"
            history_text += f"⚖️ Середній P&L: ${avg_pnl:.2f}\n"
        
        await update.message.reply_text(history_text, parse_mode='Markdown')
        
    except Exception as e:
        logging.error(f"Помилка історії торгівлі: {e}")
        await update.message.reply_text("❌ Помилка отримання історії торгівлі")

async def profit_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current profit/loss from active positions"""
    if not is_authorized(update.effective_user.id):
        return
    
    try:
        profit_text = "💰 **ЗВІТ ПРО ЗАРОБІТОК:**\n\n"
        
        total_unrealized_pnl = 0.0
        total_positions = 0
        profitable_positions = 0
        
        # Отримуємо gate клієнт для цін
        # ❌ GATE ВИДАЛЕНО: використовуємо тільки XT.com
        # gate = gate_client.create_gate()  # REMOVED - Gate.io system removed
        
        if not bot.active_positions:
            profit_text += "❌ Немає активних позицій для розрахунку прибутку\n"
            profit_text += "📊 Загальний нереалізований P&L: $0.00\n"
        else:
            profit_text += "📊 **АКТИВНІ ПОЗИЦІЇ:**\n\n"
            
            for symbol, position in bot.active_positions.items():
                if position:
                    # Отримуємо поточну ціну
                    try:
                        # ✅ ВИКОРИСТОВУЄМО XT.com замість Gate.io
                        from xt_client import fetch_xt_ticker, create_xt
                        xt_exchange = create_xt()
                        ticker = fetch_xt_ticker(xt_exchange, symbol)
                        if ticker and 'last' in ticker:
                            current_price = float(ticker['last'])
                        
                        clean_symbol = symbol.replace('/USDT:USDT', '')
                        profit_text += f"**{clean_symbol}:**\n"
                        
                        side = position['side']
                        open_price = position['avg_entry']
                        amount = position['size_usdt']
                        
                        # Розрахунок нереалізованого P&L
                        if side == "LONG":
                            unrealized_pnl = ((current_price - open_price) / open_price) * amount
                        else:  # SHORT
                            unrealized_pnl = ((open_price - current_price) / open_price) * amount
                        
                        total_unrealized_pnl += unrealized_pnl
                        total_positions += 1
                        
                        if unrealized_pnl > 0:
                            profitable_positions += 1
                            pnl_emoji = "🟢"
                        else:
                            pnl_emoji = "🔴"
                        
                        profit_pct = (unrealized_pnl / amount) * 100
                        
                        side_emoji = "🟢" if side == "LONG" else "🔴"
                        profit_text += f"{side_emoji} {side} | "
                        profit_text += f"💵 ${amount:.2f} | "
                        profit_text += f"📈 ${open_price:.6f} → ${current_price:.6f}\n"
                        profit_text += f"{pnl_emoji} P&L: ${unrealized_pnl:+.2f} ({profit_pct:+.1f}%)\n"
                        profit_text += f"🎯 TP: ${position['tp_price']:.6f}\n"
                        profit_text += f"📊 Усереднення: {position['adds_done']}\n"
                        profit_text += "━━━━━━━━━━━━━━━━━━━━\n"
                        
                    except Exception as e:
                        profit_text += f"❌ Помилка отримання ціни для {symbol}: {str(e)}\n"
                        continue
            
            # Загальна статистика
            win_rate = (profitable_positions / total_positions * 100) if total_positions > 0 else 0
            avg_pnl = total_unrealized_pnl / total_positions if total_positions > 0 else 0
            
            profit_text += "\n📈 **ЗАГАЛЬНА СТАТИСТИКА:**\n"
            profit_text += f"💰 Загальний нереалізований P&L: ${total_unrealized_pnl:+.2f}\n"
            profit_text += f"📊 Позицій всього: {total_positions}\n"
            profit_text += f"🟢 Прибуткових: {profitable_positions} ({win_rate:.1f}%)\n"
            profit_text += f"🔴 Збиткових: {total_positions - profitable_positions}\n"
            profit_text += f"📊 Середній P&L: ${avg_pnl:+.2f}\n"
            
            # Статус по відношенню до TP
            if total_unrealized_pnl > 0:
                profit_text += f"\n🎯 **СТАТУС:** На шляху до прибутку! 🚀"
            elif total_unrealized_pnl == 0:
                profit_text += f"\n⚖️ **СТАТУС:** Беззбитковість (Break-even)"
            else:
                profit_text += f"\n📉 **СТАТУС:** Тимчасовий дроудаун"
        
        # Інформація про режим
        if config.DRY_RUN:
            profit_text += f"\n\n🔒 **РЕЖИМ:** DRY RUN (Тестування)\n"
            profit_text += f"⚠️ Це симуляція, реальні кошти не задіяні"
        else:
            profit_text += f"\n\n🔥 **РЕЖИМ:** LIVE TRADING\n"
            profit_text += f"💰 Реальна торгівля з реальними коштами"
    
    except Exception as e:
        profit_text = f"❌ **ПОМИЛКА РОЗРАХУНКУ ПРИБУТКУ:**\n\n{str(e)}"
    
    await update.message.reply_text(profit_text, parse_mode='Markdown')

async def symbols_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show symbols management menu"""
    if not is_authorized(update.effective_user.id):
        return
    
    keyboard = []
    row = []
    for i, (symbol, enabled) in enumerate(list(bot.trade_symbols.items())[:20]):  # Показуємо перші 20
        status_emoji = "🟢" if enabled else "🔴"
        button_text = f"{status_emoji} {symbol}"
        row.append(InlineKeyboardButton(button_text, callback_data=f"toggle_{symbol}"))
        
        if len(row) == 2:  # 2 кнопки в ряду
            keyboard.append(row)
            row = []
    
    if row:  # Додаємо останній ряд якщо є
        keyboard.append(row)
    
    keyboard.append([
        InlineKeyboardButton("✅ Включити всі", callback_data="enable_all"),
        InlineKeyboardButton("❌ Вимкнути всі", callback_data="disable_all")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    active_count = len([s for s, enabled in bot.trade_symbols.items() if enabled])
    text = f"📋 **КЕРУВАННЯ СИМВОЛАМИ** ({active_count} активних)\n\nНатисніть на символ щоб увімкнути/вимкнути:"
    
    await update.message.reply_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def settings_buttons_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show settings menu with buttons"""
    if not is_authorized(update.effective_user.id):
        return
    
    settings_text = f"""
⚙️ **НАЛАШТУВАННЯ БОТА**

Поточні значення:
💰 Сума ордера: {config.ORDER_AMOUNT} USDT
📊 Мін. спред: {config.MIN_SPREAD}%
🎯 Леверидж: {config.LEVERAGE}x
📚 Макс. позицій: {config.MAX_OPEN_POSITIONS}
📖 Глибина стакану: {config.ORDER_BOOK_DEPTH}

📈 **УСЕРЕДНЕННЯ:**
🔄 Увімкнено: {"✅" if config.AVERAGING_ENABLED else "❌"}
📊 Поріг: {config.AVERAGING_THRESHOLD_PCT}%
🔢 Макс. додавань: {config.AVERAGING_MAX_ADDS}
💵 Макс. розмір: ${config.MAX_POSITION_USDT_PER_SYMBOL}

Натисніть кнопку щоб змінити параметр:
"""
    
    keyboard = [
        [
            InlineKeyboardButton("💰 Сума ордера", callback_data="settings_amount"),
            InlineKeyboardButton("📊 Мін. спред", callback_data="settings_spread")
        ],
        [
            InlineKeyboardButton("🎯 Леверидж", callback_data="settings_leverage"),
            InlineKeyboardButton("📚 Макс. позицій", callback_data="settings_positions")
        ],
        [
            InlineKeyboardButton("📖 Глибина стакану", callback_data="settings_depth"),
            InlineKeyboardButton("🔄 Усереднення", callback_data="settings_averaging")
        ],
        [
            InlineKeyboardButton("🔄 Оновити", callback_data="settings_refresh")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(settings_text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_settings_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle settings button clicks"""
    if not is_authorized(update.effective_user.id):
        return
    
    query = update.callback_query
    await query.answer()
    
    if query.data == "settings_amount":
        keyboard = [
            [InlineKeyboardButton("💰 $3", callback_data="set_amount_3"),
             InlineKeyboardButton("💰 $5", callback_data="set_amount_5")],
            [InlineKeyboardButton("💰 $10", callback_data="set_amount_10"),
             InlineKeyboardButton("💰 $15", callback_data="set_amount_15")],
            [InlineKeyboardButton("💰 $20", callback_data="set_amount_20"),
             InlineKeyboardButton("💰 $50", callback_data="set_amount_50")],
            [InlineKeyboardButton("◀️ Назад", callback_data="settings_back")]
        ]
        text = f"💰 **СУМА ОРДЕРА** (поточна: ${config.ORDER_AMOUNT})\n\nВиберіть нову суму ордера:"
        
    elif query.data == "settings_spread":
        keyboard = [
            [InlineKeyboardButton("📊 0.5%", callback_data="set_spread_0.5"),
             InlineKeyboardButton("📊 0.7%", callback_data="set_spread_0.7")],
            [InlineKeyboardButton("📊 1.0%", callback_data="set_spread_1.0"),
             InlineKeyboardButton("📊 1.5%", callback_data="set_spread_1.5")],
            [InlineKeyboardButton("📊 2.0%", callback_data="set_spread_2.0"),
             InlineKeyboardButton("📊 3.0%", callback_data="set_spread_3.0")],
            [InlineKeyboardButton("◀️ Назад", callback_data="settings_back")]
        ]
        text = f"📊 **МІНІМАЛЬНИЙ СПРЕД** (поточний: {config.MIN_SPREAD}%)\n\nВиберіть новий мінімальний спред:"
        
    elif query.data == "settings_leverage":
        keyboard = [
            [InlineKeyboardButton("🎯 3x", callback_data="set_leverage_3"),
             InlineKeyboardButton("🎯 5x", callback_data="set_leverage_5")],
            [InlineKeyboardButton("🎯 7x", callback_data="set_leverage_7"),
             InlineKeyboardButton("🎯 10x", callback_data="set_leverage_10")],
            [InlineKeyboardButton("🎯 15x", callback_data="set_leverage_15"),
             InlineKeyboardButton("🎯 20x", callback_data="set_leverage_20")],
            [InlineKeyboardButton("◀️ Назад", callback_data="settings_back")]
        ]
        text = f"🎯 **ЛЕВЕРИДЖ** (поточний: {config.LEVERAGE}x)\n\nВиберіть новий леверидж:"
        
    elif query.data == "settings_positions":
        keyboard = [
            [InlineKeyboardButton("📚 1", callback_data="set_positions_1"),
             InlineKeyboardButton("📚 3", callback_data="set_positions_3")],
            [InlineKeyboardButton("📚 5", callback_data="set_positions_5"),
             InlineKeyboardButton("📚 10", callback_data="set_positions_10")],
            [InlineKeyboardButton("📚 15", callback_data="set_positions_15"),
             InlineKeyboardButton("📚 25", callback_data="set_positions_25")],
            [InlineKeyboardButton("◀️ Назад", callback_data="settings_back")]
        ]
        text = f"📚 **МАКСИМУМ ПОЗИЦІЙ** (поточно: {config.MAX_OPEN_POSITIONS})\n\nВиберіть максимальну кількість позицій:"
        
    elif query.data == "settings_depth":
        keyboard = [
            [InlineKeyboardButton("📖 5", callback_data="set_depth_5"),
             InlineKeyboardButton("📖 10", callback_data="set_depth_10")],
            [InlineKeyboardButton("📖 15", callback_data="set_depth_15"),
             InlineKeyboardButton("📖 20", callback_data="set_depth_20")],
            [InlineKeyboardButton("📖 25", callback_data="set_depth_25"),
             InlineKeyboardButton("📖 50", callback_data="set_depth_50")],
            [InlineKeyboardButton("◀️ Назад", callback_data="settings_back")]
        ]
        text = f"📖 **ГЛИБИНА СТАКАНУ** (поточна: {config.ORDER_BOOK_DEPTH})\n\nВиберіть глибину аналізу стакану:"
        
    elif query.data == "settings_averaging":
        keyboard = [
            [
                InlineKeyboardButton("🔄 Увімкнути" if not config.AVERAGING_ENABLED else "❌ Вимкнути", 
                                   callback_data="toggle_averaging")
            ],
            [
                InlineKeyboardButton("📊 Поріг усереднення", callback_data="averaging_threshold"),
                InlineKeyboardButton("🔢 Макс. додавань", callback_data="averaging_max_adds")
            ],
            [
                InlineKeyboardButton("💵 Макс. розмір позиції", callback_data="averaging_max_size"),
                InlineKeyboardButton("◀️ Назад", callback_data="settings_back")
            ]
        ]
        text = f"""📈 **НАЛАШТУВАННЯ УСЕРЕДНЕННЯ**

🔄 Увімкнено: {"✅" if config.AVERAGING_ENABLED else "❌"}
📊 Поріг: {config.AVERAGING_THRESHOLD_PCT}% (ціна проти позиції)
🔢 Макс. додавань: {config.AVERAGING_MAX_ADDS}
💵 Макс. розмір позиції: ${config.MAX_POSITION_USDT_PER_SYMBOL}
⏰ Пауза між усередненнями: {config.AVERAGING_COOLDOWN_SEC}с

Виберіть параметр для налаштування:"""
        
    elif query.data == "settings_refresh" or query.data == "settings_back":
        return await settings_buttons_menu_refresh(query)
        
    # Обробка налаштувань усереднення
    elif query.data == "toggle_averaging":
        config.AVERAGING_ENABLED = not config.AVERAGING_ENABLED
        utils.save_config_to_file({"AVERAGING_ENABLED": config.AVERAGING_ENABLED})
        status = "✅ увімкнено" if config.AVERAGING_ENABLED else "❌ вимкнено"
        keyboard = [[InlineKeyboardButton("◀️ Назад до усереднення", callback_data="settings_averaging")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(f"🔄 Усереднення {status}", reply_markup=reply_markup)
        return
        
    elif query.data == "averaging_threshold":
        keyboard = [
            [InlineKeyboardButton("📊 0.5%", callback_data="set_avg_threshold_0.5"),
             InlineKeyboardButton("📊 1.0%", callback_data="set_avg_threshold_1.0")],
            [InlineKeyboardButton("📊 1.5%", callback_data="set_avg_threshold_1.5"),
             InlineKeyboardButton("📊 2.0%", callback_data="set_avg_threshold_2.0")],
            [InlineKeyboardButton("📊 3.0%", callback_data="set_avg_threshold_3.0"),
             InlineKeyboardButton("📊 5.0%", callback_data="set_avg_threshold_5.0")],
            [InlineKeyboardButton("◀️ Назад", callback_data="settings_averaging")]
        ]
        text = f"📊 **ПОРІГ УСЕРЕДНЕННЯ** (поточний: {config.AVERAGING_THRESHOLD_PCT}%)\n\nВиберіть відсоток руху проти позиції для усереднення:"
        
    elif query.data == "averaging_max_adds":
        keyboard = [
            [InlineKeyboardButton("🔢 1", callback_data="set_avg_adds_1"),
             InlineKeyboardButton("🔢 2", callback_data="set_avg_adds_2")],
            [InlineKeyboardButton("🔢 3", callback_data="set_avg_adds_3"),
             InlineKeyboardButton("🔢 5", callback_data="set_avg_adds_5")],
            [InlineKeyboardButton("🔢 10", callback_data="set_avg_adds_10"),
             InlineKeyboardButton("◀️ Назад", callback_data="settings_averaging")]
        ]
        text = f"🔢 **МАКСИМУМ ДОДАВАНЬ** (поточно: {config.AVERAGING_MAX_ADDS})\n\nВиберіть максимальну кількість усереднень на позицію:"
        
    elif query.data == "averaging_max_size":
        keyboard = [
            [InlineKeyboardButton("💵 $25", callback_data="set_avg_size_25"),
             InlineKeyboardButton("💵 $50", callback_data="set_avg_size_50")],
            [InlineKeyboardButton("💵 $100", callback_data="set_avg_size_100"),
             InlineKeyboardButton("💵 $200", callback_data="set_avg_size_200")],
            [InlineKeyboardButton("💵 $500", callback_data="set_avg_size_500"),
             InlineKeyboardButton("◀️ Назад", callback_data="settings_averaging")]
        ]
        text = f"💵 **МАКСИМАЛЬНИЙ РОЗМІР ПОЗИЦІЇ** (поточний: ${config.MAX_POSITION_USDT_PER_SYMBOL})\n\nВиберіть максимальний розмір позиції на один символ:"
    
    # Обробка встановлення значень
    elif query.data.startswith("set_"):
        return await handle_setting_change(query)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_setting_change(query):
    """Handle actual setting changes"""
    parts = query.data.split("_")
    if len(parts) == 3:
        _, param, value = parts
    elif len(parts) == 4:  # для avg_threshold_1.0 формату
        _, param, subparam, value = parts
    else:
        await query.edit_message_text("❌ Помилка формату команди")
        return
    
    try:
        # 🔒 THREAD-SAFE CONFIG CHANGES (Task 6: захист від конфліктів з trading logic)
        from locks import config_lock
        with config_lock:
            if param == "amount":
                config.ORDER_AMOUNT = float(value)
                message = f"✅ Сума ордера встановлена: ${value}"
            elif param == "spread":
                config.MIN_SPREAD = float(value)
                message = f"✅ Мінімальний спред встановлено: {value}%"
            elif param == "leverage":
                config.LEVERAGE = int(value)
                message = f"✅ Леверидж встановлено: {value}x"
            elif param == "positions":
                config.MAX_OPEN_POSITIONS = int(value)
                message = f"✅ Максимум позицій встановлено: {value}"
            elif param == "depth":
                config.ORDER_BOOK_DEPTH = int(value)
                message = f"✅ Глибина стакану встановлена: {value}"
            elif param == "avg":
                if subparam == "threshold":
                    config.AVERAGING_THRESHOLD_PCT = float(value)
                    message = f"✅ Поріг усереднення встановлено: {value}%"
                elif subparam == "adds":
                    config.AVERAGING_MAX_ADDS = int(value)
                    message = f"✅ Максимум додавань встановлено: {value}"
                elif subparam == "size":
                    config.MAX_POSITION_USDT_PER_SYMBOL = float(value)
                    message = f"✅ Максимальний розмір позиції встановлено: ${value}"
        
        # Зберігаємо налаштування
        utils.save_config_to_file({
            "ORDER_AMOUNT": config.ORDER_AMOUNT,
            "MIN_SPREAD": config.MIN_SPREAD,
            "LEVERAGE": config.LEVERAGE,
            "MAX_OPEN_POSITIONS": config.MAX_OPEN_POSITIONS,
            "ORDER_BOOK_DEPTH": config.ORDER_BOOK_DEPTH
        })
        
        # Показуємо підтвердження з можливістю повернутися
        keyboard = [[InlineKeyboardButton("◀️ Назад до налаштувань", callback_data="settings_back")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(message, reply_markup=reply_markup)
        
    except Exception as e:
        await query.edit_message_text(f"❌ Помилка встановлення: {str(e)}")

async def settings_buttons_menu_refresh(query):
    """Refresh settings menu"""
    settings_text = f"""
⚙️ **НАЛАШТУВАННЯ БОТА**

Поточні значення:
💰 Сума ордера: {config.ORDER_AMOUNT} USDT
📊 Мін. спред: {config.MIN_SPREAD}%
🎯 Леверидж: {config.LEVERAGE}x
📚 Макс. позицій: {config.MAX_OPEN_POSITIONS}
📖 Глибина стакану: {config.ORDER_BOOK_DEPTH}

Натисніть кнопку щоб змінити параметр:
"""
    
    keyboard = [
        [
            InlineKeyboardButton("💰 Сума ордера", callback_data="settings_amount"),
            InlineKeyboardButton("📊 Мін. спред", callback_data="settings_spread")
        ],
        [
            InlineKeyboardButton("🎯 Леверидж", callback_data="settings_leverage"),
            InlineKeyboardButton("📚 Макс. позицій", callback_data="settings_positions")
        ],
        [
            InlineKeyboardButton("📖 Глибина стакану", callback_data="settings_depth"),
            InlineKeyboardButton("🔄 Оновити", callback_data="settings_refresh")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(settings_text, reply_markup=reply_markup, parse_mode='Markdown')

async def toggle_symbol(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle symbol enable/disable"""
    if not is_authorized(update.effective_user.id):
        return
    
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("toggle_"):
        symbol = query.data[7:]  # Remove "toggle_" prefix
        if symbol in bot.trade_symbols:
            bot.trade_symbols[symbol] = not bot.trade_symbols[symbol]
            status = "🟢 увімкнено" if bot.trade_symbols[symbol] else "🔴 вимкнено"
            await query.edit_message_text(f"✅ Символ {symbol} {status}")
            
            # Повертаємося до меню символів через 1 секунду
            import asyncio
            await asyncio.sleep(1.0)
            await symbols_menu(update, context)
    
    elif query.data == "enable_all":
        for symbol in bot.trade_symbols:
            bot.trade_symbols[symbol] = True
        await query.edit_message_text("✅ Всі символи увімкнено!")
        import asyncio
        await asyncio.sleep(1.0)
        await symbols_menu(update, context)
    
    elif query.data == "disable_all":
        for symbol in bot.trade_symbols:
            bot.trade_symbols[symbol] = False
        await query.edit_message_text("❌ Всі символи вимкнено!")
        import asyncio
        await asyncio.sleep(1.0)
        await symbols_menu(update, context)

async def set_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set order amount"""
    await set_parameter(update, context, "set_amount")

async def set_spread(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set min spread"""
    await set_parameter(update, context, "set_spread")

async def set_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set leverage"""
    await set_parameter(update, context, "set_leverage")

async def set_positions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set max positions"""
    await set_parameter(update, context, "set_positions")

async def set_depth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set order book depth"""
    await set_parameter(update, context, "set_depth")

async def set_parameter(update: Update, context: ContextTypes.DEFAULT_TYPE, param_name: str):
    """Set trading parameter"""
    if not is_authorized(update.effective_user.id):
        return
    
    if len(context.args) != 1:
        await update.message.reply_text(f"❌ Вкажіть значення: /{param_name} <значення>")
        return
    
    try:
        value = float(context.args[0])
        
        if param_name == "set_amount":
            # ORDER_AMOUNT тепер ФІКСОВАНИЙ на 5.0 USDT - не змінюється
            await update.message.reply_text(f"❌ Сума ордера ФІКСОВАНА на 5.0 USDT і не може змінюватися!")
        elif param_name == "set_spread":
            config.MIN_SPREAD = value
            await update.message.reply_text(f"✅ Мін. спред встановлено: {value}%")
        elif param_name == "set_leverage":
            config.LEVERAGE = int(value)
            await update.message.reply_text(f"✅ Леверидж встановлено: {int(value)}x")
        elif param_name == "set_positions":
            config.MAX_OPEN_POSITIONS = int(value)
            await update.message.reply_text(f"✅ Макс. позицій встановлено: {int(value)}")
        elif param_name == "set_depth":
            config.ORDER_BOOK_DEPTH = int(value)
            await update.message.reply_text(f"✅ Глибина стакану встановлена: {int(value)}")
        
        # Зберігаємо налаштування
        utils.save_config_to_file({
            "ORDER_AMOUNT": config.ORDER_AMOUNT,
            "MIN_SPREAD": config.MIN_SPREAD,
            "LEVERAGE": config.LEVERAGE,
            "MAX_OPEN_POSITIONS": config.MAX_OPEN_POSITIONS,
            "ORDER_BOOK_DEPTH": config.ORDER_BOOK_DEPTH
        })
        
    except ValueError:
        await update.message.reply_text("❌ Невірне значення! Вкажіть число.")

async def toggle_dry_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle DRY_RUN mode"""
    if not is_authorized(update.effective_user.id):
        return
    
    if not config.ALLOW_LIVE_TRADING:
        await update.message.reply_text("🔒 Режим реальної торгівлі заблокований для безпеки")
        return
    
    # 🔒 THREAD-SAFE CONFIG CHANGE (Task 6: захист від конфліктів з trading logic)  
    from locks import config_lock
    with config_lock:
        config.DRY_RUN = not config.DRY_RUN
        mode = "🔒 DRY RUN (Безпечно)" if config.DRY_RUN else "🔥 LIVE TRADING"
    await update.message.reply_text(f"✅ Режим змінено на: {mode}")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages from keyboard"""
    user_id = update.effective_user.id
    
    # Debug logging
    logging.info(f"📱 Отримано текст від користувача {user_id}: '{update.message.text}'")
    
    if not is_authorized(user_id):
        # Тихо ігноруємо неавторизованих користувачів
        pass
        await update.message.reply_text("🚫 У вас немає доступу до цього бота")
        return
    
    text = update.message.text
    logging.info(f"✅ Обробляю команду: '{text}'")
    
    if text == "📊 Статус":
        await status(update, context)
    elif text == "💼 Позиції":
        await positions(update, context)
    elif text == "⚙️ Налаштування":
        await settings_buttons_menu(update, context)
    elif text == "📋 Символи":
        await symbols_menu(update, context)
    elif text == "💰 Баланс":
        await balance(update, context)
    elif text == "📡 Сигнали":
        await signals(update, context)
    elif text == "💰 Заробіток":
        await profit_report(update, context)
    elif text == "📚 Історія":
        await trade_history(update, context)
    elif text == "💱 DRY RUN":
        # 🔒 THREAD-SAFE CONFIG CHANGE (Task 6: захист від конфліктів з trading logic)
        from bot import config_lock
        with config_lock:
            config.DRY_RUN = True
        await update.message.reply_text("🔒 Увімкнено режим DRY RUN (Безпечно)")
    elif text == "📈 Торгівля":
        from bot import config_lock
        if config.ALLOW_LIVE_TRADING:
            # 🔒 THREAD-SAFE CONFIG CHANGE (Task 6: захист від конфліктів з trading logic)
            with config_lock:
                config.DRY_RUN = False
            await update.message.reply_text("🔥 Увімкнено режим LIVE TRADING")
        else:
            await update.message.reply_text("🔒 Режим реальної торгівлі заблокований")
    elif text in ["🔴 Стоп бот", "🟢 Старт бот"]:
        await update.message.reply_text("ℹ️ Функція старт/стоп буде додана в наступній версії")
    elif "ARBITRAGE SIGNAL" in text.upper() or "ASSET:" in text.upper():
        # Обробка арбітражних сигналів
        await handle_arbitrage_signal(update, context)
    elif text.upper().startswith("CANCEL "):
        # Обробка команд скасування
        await handle_cancel_command(update, context)
    else:
        logging.info(f"❓ Невідома команда: '{text}'")
        await update.message.reply_text(f"❓ Невідома команда: '{text}'\nСпробуйте /start")

async def handle_arbitrage_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє арбітражні сигнали"""
    try:
        from signal_processor import process_signal_message
        
        message_text = update.message.text
        user_id = update.effective_user.id
        
        logging.info(f"📨 Отримано арбітражний сигнал від {user_id}")
        
        # Обробляємо сигнал
        result = process_signal_message(message_text, "telegram")
        
        # Відповідаємо користувачу
        if result['success']:
            await update.message.reply_text("✅ Арбітражний сигнал успішно оброблений і перевірений")
        else:
            error_msg = "; ".join(result['errors'][:2])  # Перші 2 помилки
            await update.message.reply_text(f"❌ Помилка обробки сигналу:\n{error_msg}")
        
    except Exception as e:
        logging.error(f"Помилка обробки арбітражного сигналу: {e}")
        await update.message.reply_text("❌ Внутрішня помилка обробки сигналу")

async def handle_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє команди скасування торгових операцій"""
    try:
        text = update.message.text.upper()
        # Витягуємо назву активу з команди "CANCEL SYMBOL"
        parts = text.split()
        if len(parts) >= 2:
            asset = parts[1]
            # Реалізовано через глобальний cancel registry
            from cancel_registry import request_cancel_for_asset
            success = request_cancel_for_asset(asset)
            if success:
                await update.message.reply_text(f"✅ Скасування для {asset} зареєстровано\n⏱️ Виконання буде зупинено якщо воно ще не почалось")
        else:
            await update.message.reply_text("❌ Невірний формат. Використовуйте: CANCEL SYMBOL")
    except Exception as e:
        logging.error(f"Помилка обробки команди скасування: {e}")
        await update.message.reply_text("❌ Помилка обробки команди скасування")

def setup_telegram_bot():
    """Setup Telegram bot"""
    if not config.TELEGRAM_BOT_TOKEN:
        logging.error("TELEGRAM_BOT_TOKEN не встановлено!")
        return None
    
    application = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    # Commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("chat_id", chat_id))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("positions", positions))
    application.add_handler(CommandHandler("symbols", symbols_menu))
    application.add_handler(CommandHandler("settings", settings_buttons_menu))
    application.add_handler(CommandHandler("set_amount", set_amount))
    application.add_handler(CommandHandler("set_spread", set_spread)) 
    application.add_handler(CommandHandler("set_leverage", set_leverage))
    application.add_handler(CommandHandler("set_positions", set_positions))
    application.add_handler(CommandHandler("set_depth", set_depth))
    
    # Дублікати команд видалено
    
    # Callback handlers for symbols
    application.add_handler(CallbackQueryHandler(toggle_symbol, pattern="^(toggle_|enable_all|disable_all)"))
    
    # Callback handlers for settings
    application.add_handler(CallbackQueryHandler(handle_settings_buttons, pattern="^(settings_|set_)"))
    
    # Text message handler
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    
    return application

def run_telegram_bot():
    """Run Telegram bot"""
    import asyncio
    try:
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        application = setup_telegram_bot()
        if application:
            logging.info("Запуск Telegram бота...")
            application.run_polling()
        else:
            # Тихо обробляємо помилки запуску Telegram бота
            pass
    except Exception as e:
        # Тихо обробляємо помилки Telegram бота
        pass
    finally:
        try:
            loop.close()
        except:
            pass

if __name__ == "__main__":
    run_telegram_bot()