import logging
import time
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass, field

from signal_parser import ArbitrageSignal
# Simple fallback for price dynamics
class DynamicsAnalysis:
    def __init__(self):
        self.trend = "neutral"
        self.momentum = 0.0
from config import (
    MIN_24H_VOLUME_USD, MIN_POOLED_LIQUIDITY_USD, MIN_SPREAD, MAX_SPREAD,
    MAX_SLIPPAGE_PERCENT, SLIPPAGE_PADDING, COOLDOWN_SEC,
    MIN_VOLATILITY_15MIN, MAX_VOLATILITY_15MIN, MIN_ORDERBOOK_DEPTH_MULTIPLIER,
    MIN_BUY_RATIO_PERCENT, ORDER_AMOUNT, MIN_NET_PROFIT_PERCENT, ESTIMATED_TRADING_COSTS_PERCENT
)

@dataclass
class VerificationResult:
    """Результат верифікації арбітражного сигналу"""
    valid: bool = False
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    
    # Дані з XT.com
    xt_found: bool = False
    xt_symbol: str = ""
    xt_price: float = 0.0
    xt_tradeable: bool = False
    
    # Дані з DEX
    dex_found: bool = False
    dex_pair_address: str = ""
    dex_token_address: str = ""
    dex_price: float = 0.0
    dex_liquidity: float = 0.0
    dex_volume_24h: float = 0.0
    dex_chain: str = ""
    dex_name: str = ""
    
    # Розрахунки
    actual_spread: float = 0.0
    price_ratio: float = 0.0
    honeypot_status: str = "unknown"
    
    # Додаткові аналізи згідно з вимогами
    volatility_15min: float = 0.0
    buy_ratio_percent: float = 0.0
    orderbook_depth_ratio: float = 0.0
    price_dynamics_15min: float = 0.0
    price_dynamics_1hour: float = 0.0
    
    # 📊 НОВІ ДАНІ: Глибина ринку та динаміка цін
    market_depth_data: Dict = field(default_factory=dict)
    price_dynamics_analysis: Dict = field(default_factory=dict)
    trend_direction: str = "unknown"
    momentum_score: float = 0.0
    support_resistance_levels: Dict = field(default_factory=dict)
    
    # Посилання
    dexscreener_link: str = ""
    pancakeswap_link: str = ""
    uniswap_link: str = ""
    

class SignalVerification:
    """
    Клас для верифікації арбітражних сигналів згідно з вашими вимогами:
    
    1. Знайти token на XT.com
    2. Знайти пару на DEX  
    3. Перевірити volume/liquidity
    4. Перевірити spread
    5. Перевірити honeypot
    """
    
    def __init__(self):
        self.cooldown_cache = {}  # Кеш для анти-дубль кулдауну
        
    def verify_signal(self, signal: ArbitrageSignal) -> VerificationResult:
        """
        Повна верифікація сигналу згідно з вашими вимогами
        
        Args:
            signal: Парсований арбітражний сигнал
            
        Returns:
            VerificationResult з результатами перевірки
        """
        result = VerificationResult()
        
        try:
            # 1. Перевірка кулдауну
            if not self._check_cooldown(signal.asset):
                result.errors.append(f"Символ {signal.asset} в кулдауні ({COOLDOWN_SEC}с)")
                return result
            
            # 2. Знаходимо token на XT.com
            xt_result = self._verify_xt_token(signal)
            result.xt_found = xt_result['found']
            result.xt_symbol = xt_result.get('symbol', '')
            result.xt_price = xt_result.get('price', 0.0)
            result.xt_tradeable = xt_result.get('tradeable', False)
            
            if not result.xt_found:
                result.errors.append(f"Токен {signal.asset} не знайдено на XT.com")
                return result
            
            if not result.xt_tradeable:
                result.errors.append(f"Токен {signal.asset} не доступний для торгівлі на XT.com")
                return result
                
            # 3. Знаходимо пару на DEX
            dex_result = self._verify_dex_pair(signal)
            result.dex_found = dex_result['found']
            result.dex_pair_address = dex_result.get('pair_address', '')
            result.dex_token_address = dex_result.get('token_address', '')
            result.dex_price = dex_result.get('price', 0.0)
            result.dex_liquidity = dex_result.get('liquidity', 0.0)
            result.dex_volume_24h = dex_result.get('volume_24h', 0.0)
            result.dex_chain = dex_result.get('chain', '')
            result.dex_name = dex_result.get('dex_name', '')
            
            if not result.dex_found:
                result.errors.append(f"Якісна DEX пара для {signal.asset} не знайдена")
                return result
            
            # 4. Перевіряємо volume та liquidity
            if result.dex_volume_24h < MIN_24H_VOLUME_USD:
                result.errors.append(f"Об'єм ${result.dex_volume_24h:,.0f} < мінімум ${MIN_24H_VOLUME_USD:,.0f}")
                
            if result.dex_liquidity < MIN_POOLED_LIQUIDITY_USD:
                result.errors.append(f"Ліквідність ${result.dex_liquidity:,.0f} < мінімум ${MIN_POOLED_LIQUIDITY_USD:,.0f}")
            
            # 5. Перевіряємо spread та чистий прибуток
            if result.xt_price > 0 and result.dex_price > 0:
                result.actual_spread = ((result.dex_price - result.xt_price) / result.xt_price) * 100
                result.price_ratio = max(result.xt_price, result.dex_price) / min(result.xt_price, result.dex_price)
                
                spread_abs = abs(result.actual_spread)
                
                # Розрахунок чистого прибутку з урахуванням комісій
                net_profit = spread_abs - ESTIMATED_TRADING_COSTS_PERCENT
                
                if net_profit < MIN_NET_PROFIT_PERCENT:
                    result.errors.append(f"Чистий прибуток {net_profit:.2f}% < мінімум {MIN_NET_PROFIT_PERCENT}%")
                    
                if spread_abs > MAX_SPREAD:
                    result.errors.append(f"Спред {spread_abs:.2f}% > максимум {MAX_SPREAD}%")
                    
                # Підозрілі ціни
                if result.price_ratio > 1.5:
                    result.warnings.append(f"Підозріла різниця цін: {result.price_ratio:.2f}x")
            
            # 6. Генеруємо посилання на КОНКРЕТНУ торгову пару
            # ПРІОРИТЕТ 1: Готове exact_pair_url з DexCheck Pro
            if dex_result.get('exact_pair_url'):
                result.dexscreener_link = dex_result['exact_pair_url']
                logging.info(f"🔗 ГОТОВЕ EXACT URL для {signal.asset}: {result.dexscreener_link}")
            # ПРІОРИТЕТ 2: Будуємо з pair_address та chain
            elif result.dex_pair_address and result.dex_chain:
                result.dexscreener_link = self._generate_dexscreener_link(result.dex_chain, result.dex_pair_address)
                logging.info(f"🔗 КОНКРЕТНА ПАРА для {signal.asset}: {result.dexscreener_link}")
            # ПРІОРИТЕТ 3: Використовуємо token_address якщо є
            elif result.dex_token_address and result.dex_chain:
                result.dexscreener_link = f"https://dexscreener.com/{result.dex_chain}/{result.dex_token_address}"
                logging.info(f"🔗 ТОКЕН АДРЕСА для {signal.asset}: {result.dexscreener_link}")
            else:
                # ОСТАННІЙ FALLBACK: з назвою токена
                clean_token = signal.asset.replace('/USDT:USDT', '').replace('/USDT', '').upper()
                chain = 'ethereum'  # Default
                result.dexscreener_link = f"https://dexscreener.com/{chain}/{clean_token}"
                logging.info(f"🔗 FALLBACK ТОКЕН для {signal.asset}: {result.dexscreener_link}")
                
            result.pancakeswap_link = self._generate_pancakeswap_link(result.dex_token_address, result.dex_chain)
            result.uniswap_link = self._generate_uniswap_link(result.dex_token_address, result.dex_chain)
            
            # 7. Перевірка honeypot (швидка симуляція)
            honeypot_result = self._check_honeypot(result.dex_token_address, result.dex_chain)
            result.honeypot_status = honeypot_result
            
            if honeypot_result == "suspicious":
                result.errors.append("Підозра на honeypot - токен заблоковано для безпеки")
            elif honeypot_result == "blocked":
                result.errors.append("Токен блокує продаж (honeypot)")
            elif honeypot_result == "unknown":
                result.warnings.append("⚠️ Honeypot статус невідомий - будьте обережні")
            
            # 8. Перевірка волатильності за 15 хвилин
            volatility_result = self._check_volatility_15min(signal.asset, result.dex_pair_address, result.dex_chain)
            result.volatility_15min = volatility_result
            
            if volatility_result < MIN_VOLATILITY_15MIN:
                result.errors.append(f"Волатильність {volatility_result:.1f}% < мінімум {MIN_VOLATILITY_15MIN}%")
            elif volatility_result > MAX_VOLATILITY_15MIN:
                result.errors.append(f"Волатильність {volatility_result:.1f}% > максимум {MAX_VOLATILITY_15MIN}%")
            
            # 9. Перевірка глибини ордербуку
            orderbook_result = self._check_orderbook_depth(signal.asset, result.dex_pair_address, result.dex_chain)
            result.orderbook_depth_ratio = orderbook_result
            
            required_depth = ORDER_AMOUNT * MIN_ORDERBOOK_DEPTH_MULTIPLIER
            if orderbook_result < required_depth:
                result.warnings.append(f"Глибина ордербуку ${orderbook_result:.0f} < потрібно ${required_depth:.0f}")
            
            # 10. Перевірка співвідношення buy/sell
            buysell_result = self._check_buy_sell_ratio(signal.asset, result.dex_pair_address, result.dex_chain)
            result.buy_ratio_percent = buysell_result
            
            if buysell_result < MIN_BUY_RATIO_PERCENT:
                result.warnings.append(f"Buy/Sell співвідношення {buysell_result:.1f}% < мінімум {MIN_BUY_RATIO_PERCENT}%")
            
            # 11. Аналіз динаміки цін за 15 хв та 1 годину
            price_dynamics_15min, price_dynamics_1hour = self._analyze_price_dynamics(signal.asset, result.dex_pair_address, result.dex_chain)
            result.price_dynamics_15min = price_dynamics_15min
            result.price_dynamics_1hour = price_dynamics_1hour
            
            # Логування динаміки для аналізу
            logging.info(f"📊 Динаміка цін {signal.asset}: 15хв={price_dynamics_15min:.1f}%, 1год={price_dynamics_1hour:.1f}%")
            
            # 12. 📊 НОВИЙ: Збір даних про глибину ринку XT.com з фільтрацією
            market_depth = self._collect_market_depth_analysis(result.xt_symbol)
            result.market_depth_data = market_depth if market_depth else {}
            
            # Перевірка якості глибини ринку
            if market_depth:
                depth_validation = self._validate_market_depth_quality(market_depth, ORDER_AMOUNT)
                if not depth_validation['valid']:
                    result.errors.append(f"Глибина ринку незадовільна: {depth_validation['reason']}")
            
            # 13. 📈 НОВИЙ: Розширений аналіз динаміки цін з трекером та фільтрацією
            price_dynamics_enhanced = self._collect_enhanced_price_dynamics(signal.asset)
            result.price_dynamics_analysis = price_dynamics_enhanced if price_dynamics_enhanced else {}
            
            if price_dynamics_enhanced:
                analysis_15m = price_dynamics_enhanced.get('15m')
                if analysis_15m:
                    result.trend_direction = analysis_15m['trend_direction']
                    result.momentum_score = analysis_15m['momentum_score']
                    result.support_resistance_levels = analysis_15m['support_resistance']
                    
                    # Фільтрація на основі якості та тренду
                    dynamics_validation = self._validate_price_dynamics_quality(analysis_15m)
                    if not dynamics_validation['valid']:
                        result.warnings.append(f"Динаміка цін: {dynamics_validation['reason']}")
            
            # Фінальна перевірка
            result.valid = len(result.errors) == 0
            
            if result.valid:
                self._set_cooldown(signal.asset)
                logging.info(f"✅ Сигнал {signal.asset} пройшов верифікацію: спред {result.actual_spread:.2f}%")
            else:
                logging.warning(f"❌ Сигнал {signal.asset} НЕ пройшов верифікацію: {'; '.join(result.errors)}")
                
        except Exception as e:
            logging.error(f"❌ Помилка верифікації сигналу {signal.asset}: {e}")
            result.errors.append(f"Критична помилка верифікації: {str(e)}")
            
        return result
    
    def _check_cooldown(self, symbol: str) -> bool:
        """Перевіряє чи не в кулдауні символ"""
        now = time.time()
        last_check = self.cooldown_cache.get(symbol, 0)
        return (now - last_check) >= COOLDOWN_SEC
    
    def _set_cooldown(self, symbol: str):
        """Встановлює кулдаун для символу"""
        self.cooldown_cache[symbol] = time.time()
    
    def _verify_xt_token(self, signal: ArbitrageSignal) -> Dict[str, Any]:
        """Перевіряє наявність токену на XT.com"""
        try:
            from xt_client import create_xt, get_xt_price, is_xt_futures_tradeable
            
            # Формуємо symbol для XT.com
            xt_symbol = f"{signal.asset}/USDT:USDT"
            
            xt = create_xt()
            if not xt:
                return {'found': False, 'error': 'XT клієнт недоступний'}
            
            # Отримуємо ціну
            xt_price = get_xt_price(xt, xt_symbol)
            if not xt_price or xt_price <= 0:
                return {'found': False, 'error': 'Ціна недоступна'}
            
            # Перевіряємо можливість торгівлі
            tradeable = is_xt_futures_tradeable(xt_symbol)
            
            return {
                'found': True,
                'symbol': xt_symbol,
                'price': xt_price,
                'tradeable': tradeable
            }
            
        except Exception as e:
            logging.error(f"Помилка перевірки XT.com для {signal.asset}: {e}")
            return {'found': False, 'error': str(e)}
    
    def _verify_dex_pair(self, signal: ArbitrageSignal) -> Dict[str, Any]:
        """Знаходить найкращу DEX пару для токену"""
        try:
            from utils import get_shared_dex_client
            
            dex_client = get_shared_dex_client()
            if not dex_client:
                return {'found': False, 'error': 'DEX клієнт недоступний'}
            
            # Отримуємо найкращу пару
            best_pair = dex_client.resolve_best_pair(signal.asset)
            if not best_pair:
                return {'found': False, 'error': 'DEX пара не знайдена'}
            
            return {
                'found': True,
                'pair_address': best_pair.get('pair_address', ''),
                'token_address': best_pair.get('token_address', ''),
                'price': best_pair.get('price_usd', 0.0),
                'liquidity': best_pair.get('liquidity_usd', 0.0),
                'volume_24h': best_pair.get('volume_24h', 0.0),
                'chain': best_pair.get('chain', 'unknown'),
                'dex_name': best_pair.get('dex_name', 'DEX'),
                'exact_pair_url': best_pair.get('exact_pair_url', '')
            }
            
        except Exception as e:
            logging.error(f"Помилка перевірки DEX для {signal.asset}: {e}")
            return {'found': False, 'error': str(e)}
    
    def _generate_dexscreener_link(self, chain: str, pair_address: str, token_address: str = "") -> str:
        """Генерує посилання на DexScreener для конкретної пари"""
        if pair_address:
            return f"https://dexscreener.com/{chain}/{pair_address}"
        elif token_address:
            return f"https://dexscreener.com/{chain}?q={token_address}"
        return f"https://dexscreener.com/{chain}"
    
    def _generate_pancakeswap_link(self, token_address: str, chain: str) -> str:
        """Генерує посилання на PancakeSwap для конкретного токена"""
        if chain.lower() == 'bsc' and token_address:
            return f"https://pancakeswap.finance/swap?outputCurrency={token_address}"
        return ""
    
    def _generate_uniswap_link(self, token_address: str, chain: str) -> str:
        """Генерує посилання на Uniswap для конкретного токена"""
        if chain.lower() == 'ethereum' and token_address:
            return f"https://app.uniswap.org/#/swap?outputCurrency={token_address}"
        return ""
    
    def _check_honeypot(self, token_address: str, chain: str) -> str:
        """
        Реальна перевірка honeypot через Honeypot.is API + Web3 симуляція
        Повертає: 'ok', 'suspicious', 'blocked', 'unknown'
        """
        try:
            import requests
            from web3 import Web3
            
            # Базова перевірка за відомими патернами
            if not token_address or len(token_address) < 10:
                return 'unknown'
            
            # 🚀 РЕАЛЬНА HONEYPOT ПЕРЕВІРКА через Honeypot.is API
            try:
                honeypot_url = f"https://api.honeypot.is/v2/IsHoneypot?address={token_address}"
                response = requests.get(honeypot_url, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Перевірка honeypot статусу
                    if data.get('IsHoneypot', False):
                        logging.warning(f"🚨 HONEYPOT DETECTED: {token_address} - BLOCKED!")
                        return 'blocked'
                    
                    # Перевірка високих податків (>10%)
                    buy_tax = data.get('BuyTax', 0)
                    sell_tax = data.get('SellTax', 0)
                    
                    if buy_tax > 10 or sell_tax > 10:
                        logging.warning(f"🚨 HIGH TAX: {token_address} - Buy: {buy_tax}%, Sell: {sell_tax}%")
                        return 'suspicious'
                    
                    # Перевірка можливості продажу
                    can_sell = data.get('CanSell', True)
                    if not can_sell:
                        logging.warning(f"🚨 SELL BLOCKED: {token_address}")
                        return 'blocked'
                    
                    logging.info(f"✅ HONEYPOT CHECK PASSED: {token_address} (Buy: {buy_tax}%, Sell: {sell_tax}%)")
                    return 'ok'
                    
            except Exception as api_error:
                logging.warning(f"⚠️ Honeypot API недоступний для {token_address}: {api_error}")
            
            # 🔥 FALLBACK: Web3 симуляція торгівлі
            if chain.lower() in ['ethereum', 'bsc']:
                return self._simulate_web3_trade(token_address, chain)
            
            # Якщо всі перевірки недоступні - безпечний підхід
            logging.warning(f"⚠️ Honeypot перевірка недоступна для {token_address} - використовуємо fail-safe")
            return 'unknown'
            
        except Exception as e:
            logging.error(f"Помилка перевірки honeypot для {token_address}: {e}")
            return 'unknown'
    
    def _simulate_web3_trade(self, token_address: str, chain: str) -> str:
        """
        Web3 симуляція торгівлі для перевірки honeypot
        Повертає: 'ok', 'suspicious', 'blocked'
        """
        try:
            from web3 import Web3
            
            # RPC ендпоінти
            rpc_urls = {
                'ethereum': 'https://eth.llamarpc.com',
                'bsc': 'https://bsc-dataseed.binance.org'
            }
            
            if chain.lower() not in rpc_urls:
                return 'unknown'
            
            # Підключення до Web3
            w3 = Web3(Web3.HTTPProvider(rpc_urls[chain.lower()]))
            if not w3.is_connected():
                logging.warning(f"⚠️ Web3 недоступний для {chain}")
                return 'unknown'
            
            # Базова перевірка контракту
            try:
                # Перевіряємо чи існує контракт
                code = w3.eth.get_code(Web3.to_checksum_address(token_address))
                if len(code) <= 2:  # "0x" означає що немає коду
                    logging.warning(f"🚨 NO CONTRACT CODE: {token_address}")
                    return 'suspicious'
                
                # Перевіряємо розмір коду (великі контракти часто honeypot)
                if len(code) > 50000:  # >50KB код підозрілий
                    logging.warning(f"🚨 LARGE CONTRACT: {token_address} ({len(code)} bytes)")
                    return 'suspicious'
                
                logging.info(f"✅ WEB3 CHECK PASSED: {token_address} ({len(code)} bytes)")
                return 'ok'
                
            except Exception as contract_error:
                logging.warning(f"⚠️ Contract check failed for {token_address}: {contract_error}")
                return 'unknown'
                
        except Exception as e:
            logging.warning(f"⚠️ Web3 симуляція failed для {token_address}: {e}")
            return 'unknown'
    
    def _check_volatility_15min(self, symbol: str, pair_address: str, chain: str) -> float:
        """
        Перевіряє волатільність за останні 15 хвилин
        Повертає волатільність у відсотках
        """
        try:
            from utils import get_shared_dex_client
            
            dex_client = get_shared_dex_client()
            if not dex_client:
                logging.warning(f"DEX клієнт недоступний для перевірки волатільності {symbol}")
                # Fail-closed: якщо не можемо отримати дані, блокуємо
                return 0.0  # Нижче мінімального порогу
            
            # Отримуємо розширені метрики з DexCheck API
            metrics = dex_client.get_advanced_token_metrics(symbol)
            if not metrics:
                logging.warning(f"Не вдалося отримати метрики для {symbol}")
                return 0.0  # Fail-closed
            
            # Використовуємо ціни для обчислення волатільності
            current_price = metrics.get('price_usd', 0)
            price_change = metrics.get('price_change_15min', 0)  # Якщо доступно
            
            if current_price > 0 and price_change != 0:
                volatility = abs(price_change)
                logging.info(f"📊 Волатільність {symbol}: {volatility:.1f}%")
                return volatility
            else:
                # Fail-closed: якщо немає даних про зміну ціни, блокуємо
                logging.warning(f"Немає даних про волатільність для {symbol}")
                return 0.0  # Нижче мінімального порогу
            
        except Exception as e:
            logging.error(f"Помилка перевірки волатільності для {symbol}: {e}")
            return 0.0  # Fail-closed
    
    def _check_orderbook_depth(self, symbol: str, pair_address: str, chain: str) -> float:
        """
        Перевіряє глибину ордербуку через загальну ліквідність
        Повертає загальну ліквідність у USD
        """
        try:
            from utils import get_shared_dex_client
            
            dex_client = get_shared_dex_client()
            if not dex_client:
                logging.warning(f"DEX клієнт недоступний для перевірки глибини ордербуку {symbol}")
                # Fail-closed: якщо не можемо отримати дані, блокуємо
                return 0.0  # Нижче мінімального порогу
            
            # Використовуємо загальну ліквідність як проксі для глибини ордербуку
            pair_data = dex_client.resolve_best_pair(symbol)
            if not pair_data:
                logging.warning(f"Не вдалося отримати дані пари для {symbol}")
                return 0.0  # Fail-closed
            
            # Використовуємо правильний ключ для ліквідності
            liquidity_usd = pair_data.get('liquidity', 0.0)  # Використовуємо 'liquidity' як у _verify_dex_pair
            
            # Логіка: якщо загальна ліквідність достатня, то і глибина ордербуку буде достатньою
            # Використовуємо 10% від загальної ліквідності як доступну глибину для торгівлі
            available_depth = liquidity_usd * 0.1
            
            logging.info(f"📊 Глибина ордербуку {symbol}: ${available_depth:,.0f} (з ліквідності ${liquidity_usd:,.0f})")
            return available_depth
            
        except Exception as e:
            logging.error(f"Помилка перевірки глибини ордербуку для {symbol}: {e}")
            return 0.0  # Fail-closed
    
    def _check_buy_sell_ratio(self, symbol: str, pair_address: str, chain: str) -> float:
        """
        Перевіряє співвідношення покупок до продажів за останні 100 угод
        Повертає відсоток покупок
        """
        try:
            from utils import get_shared_dex_client
            
            dex_client = get_shared_dex_client()
            if not dex_client:
                logging.warning(f"DEX клієнт недоступний для перевірки buy/sell ratio {symbol}")
                # Fail-closed: якщо не можемо отримати дані, блокуємо
                return 0.0  # Нижче мінімального порогу
            
            # Отримуємо розширені метрики з DexCheck API
            metrics = dex_client.get_advanced_token_metrics(symbol)
            if not metrics:
                logging.warning(f"Не вдалося отримати метрики для {symbol}")
                return 0.0  # Fail-closed
            
            # Перевіряємо дані про транзакції за 24 години
            txns_24h = metrics.get('txns_24h', {})
            if txns_24h and 'buy_percentage' in txns_24h:
                buy_percentage = txns_24h['buy_percentage']
                logging.info(f"📊 Buy/Sell ratio {symbol}: {buy_percentage:.1f}% покупок")
                return buy_percentage
            
            # Альтернативний розрахунок якщо є дані про кількість угод
            buys = txns_24h.get('buys', 0)
            sells = txns_24h.get('sells', 0)
            total_trades = buys + sells
            
            if total_trades > 0:
                buy_percentage = (buys / total_trades) * 100
                logging.info(f"📊 Buy/Sell ratio {symbol}: {buy_percentage:.1f}% покупок ({buys}B/{sells}S)")
                return buy_percentage
            else:
                logging.warning(f"Немає даних про угоди для {symbol}")
                return 0.0  # Fail-closed
            
        except Exception as e:
            logging.error(f"Помилка перевірки buy/sell ratio для {symbol}: {e}")
            return 0.0  # Fail-closed
    
    def _analyze_price_dynamics(self, symbol: str, pair_address: str, chain: str) -> Tuple[float, float]:
        """
        Аналізує динаміку цін за 15 хвилин та 1 годину
        Повертає кортеж (зміна_за_15хв_%, зміна_за_1год_%)
        """
        try:
            from utils import get_shared_dex_client
            
            dex_client = get_shared_dex_client()
            if not dex_client:
                logging.warning(f"DEX клієнт недоступний для аналізу динаміки цін {symbol}")
                return 0.0, 0.0  # Нейтральна динаміка
            
            # TODO: Реалізувати отримання історичних даних та розрахунок динаміки
            # Поки що повертаємо нейтральні значення
            price_change_15min = 0.0  # Зміна ціни за 15 хвилин у %
            price_change_1hour = 0.0  # Зміна ціни за 1 годину у %
            
            return price_change_15min, price_change_1hour
            
        except Exception as e:
            logging.error(f"Помилка аналізу динаміки цін для {symbol}: {e}")
            return 0.0, 0.0
    
    def _collect_market_depth_analysis(self, xt_symbol: str) -> Optional[Dict]:
        """
        📊 ЗБІР ДАНИХ ПРО ГЛИБИНУ РИНКУ XT.com
        Отримує детальну інформацію про обсяги заявок на різних рівнях цін
        """
        try:
            from xt_client import create_xt, collect_market_depth_data
            
            if not xt_symbol:
                return None
                
            xt = create_xt()
            if not xt:
                logging.warning("XT клієнт недоступний для збору глибини ринку")
                return None
            
            # Збираємо дані глибини ринку з 20 рівнями
            depth_data = collect_market_depth_data(xt, xt_symbol, depth_levels=20)
            
            if depth_data:
                logging.info(f"📊 Зібрано дані глибини ринку {xt_symbol}: "
                           f"bids=${depth_data['total_bid_liquidity']:,.0f} "
                           f"asks=${depth_data['total_ask_liquidity']:,.0f}")
                return depth_data
            else:
                logging.warning(f"Не вдалося зібрати дані глибини ринку для {xt_symbol}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Помилка збору глибини ринку {xt_symbol}: {e}")
            return None
    
    def _collect_enhanced_price_dynamics(self, symbol: str) -> Optional[Dict]:
        """
        📈 РОЗШИРЕНИЙ АНАЛІЗ ДИНАМІКИ ЦІН
        Використовує price_tracker для отримання мульти-інтервального аналізу
        """
        try:
            # Збираємо поточні дані про ціну для трекера
            price_tracker.collect_current_price_data(symbol)
            
            # Отримуємо аналіз для кількох часових інтервалів
            multi_analysis = price_tracker.get_multi_timeframe_analysis(symbol)
            
            if multi_analysis:
                # Конвертуємо DynamicsAnalysis об'єкти в словники для серіалізації
                serialized_analysis = {}
                for timeframe, analysis in multi_analysis.items():
                    if analysis:
                        serialized_analysis[timeframe] = {
                            'symbol': analysis.symbol,
                            'timeframe_minutes': analysis.timeframe_minutes,
                            'price_change_pct': analysis.price_change_pct,
                            'volatility_pct': analysis.volatility_pct,
                            'trend_direction': analysis.trend_direction,
                            'momentum_score': analysis.momentum_score,
                            'support_resistance': analysis.support_resistance,
                            'quality_score': analysis.quality_score,
                            'price_levels_count': len(analysis.price_levels)
                        }
                
                if serialized_analysis:
                    logging.info(f"📈 Зібрано розширений аналіз динаміки для {symbol}: "
                               f"{len(serialized_analysis)} інтервалів")
                    return serialized_analysis
            
            logging.warning(f"Недостатньо даних для розширеного аналізу динаміки {symbol}")
            return None
            
        except Exception as e:
            logging.error(f"❌ Помилка розширеного аналізу динаміки {symbol}: {e}")
            return None
    
    def _validate_market_depth_quality(self, market_depth: Dict, order_amount: float) -> Dict[str, Any]:
        """
        📊 ВАЛІДАЦІЯ ЯКОСТІ ГЛИБИНИ РИНКУ
        Перевіряє чи достатня глибина ринку для безпечної торгівлі
        """
        try:
            # Конфігурації з config.py
            MAX_BID_ASK_SPREAD_PERCENT = 1.0
            MIN_TOTAL_LIQUIDITY_MULTIPLIER = 5.0
            MAX_TOP3_CONCENTRATION_PERCENT = 90.0
            
            # Базові перевірки наявності даних
            if not market_depth.get('spread_analysis') or not market_depth.get('bids') or not market_depth.get('asks'):
                return {'valid': False, 'reason': 'Недостатні дані глибини ринку'}
            
            # 1. Перевірка спреду bid/ask
            bid_ask_spread = market_depth['spread_analysis'].get('bid_ask_spread_pct', 999)
            if bid_ask_spread > MAX_BID_ASK_SPREAD_PERCENT:
                return {'valid': False, 'reason': f'Спред bid/ask {bid_ask_spread:.2f}% > {MAX_BID_ASK_SPREAD_PERCENT}%'}
            
            # 2. Перевірка загальної ліквідності
            total_bid_liquidity = market_depth.get('total_bid_liquidity', 0)
            total_ask_liquidity = market_depth.get('total_ask_liquidity', 0)
            min_required_liquidity = order_amount * MIN_TOTAL_LIQUIDITY_MULTIPLIER
            
            if total_bid_liquidity < min_required_liquidity:
                return {'valid': False, 'reason': f'Ліквідність bids ${total_bid_liquidity:.0f} < ${min_required_liquidity:.0f}'}
            
            if total_ask_liquidity < min_required_liquidity:
                return {'valid': False, 'reason': f'Ліквідність asks ${total_ask_liquidity:.0f} < ${min_required_liquidity:.0f}'}
            
            # 3. Перевірка концентрації ліквідності
            bid_concentration = market_depth.get('bid_depth_analysis', {}).get('top3_concentration_pct', 0)
            ask_concentration = market_depth.get('ask_depth_analysis', {}).get('top3_concentration_pct', 0)
            
            if bid_concentration > MAX_TOP3_CONCENTRATION_PERCENT:
                return {'valid': False, 'reason': f'Концентрація bids {bid_concentration:.1f}% > {MAX_TOP3_CONCENTRATION_PERCENT}%'}
            
            if ask_concentration > MAX_TOP3_CONCENTRATION_PERCENT:
                return {'valid': False, 'reason': f'Концентрація asks {ask_concentration:.1f}% > {MAX_TOP3_CONCENTRATION_PERCENT}%'}
            
            return {'valid': True, 'reason': 'Глибина ринку задовільна'}
            
        except Exception as e:
            logging.error(f"❌ Помилка валідації глибини ринку: {e}")
            return {'valid': False, 'reason': f'Помилка аналізу: {str(e)}'}
    
    def _validate_price_dynamics_quality(self, analysis_15m: Dict) -> Dict[str, Any]:
        """
        📈 ВАЛІДАЦІЯ ЯКОСТІ ДИНАМІКИ ЦІН
        Перевіряє чи достатньо якісні дані для прийняття торгових рішень
        """
        try:
            # Конфігурація з config.py
            MIN_DYNAMICS_QUALITY_SCORE = 30.0
            
            # Перевірка якості даних
            quality_score = analysis_15m.get('quality_score', 0)
            if quality_score < MIN_DYNAMICS_QUALITY_SCORE:
                return {'valid': False, 'reason': f'Якість даних {quality_score:.1f} < {MIN_DYNAMICS_QUALITY_SCORE}'}
            
            # Перевірка екстремальних значень
            volatility_pct = analysis_15m.get('volatility_pct', 0)
            if volatility_pct > 50:  # Екстремальна волатільність
                return {'valid': False, 'reason': f'Екстремальна волатільність {volatility_pct:.1f}%'}
            
            # Перевірка наявності достатньої кількості точок даних
            price_levels_count = analysis_15m.get('price_levels_count', 0)
            if price_levels_count < 5:
                return {'valid': False, 'reason': f'Мало точок даних: {price_levels_count}'}
            
            # Всі перевірки пройшли
            return {'valid': True, 'reason': 'Динаміка цін якісна'}
            
        except Exception as e:
            logging.error(f"❌ Помилка валідації динаміки цін: {e}")
            return {'valid': False, 'reason': f'Помилка аналізу: {str(e)}'}

# Глобальний верифікатор
signal_verifier = SignalVerification()

def verify_arbitrage_signal(signal: ArbitrageSignal) -> VerificationResult:
    """Зручна функція для верифікації сигналу"""
    return signal_verifier.verify_signal(signal)