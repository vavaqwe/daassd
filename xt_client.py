import ccxt
import logging
import time
from config import XT_API_KEY, XT_API_SECRET, XT_ACCOUNT_2_API_KEY, XT_ACCOUNT_2_API_SECRET, DRY_RUN, ALLOW_LIVE_TRADING

# Глобальна змінна для збереження ринків XT
xt_markets = {}

def create_xt(api_key=None, api_secret=None, account_name="Account 1"):
    """Створення XT клієнта для арбітражної торгівлі
    
    Args:
        api_key: API ключ (якщо None, використовує XT_API_KEY з config)
        api_secret: API секрет (якщо None, використовує XT_API_SECRET з config)
        account_name: Назва акаунту для логування
    """
    # Використовуємо передані ключі або дефолтні з config
    key = api_key if api_key is not None else XT_API_KEY
    secret = api_secret if api_secret is not None else XT_API_SECRET
    
    xt = ccxt.xt({
        'apiKey': key,
        'secret': secret,
        'enableRateLimit': True,
        'sandbox': False,
        'options': {
            'defaultType': 'swap',  # Futures контракти
            'createMarketBuyOrderRequiresPrice': False
        }
    })
    # 🚀 ОПТИМІЗАЦІЯ: Налаштовуємо connection pool після створення
    try:
        import requests.adapters
        if hasattr(xt, 'session') and xt.session:
            # CCXT використовує requests.Session - налаштовуємо його
            adapter = requests.adapters.HTTPAdapter(
                pool_connections=50,
                pool_maxsize=50,
                pool_block=False
            )
            xt.session.mount('http://', adapter)
            xt.session.mount('https://', adapter)
            logging.info(f"🚀 XT {account_name} connection pool налаштовано: 50 connections")
    except Exception as e:
        logging.warning(f"⚠️ {account_name}: Не вдалося налаштувати connection pool: {e}")
    
    logging.info(f"✅ XT {account_name} клієнт створено успішно")
    return xt

def load_xt_futures_markets(xt):
    """🚀 Завантажує ВСІ futures ринки XT (swap + future для 700+)"""
    global xt_markets
    
    # 🚀 РОЗШИРЕНИЙ ПОШУК: завантажуємо ОБА типи futures
    # 1. Завантажуємо perpetual swaps
    swap_markets = xt.load_markets(params={'type':'swap'}, reload=True)
    
    # 2. Завантажуємо dated futures
    future_markets = xt.load_markets(params={'type':'future'}, reload=True)
    
    # 3. Об'єднуємо всі ринки
    all_markets = {**swap_markets, **future_markets}
    
    xt_markets = {}
    futures_markets = {}
    count = 0
    futures_count = 0
    spot_count = 0
    
    for symbol, meta in all_markets.items():
        # 🚀 РОЗШИРЕНА ФІЛЬТРАЦІЯ: підтримка USDT, USD, USDC
        if (meta.get('active', False) and 
            (meta.get('quote') in ['USDT', 'USD', 'USDC'] or 
             meta.get('settle') in ['USDT', 'USD', 'USDC'])):
            
            market_type = meta.get('type', 'unknown')
            
            # 🎯 КРИТИЧНО: ТІЛЬКИ FUTURES/SWAP (виключаємо SPOT)
            if market_type in ['swap', 'future']:
                futures_markets[symbol] = meta
                xt_markets[symbol] = meta
                count += 1
                futures_count += 1
                
                # Логування перших 15 символів для діагностики
                if count <= 15:
                    settle = meta.get('settle', 'N/A')
                    logging.info(f"✅ XT Futures: {symbol} (type: {market_type}, settle: {settle})")
            elif market_type == 'spot':
                spot_count += 1
    
    logging.info(f"🚀 XT РОЗШИРЕНИЙ ПОШУК: swap + future markets")
    logging.info(f"📉 FUTURES увімкнено: {futures_count}")
    logging.info(f"📈 SPOT пропущено: {spot_count}")
    
    # Перевірка результатів
    if futures_count >= 700:
        logging.info(f"🎯 МАКСИМУМ: Знайдено {futures_count} пар (>=700 УСПІХ!)")
    elif futures_count >= 500:
        logging.info(f"🎯 ДОБРЕ: Знайдено {futures_count} пар (>=500)")
    else:
        logging.warning(f"⚠️ Очікувалося >=700 futures пар, отримано {futures_count}")
    
    return futures_markets

def fetch_xt_ticker(xt, symbol):
    """Отримання тікера з XT"""
    return xt.fetch_ticker(symbol)

def get_all_xt_futures_pairs(client):
    """Отримати всі доступні futures торгові пари з XT.com"""
    try:
        # Загружаємо всі ринки
        markets = client.load_markets()
        
        # Фільтруємо тільки futures USDT пари
        futures_pairs = []
        
        for symbol, market in markets.items():
            if (market.get('type') == 'swap' and 
                market.get('quote') == 'USDT' and
                market.get('settle') == 'USDT' and
                market.get('active', True)):
                
                # Отримуємо base символ (наприклад BTC з BTC/USDT:USDT)
                base = market.get('base', '')
                if base and base not in ['USDT', 'USD']:
                    futures_pairs.append(base)
        
        print(f"📊 XT.com: знайдено {len(futures_pairs)} futures USDT пар")
        print(f"🔍 Перші 20: {futures_pairs[:20]}")
        
        return sorted(list(set(futures_pairs)))  # Унікальні та відсортовані
        
    except Exception as e:
        print(f"❌ Помилка отримання XT пар: {e}")
        return []

def fetch_xt_order_book(xt, symbol, depth=10):
    """Отримання стакану з XT"""
    return xt.fetch_order_book(symbol, depth)

def collect_market_depth_data(xt, symbol, depth_levels=20):
    """
    📊 ЗБІР ДАНИХ ПРО ГЛИБИНУ РИНКУ
    Отримує детальну інформацію про обсяги заявок на різних рівнях цін
    
    Повертає:
    {
        'symbol': символ,
        'bids': [{'price': цена, 'volume': объем, 'total_usd': загальна_сума}, ...],
        'asks': [{'price': цена, 'volume': объем, 'total_usd': загальна_сума}, ...],
        'bid_depth_analysis': аналіз глибини покупок,
        'ask_depth_analysis': аналіз глибини продажів,
        'total_bid_liquidity': загальна ліквідність покупок,
        'total_ask_liquidity': загальна ліквідність продажів,
        'spread_analysis': аналіз спредів між рівнями
    }
    """
    try:
        orderbook = fetch_xt_order_book(xt, symbol, depth_levels)
        if not orderbook or 'bids' not in orderbook or 'asks' not in orderbook:
            return None
            
        # Обробка bids (заявки на покупку)
        processed_bids = []
        total_bid_liquidity = 0
        for price, volume in orderbook['bids'][:depth_levels]:
            price_float = float(price)
            volume_float = float(volume)
            total_usd = price_float * volume_float
            total_bid_liquidity += total_usd
            
            processed_bids.append({
                'price': price_float,
                'volume': volume_float,
                'total_usd': total_usd
            })
        
        # Обробка asks (заявки на продаж)
        processed_asks = []
        total_ask_liquidity = 0
        for price, volume in orderbook['asks'][:depth_levels]:
            price_float = float(price)
            volume_float = float(volume)
            total_usd = price_float * volume_float
            total_ask_liquidity += total_usd
            
            processed_asks.append({
                'price': price_float,
                'volume': volume_float,
                'total_usd': total_usd
            })
        
        # Аналіз глибини по рівнях
        bid_depth_analysis = _analyze_depth_levels(processed_bids, "bids")
        ask_depth_analysis = _analyze_depth_levels(processed_asks, "asks")
        
        # Аналіз спредів між рівнями
        spread_analysis = _analyze_level_spreads(processed_bids, processed_asks)
        
        return {
            'symbol': symbol,
            'timestamp': time.time(),
            'bids': processed_bids,
            'asks': processed_asks,
            'bid_depth_analysis': bid_depth_analysis,
            'ask_depth_analysis': ask_depth_analysis,
            'total_bid_liquidity': total_bid_liquidity,
            'total_ask_liquidity': total_ask_liquidity,
            'spread_analysis': spread_analysis
        }
        
    except Exception as e:
        logging.error(f"❌ Помилка збору даних глибини ринку {symbol}: {e}")
        return None

def _analyze_depth_levels(levels, side_name):
    """Аналізує розподіл ліквідності по рівнях"""
    if not levels or len(levels) < 3:
        return {"quality": "poor", "reason": "Недостатньо рівнів"}
    
    # Аналіз концентрації ліквідності
    top3_liquidity = sum(level['total_usd'] for level in levels[:3])
    total_liquidity = sum(level['total_usd'] for level in levels)
    
    concentration_pct = (top3_liquidity / total_liquidity * 100) if total_liquidity > 0 else 0
    
    # Аналіз розподілу обсягів
    volumes = [level['volume'] for level in levels]
    avg_volume = sum(volumes) / len(volumes) if volumes else 0
    
    # Визначення якості глибини
    if concentration_pct > 80:
        quality = "concentrated"  # Ліквідність сконцентрована в топ-3
    elif concentration_pct > 60:
        quality = "balanced"      # Збалансований розподіл
    else:
        quality = "distributed"   # Рівномірно розподілена
    
    return {
        "quality": quality,
        "levels_count": len(levels),
        "top3_concentration_pct": concentration_pct,
        "avg_volume_per_level": avg_volume,
        "total_liquidity": total_liquidity
    }

def _analyze_level_spreads(bids, asks):
    """Аналіз спредів між рівнями цін"""
    spreads_analysis = {}
    
    # Спред між найкращими bid/ask
    if bids and asks:
        best_bid = bids[0]['price']
        best_ask = asks[0]['price']
        bid_ask_spread = ((best_ask - best_bid) / best_bid) * 100
        spreads_analysis['bid_ask_spread_pct'] = bid_ask_spread
    
    # Спреди між рівнями в bids
    if len(bids) >= 3:
        bid_spreads = []
        for i in range(len(bids) - 1):
            spread = ((bids[i]['price'] - bids[i+1]['price']) / bids[i]['price']) * 100
            bid_spreads.append(spread)
        spreads_analysis['avg_bid_level_spread_pct'] = sum(bid_spreads) / len(bid_spreads)
        spreads_analysis['max_bid_level_spread_pct'] = max(bid_spreads)
    
    # Спреди між рівнями в asks  
    if len(asks) >= 3:
        ask_spreads = []
        for i in range(len(asks) - 1):
            spread = ((asks[i+1]['price'] - asks[i]['price']) / asks[i]['price']) * 100
            ask_spreads.append(spread)
        spreads_analysis['avg_ask_level_spread_pct'] = sum(ask_spreads) / len(ask_spreads)
        spreads_analysis['max_ask_level_spread_pct'] = max(ask_spreads)
    
    return spreads_analysis

def analyze_xt_order_book_liquidity(xt, symbol, side, usd_amount, min_liquidity_ratio=2.0):
    """
    🔍 АНАЛІЗ СТАКАНУ XT - перевірка ліквідності перед входом
    
    Параметри:
    - min_liquidity_ratio: мінімальне співвідношення ліквідності до розміру ордера (2.0 = 200%)
    
    Повертає: (can_trade, liquidity_info)
    """
    try:
        orderbook = fetch_xt_order_book(xt, symbol, depth=10)
        if not orderbook or 'bids' not in orderbook or 'asks' not in orderbook:
            return False, "❌ Не вдалося отримати XT стакан"
        
        # Визначаємо сторону для аналізу
        relevant_side = orderbook['asks'] if side == "LONG" else orderbook['bids'] 
        side_name = "asks (продажі)" if side == "LONG" else "bids (покупки)"
        
        if not relevant_side or len(relevant_side) < 3:
            return False, f"❌ Недостатньо XT ордерів в {side_name}: {len(relevant_side)}"
        
        # Аналізуємо перші 5 рівнів стакану
        total_liquidity_usd = 0
        levels_analyzed = min(5, len(relevant_side))
        
        for i in range(levels_analyzed):
            price = float(relevant_side[i][0])
            quantity = float(relevant_side[i][1])
            level_usd = price * quantity
            total_liquidity_usd += level_usd
        
        # Перевірка мінімальної ліквідності
        required_liquidity = usd_amount * min_liquidity_ratio
        liquidity_ok = total_liquidity_usd >= required_liquidity
        
        # Аналіз спреду між рівнями
        best_price = float(relevant_side[0][0])
        second_price = float(relevant_side[1][0]) if len(relevant_side) > 1 else best_price
        spread_between_levels = abs(second_price - best_price) / best_price * 100
        
        # Детальна оцінка якості стакану
        quality_issues = []
        if total_liquidity_usd < required_liquidity:
            quality_issues.append(f"Мала XT ліквідність: ${total_liquidity_usd:.0f} < ${required_liquidity:.0f}")
        if spread_between_levels > 0.5:  # Спред між рівнями > 0.5%
            quality_issues.append(f"Великий XT спред між рівнями: {spread_between_levels:.2f}%")
        if levels_analyzed < 3:
            quality_issues.append(f"Мало XT рівнів: {levels_analyzed}")
        
        if quality_issues:
            return False, f"❌ XT проблеми стакану: {'; '.join(quality_issues)}"
        
        return True, f"✅ XT стакан ОК: ліквідність ${total_liquidity_usd:.0f} ({total_liquidity_usd/usd_amount:.1f}x), спред {spread_between_levels:.2f}%"
        
    except Exception as e:
        return False, f"❌ Помилка аналізу XT стакану: {str(e)}"

def get_xt_futures_balance(xt):
    """Отримання балансу futures рахунку XT"""
    try:
        if DRY_RUN:
            return {
                'total': 1000.0,
                'free': 950.0,
                'used': 50.0
            }
        
        balance = xt.fetch_balance({'type': 'swap'})
        
        # 🔍 DEBUG: Логування сирої відповіді для діагностики
        logging.info(f"🔍 RAW XT BALANCE: {balance}")
        
        if 'USDT' in balance and isinstance(balance['USDT'], dict):
            usdt_balance = balance['USDT']
            logging.info(f"🔍 USDT BALANCE KEYS: {list(usdt_balance.keys())}")
            logging.info(f"🔍 USDT BALANCE DATA: {usdt_balance}")
            
            # 🚀 ВИПРАВЛЕННЯ: Спробуємо різні ключі для балансу
            available = (
                usdt_balance.get('equity') or      # 💰 НОВЕ: спробуємо equity
                usdt_balance.get('wallet_balance') or # 💰 НОВЕ: спробуємо wallet_balance  
                usdt_balance.get('free') or 
                usdt_balance.get('available') or 
                usdt_balance.get('balance') or     # 💰 НОВЕ: спробуємо balance
                (usdt_balance.get('total', 0) - usdt_balance.get('used', 0))
            )
            
            total_balance = (
                usdt_balance.get('equity') or      # 💰 НОВЕ: спробуємо equity для total
                usdt_balance.get('wallet_balance') or
                usdt_balance.get('total', 0)
            )
            
            logging.info(f"🔍 BALANCE PARSING: available={available}, total={total_balance}")
            
            return {
                'total': total_balance,
                'free': available,
                'used': usdt_balance.get('used', 0)
            }
        
        # 🚀 ВИПРАВЛЕННЯ: Якщо USDT не знайдено, логуємо всі ключі
        logging.warning(f"🔍 NO USDT KEY FOUND. All balance keys: {list(balance.keys())}")
        return {'total': 0, 'free': 0, 'used': 0}
        
    except Exception as e:
        logging.error(f"XT баланс помилка: {e}")
        import traceback
        logging.error(f"XT баланс traceback: {traceback.format_exc()}")
        return {'total': 0, 'free': 0, 'used': 0}

def is_xt_futures_tradeable(symbol):
    """Перевіряє чи можна торгувати токен на XT futures (USDT, USD, USDC)"""
    try:
        if symbol not in xt_markets:
            return False
        
        market = xt_markets[symbol]
        
        # Перевіряємо що це активний futures ринок
        if not market.get('active', False):
            return False
            
        if market.get('type') not in ['swap', 'future']:
            return False
            
        # Перевіряємо що це підтримувана валюта settle (USDT, USD, USDC)
        settle = market.get('settle', '')
        quote = market.get('quote', '')
        if settle not in ['USDT', 'USD', 'USDC'] and quote not in ['USDT', 'USD', 'USDC']:
            return False
            
        return True
        
    except Exception as e:
        logging.error(f"Помилка перевірки XT futures для {symbol}: {e}")
        return False

def xt_open_market_position(xt, symbol, side, usd_amount, leverage, xt_price_ref=None, dex_price_ref=None, spread_ref=None):
    """
    Створює ринковий ордер на XT futures через CCXT (аналогічно Gate.io).
    
    IMPORTANT: usd_amount це MARGIN (маржа яку ризикуємо), не notional value.
    Notional value = margin * leverage
    """
    # 🔒 ПОДВІЙНИЙ ЗАХИСТ: DRY_RUN + ALLOW_LIVE_TRADING
    if DRY_RUN:
        logging.info("[XT DRY-RUN] create market %s %s %sUSDT @ lev %s", symbol, side, usd_amount, leverage)
        return {"id":"dry-xt-"+str(time.time()), "price": None}
    
    # 🔍 DEBUG: Логування стану конфігурації  
    logging.info(f"🔍 OPEN DEBUG: ALLOW_LIVE_TRADING={ALLOW_LIVE_TRADING}, DRY_RUN={DRY_RUN}")
    
    if not ALLOW_LIVE_TRADING:
        logging.error("[XT SECURITY] 🚨 LIVE TRADING BLOCKED: ALLOW_LIVE_TRADING=False")
        raise Exception("Live trading not allowed - set ALLOW_LIVE_TRADING=true")
    
    # Ініціалізуємо змінні для exception handling
    current_price = 0.0
    instant_price = 0.0
    try:
        # 📊 КРОК 1: Отримуємо market metadata для символу
        logging.info(f"[XT {symbol}] 📊 КРОК 1: Отримання market metadata...")
        try:
            market = xt.market(symbol)
            logging.info(f"[XT {symbol}] ✅ Market metadata отримано: {market.get('id', 'N/A')}")
        except Exception as e:
            error_msg = f"❌ Не вдалося отримати market metadata: {e}"
            logging.error(f"[XT {symbol}] {error_msg}")
            return None
        
        # 🔍 КРОК 2: Отримуємо contractSize з market metadata
        contract_size = market.get('contractSize', 1.0)
        logging.info(f"[XT {symbol}] 📏 КРОК 2: contractSize = {contract_size}")
        
        # 📏 КРОК 3: Отримуємо limits та precision з market
        exchange_min_size = float(market.get('limits', {}).get('amount', {}).get('min', 0.001))
        amount_precision = market.get('precision', {}).get('amount', 6)
        logging.info(f"[XT {symbol}] 📊 КРОК 3: Limits - min_amount={exchange_min_size}, precision={amount_precision}")
        
        # ⚡ КРОК 4: Обмежуємо leverage до максимально дозволеного
        max_leverage = market.get('limits', {}).get('leverage', {}).get('max', leverage)
        if max_leverage is None:
            max_leverage = leverage
        clamped_leverage = min(leverage, max_leverage)
        
        if clamped_leverage != leverage:
            logging.warning(f"[XT {symbol}] ⚠️ КРОК 4: Leverage обмежено з {leverage}x до {clamped_leverage}x (максимум для ринку)")
        else:
            logging.info(f"[XT {symbol}] ✅ КРОК 4: Leverage {clamped_leverage}x в межах дозволеного (max={max_leverage}x)")
        
        # ⚙️ КРОК 5A: Встановлюємо ISOLATED MARGIN MODE
        try:
            xt.set_margin_mode('isolated', symbol)
            logging.info(f"[XT {symbol}] ⚙️ КРОК 5A: ✅ Встановлено ISOLATED margin mode")
        except Exception as e:
            logging.warning(f"[XT {symbol}] ⚠️ КРОК 5A: Помилка встановлення margin mode (можливо вже isolated): {e}")
            pass
        
        # ⚙️ КРОК 5B: Встановлюємо плече для futures контракту
        position_side = "LONG" if side == "LONG" else "SHORT"
        try:
            xt.set_leverage(clamped_leverage, symbol, {"positionSide": position_side})
            logging.info(f"[XT {symbol}] ⚙️ КРОК 5B: ✅ Встановлено леверидж {clamped_leverage}x ({position_side})")
        except Exception as e:
            logging.warning(f"[XT {symbol}] ⚠️ КРОК 5B: Помилка встановлення левериджу: {e}")
            pass

        # 💰 КРОК 6: Розрахунок margin та notional value
        margin_amount = usd_amount
        notional_value = margin_amount * clamped_leverage
        logging.info(f"[XT {symbol}] 💰 КРОК 6: margin=${margin_amount:.2f}, leverage={clamped_leverage}x → notional=${notional_value:.2f}")
        
        # 🎯 КРОК 7: Отримуємо миттєву ціну для розрахунку
        logging.info(f"[XT {symbol}] 🎯 КРОК 7: Отримання миттєвої ціни...")
        ticker = fetch_xt_ticker(xt, symbol)
        if not ticker or 'last' not in ticker:
            error_msg = f"❌ Не вдалося отримати свіжу ціну для ордера"
            logging.error(f"[XT {symbol}] {error_msg}")
            return None
        
        instant_price = float(ticker['last'])
        logging.info(f"[XT {symbol}] ✅ КРОК 7: instant_price = ${instant_price:.6f}")
        
        # 🧮 КРОК 8: ПРАВИЛЬНИЙ розрахунок contracts з contractSize
        # Формула: contracts = notional_value / (contract_size * price)
        contracts = notional_value / (contract_size * instant_price)
        logging.info(f"[XT {symbol}] 🧮 КРОК 8: Розрахунок contracts = {notional_value:.2f} / ({contract_size} * {instant_price:.6f}) = {contracts:.6f}")
        
        # 🔧 КРОК 9: Застосування amount_to_precision для округлення
        logging.info(f"[XT {symbol}] 🔧 КРОК 9: Застосування amount_to_precision...")
        try:
            final_contracts = float(xt.amount_to_precision(symbol, contracts))
            logging.info(f"[XT {symbol}] ✅ КРОК 9: final_contracts (precision) = {final_contracts:.6f}")
        except Exception as e:
            logging.warning(f"[XT {symbol}] ⚠️ КРОК 9: Помилка amount_to_precision: {e}, використовуємо fallback")
            final_contracts = round(float(contracts), amount_precision)
            logging.info(f"[XT {symbol}] ⚠️ КРОК 9: final_contracts (fallback) = {final_contracts:.6f}")
        
        # ✅ КРОК 10: КРИТИЧНА ПЕРЕВІРКА мінімального розміру ПЕРЕД створенням ордера
        logging.info(f"[XT {symbol}] ✅ КРОК 10: Перевірка мінімального розміру...")
        if final_contracts < exchange_min_size:
            error_msg = f"❌ Розмір {final_contracts:.6f} менший за мінімум {exchange_min_size:.6f}"
            logging.error(f"[XT {symbol}] {error_msg}")
            logging.error(f"[XT {symbol}] ❌ ОРДЕР НЕ ВІДПРАВЛЕНО через малий розмір")
            return None
        else:
            logging.info(f"[XT {symbol}] ✅ КРОК 10: Розмір OK - {final_contracts:.6f} >= {exchange_min_size:.6f}")
        
        # 📊 КРОК 11: Перерахунок фінальних значень
        final_notional = final_contracts * contract_size * instant_price
        final_margin = final_notional / clamped_leverage
        logging.info(f"[XT {symbol}] 📊 КРОК 11: Фінальні значення:")
        logging.info(f"[XT {symbol}]   - contracts: {final_contracts:.6f}")
        logging.info(f"[XT {symbol}]   - notional: ${final_notional:.2f}")
        logging.info(f"[XT {symbol}]   - margin: ${final_margin:.2f}")

        # 🎯 КРОК 12: СТВОРЕННЯ ОРДЕРА
        logging.info(f"[XT {symbol}] 🎯 КРОК 12: Створення ордера на біржі...")
        order = xt.create_order(
            symbol, 
            'market', 
            'buy' if side == "LONG" else 'sell', 
            final_contracts, 
            None,
            {'type': 'swap', 'settle': 'usdt'}
        )
        logging.info(f"[XT FUTURES] ✅ Відкрито {side} позицію {symbol}: {final_contracts:.6f} контрактів = ${final_notional:.2f} NOTIONAL (margin ${final_margin:.2f})")
        
        # 📱 КРОК 13: Відправка Telegram сповіщення
        logging.info(f"[XT {symbol}] 📱 КРОК 13: Відправка Telegram сповіщення...")
        from utils import send_telegram_trade_notification
        send_telegram_trade_notification(
            symbol, side, final_margin, instant_price, 
            action="OPENED (XT)", 
            spread=spread_ref, 
            exchange_price=xt_price_ref or instant_price, 
            dex_price=dex_price_ref
        )
        
        logging.info(f"[XT {symbol}] ✅ УСПІХ: Ордер створено та сповіщення відправлено")
        return order
    except Exception as e:
        # ДЕТАЛЬНЕ TELEGRAM СПОВІЩЕННЯ ПРО ПОМИЛКУ СТВОРЕННЯ XT ОРДЕРА (як просий користувач)
        price_display = instant_price if instant_price > 0 else "N/A"
        error_msg = f"❌ **ПОМИЛКА СТВОРЕННЯ XT ОРДЕРА**\n"\
                   f"📊 Символ: **{symbol.replace('/USDT:USDT', '')}** ({side})\n"\
                   f"💰 Розмір: **${usd_amount:.2f}**\n"\
                   f"⚡ Леверидж: **{leverage}x**\n"\
                   f"📉 Ціна: **${price_display}**\n"\
                   f"🏪 Біржа: **XT.COM**\n"\
                   f"❌ **ПОМИЛКА**: `{str(e)[:100]}...`\n"\
                   f"⏰ Час: **{time.strftime('%H:%M:%S')}**"
        from utils import send_telegram
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        # ❌ ПОМИЛКИ НЕ ВІДПРАВЛЯЄМО В ГРУПУ - тільки в приватний бот
        send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, error_msg)
        logging.error("XT Order create error: %s %s", type(e).__name__, e)
        return None

def xt_close_position_market(xt, symbol, side, usd_amount):
    """
    Закриття позиції на XT futures.
    
    IMPORTANT: usd_amount це NOTIONAL VALUE (загальна вартість позиції), не margin.
    Це position['size_usdt'] з нашої системи.
    """
    # 🔒 ПОДВІЙНИЙ ЗАХИСТ: DRY_RUN + ALLOW_LIVE_TRADING
    if DRY_RUN:
        logging.info("[XT DRY-RUN] close %s side %s %sUSDT", symbol, side, usd_amount)
        return True
    
    # 🔍 DEBUG: Логування стану конфігурації
    logging.info(f"🔍 CLOSE DEBUG: ALLOW_LIVE_TRADING={ALLOW_LIVE_TRADING}, DRY_RUN={DRY_RUN}")
    
    if not ALLOW_LIVE_TRADING:
        logging.error("[XT SECURITY] 🚨 LIVE TRADING BLOCKED: ALLOW_LIVE_TRADING=False")
        return False
    
    # Ініціалізуємо змінні для exception handling  
    instant_price = 0.0
    actual_position = None
    try:
        # 🔧 КРИТИЧНО: Отримуємо СПРАВЖНІЙ розмір позиції з біржі!
        try:
            live_positions = xt.fetch_positions([symbol])
            actual_position = None
            
            for pos in live_positions:
                if (pos.get('symbol') == symbol and 
                    pos.get('side', '').upper() == side.upper() and 
                    abs(float(pos.get('contracts', 0) or pos.get('size', 0))) > 0):
                    actual_position = pos
                    break
                    
            if not actual_position:
                logging.warning(f"[XT {symbol}] ℹ️ Позиція {side} не знайдена - можливо вже закрита")
                return True  # Вважаємо успішним якщо позиція вже закрита
                
            # Використовуємо ТОЧНИЙ розмір контрактів з біржі
            exact_contracts = abs(float(actual_position.get('contracts', 0) or actual_position.get('size', 0)))
            
        except Exception as e:
            logging.warning(f"[XT {symbol}] ⚠️ Помилка отримання live позиції: {e}, використовуємо fallback")
            # FALLBACK: отримуємо свіжу ціну для розрахунків
            fallback_ticker = fetch_xt_ticker(xt, symbol)
            if fallback_ticker and 'last' in fallback_ticker:
                fallback_price = float(fallback_ticker['last'])
                exact_contracts = usd_amount / fallback_price
            else:
                logging.error(f"[XT {symbol}] ❌ Не вдалося отримати ціну для fallback розрахунку")
                return False
        
        # 🎯 ОДНА ЦІНА ПІДТВЕРДЖЕННЯ: отримуємо миттєву ціну БЕЗПОСЕРЕДНЬО перед закриттям
        ticker = fetch_xt_ticker(xt, symbol)
        if not ticker or 'last' not in ticker:
            logging.error(f"[XT {symbol}] ❌ Не вдалося отримати миттєву ціну для закриття")
            return False
        
        instant_price = float(ticker['last'])  # МИТТЄВА ЦІНА для точного закриття
        
        # Застосовуємо точність біржі
        try:
            market = xt.market(symbol)
            contracts_precise = xt.amount_to_precision(symbol, exact_contracts)
            min_amount = market.get('limits', {}).get('amount', {}).get('min', 1)
            
            if float(contracts_precise) < min_amount:
                logging.warning(f"[XT {symbol}] ⚠️ Розмір {contracts_precise} < мінімум {min_amount}")
                contracts_precise = str(min_amount)
                
            contracts_final = float(contracts_precise)
            
        except Exception as e:
            logging.warning(f"[XT {symbol}] ⚠️ Помилка market precision: {e}, використовуємо fallback")
            contracts_final = max(1.0, round(exact_contracts))
        
        logging.info(f"[XT {symbol}] 🎯 INSTANT CLOSE: exact={exact_contracts:.6f}, final={contracts_final}, instant_price=${instant_price:.6f}")
        
        order = xt.create_order(
            symbol, 
            'market', 
            'sell' if side == "LONG" else 'buy', 
            contracts_final,  # Точний розмір з біржі
            None, 
            {'type': 'swap', 'settle': 'usdt', 'reduceOnly': True}
        )
        logging.info(f"[XT FUTURES] Закрито {side} позицію {symbol}: {contracts_final} контрактів (notional=${contracts_final * instant_price:.2f})")
        
        # 🔥 РОЗРАХУНОК РЕАЛЬНОГО P&L для Telegram сповіщення
        notional_value = contracts_final * instant_price
        
        # 🔥 РОБАСТНИЙ P&L РОЗРАХУНОК (як порадив architect)
        real_pnl_dollars = 0.0
        try:
            # Отримуємо entry_price з live позиції замість bot.active_positions (уникаємо циклічної залежності)
            entry_price = None
            if actual_position and 'entryPrice' in actual_position:
                entry_price = float(actual_position['entryPrice'])
            elif actual_position and 'info' in actual_position and 'avgEntryPrice' in actual_position['info']:
                entry_price = float(actual_position['info']['avgEntryPrice'])
            
            if entry_price and entry_price > 0:
                # SIDE-AWARE P&L розрахунок (як порадив architect)
                if side.upper() == "LONG":
                    pnl_usd = (instant_price - entry_price) * exact_contracts
                else:  # SHORT
                    pnl_usd = (entry_price - instant_price) * exact_contracts
                
                real_pnl_dollars = pnl_usd
                pnl_pct = (pnl_usd / notional_value) * 100 if notional_value > 0 else 0
                
                logging.info(f"[XT {symbol}] 💰 P&L РОБАСТНИЙ: entry=${entry_price:.6f}, exit=${instant_price:.6f}, contracts={exact_contracts:.6f}, PnL=${real_pnl_dollars:.2f} ({pnl_pct:.2f}%)")
            else:
                logging.warning(f"[XT {symbol}] ⚠️ Не вдалося отримати entry_price з live позиції")
        except Exception as e:
            logging.warning(f"[XT {symbol}] ⚠️ Помилка робастного P&L розрахунку: {e}")
        
        # Відправляємо Telegram сповіщення з реальним P&L
        from utils import send_telegram_trade_notification
        send_telegram_trade_notification(symbol, side, notional_value, instant_price, action="CLOSED (XT)", profit=real_pnl_dollars)
        
        return True
    except Exception as e:
        # ДЕТАЛЬНЕ TELEGRAM СПОВІЩЕННЯ ПРО ПОМИЛКУ ЗАКРИТТЯ XT ПОЗИЦІЇ (як просив користувач)
        price_display = instant_price if instant_price > 0 else "N/A"
        error_msg = f"❌ **ПОМИЛКА ЗАКРИТТЯ XT ПОЗИЦІЇ**\n"\
                   f"📊 Символ: **{symbol.replace('/USDT:USDT', '')}** ({side})\n"\
                   f"💰 Розмір: **${usd_amount:.2f}**\n"\
                   f"📉 Ціна: **${price_display}**\n"\
                   f"🏪 Біржа: **XT.COM**\n"\
                   f"❌ **ПОМИЛКА**: `{str(e)[:100]}...`\n"\
                   f"⏰ Час: **{time.strftime('%H:%M:%S')}**"
        from utils import send_telegram
        from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        # ❌ ПОМИЛКИ НЕ ВІДПРАВЛЯЄМО В ГРУПУ - тільки в приватний бот
        send_telegram(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, error_msg)
        logging.error("XT Close order error: %s %s", type(e).__name__, e)
        return False

def get_xt_price(xt, symbol):
    """Отримання поточної ціни з XT"""
    try:
        ticker = fetch_xt_ticker(xt, symbol)
        if ticker and 'last' in ticker:
            return float(ticker['last'])
        return None
    except Exception as e:
        logging.debug(f"Помилка отримання XT ціни для {symbol}: {e}")
        return None

def get_xt_open_positions(xt):
    """Отримання відкритих futures позицій XT"""
    try:
        if DRY_RUN:
            return []
        
        # XT.com може вимагати інші параметри
        positions = xt.fetch_positions()
        # Фільтруємо тільки відкриті позиції з розміром > 0
        open_positions = []
        
        if not positions:
            return []
            
        for pos in positions:
            try:
                # Перевіряємо різні поля для розміру позиції
                size = float(pos.get('size', 0) or 0)
                contracts = float(pos.get('contracts', 0) or 0)
                notional = float(pos.get('notional', 0) or 0)
                
                # 🔧 ФІКС ПРИЗРАЧНИХ ПОЗИЦІЙ: позиція відкрита тільки якщо має реальну вартість
                # Розраховуємо реальну вартість позиції в USDT  
                real_value = abs(notional) if abs(notional) > 0 else 0
                if real_value == 0 and abs(contracts) > 0:
                    # Якщо notional=0, але є контракти - розраховуємо через ціну
                    mark_price_temp = float(pos.get('markPrice', 0) or pos.get('mark_price', 0) or 0)
                    if mark_price_temp == 0 and pos.get('symbol'):
                        try:
                            mark_price_temp = get_xt_price(xt, pos.get('symbol')) or 0
                        except:
                            mark_price_temp = 0
                    real_value = abs(contracts) * mark_price_temp
                
                # Позиція реальна тільки якщо вартість > $0.01 (1 цент)
                if real_value > 0.01:
                    # Безпечно отримуємо значення з обробкою None
                    symbol = pos.get('symbol', '') or ''
                    side = pos.get('side', 'long') or 'long'
                    unrealized_pnl = float(pos.get('unrealizedPnl', 0) or 0)
                    percentage = float(pos.get('percentage', 0) or 0)
                    entry_price = float(pos.get('entryPrice', 0) or pos.get('entry_price', 0) or 0)
                    mark_price = float(pos.get('markPrice', 0) or pos.get('mark_price', 0) or 0)
                    
                    # 🔧 ФІКС XT markPrice=0.0: отримуємо реальну ціну з тікера
                    if mark_price == 0.0 and symbol:
                        try:
                            real_price = get_xt_price(xt, symbol)
                            if real_price and real_price > 0:
                                mark_price = real_price
                                logging.info(f"🔧 XT ФІКС [{symbol}]: markPrice=0.0 → використовуємо ticker={mark_price}")
                            else:
                                logging.warning(f"⚠️ XT [{symbol}]: Не вдалося отримати ціну з тікера")
                        except Exception as price_error:
                            logging.warning(f"⚠️ XT [{symbol}]: Помилка отримання ціни: {price_error}")
                            pass
                    
                    # 🔧 ФІКС РОЗМІРУ ПОЗИЦІЙ: Розраховуємо правильний розмір в доларах для закриття
                    calculated_size = abs(contracts) if abs(contracts) > 0 else abs(size)
                    # Розмір позиції в доларах = контракти * ціна (для коректного закриття)
                    size_usdt = calculated_size * mark_price if mark_price > 0 else abs(notional)
                    
                    # Отримуємо баланс кожної монетки
                    base_asset = symbol.replace('/USDT:USDT', '').replace('/USDT', '')
                    asset_balance = calculated_size  # Кількість монеток
                    margin = float(pos.get('collateral', 0) or pos.get('initialMargin', 0) or 0)
                    leverage = float(pos.get('leverage', 1) or 1)
                    
                    open_positions.append({
                        'symbol': symbol,
                        'side': side.upper(),
                        'size': calculated_size,  # Розмір в контрактах
                        'size_usdt': size_usdt,   # 🔧 ФІКС: Розмір в доларах для закриття!
                        'asset_balance': asset_balance,  # 💰 БАЛАНС КОЖНОЇ МОНЕТКИ
                        'base_asset': base_asset,        # 💰 НАЗВА МОНЕТКИ  
                        'margin': margin,                # 💰 МАРЖА В USDT
                        'leverage': leverage,            # 💰 ПЛЕЧЕ
                        'unrealizedPnl': unrealized_pnl,
                        'percentage': percentage,
                        'entryPrice': entry_price,
                        'markPrice': mark_price,
                        'notional': abs(notional)
                    })
            except (ValueError, TypeError) as ve:
                # Пропускаємо позиції з некоректними даними
                logging.debug(f"Пропускаємо позицію XT з некоректними даними: {ve}")
                continue
                
        logging.info(f"XT.com знайдено {len(open_positions)} відкритих позицій")
        return open_positions
        
    except Exception as e:
        logging.error(f"XT позиції помилка: {e}")
        return []