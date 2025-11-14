"""
💰 Калькулятор прибутковості для Trinkenbot  
Точний розрахунок P&L з урахуванням комісій, slippage, leverage
Створено Emergent AI Agent - 30 вересня 2025
"""

import logging
from typing import Dict, List, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
import math

logger = logging.getLogger(__name__)

class ProfitCalculator:
    """Клас для точного розрахунку прибутковості арбітражних угод"""
    
    def __init__(self):
        # Комісії біржі XT.com (примірні значення)
        self.xt_maker_fee = Decimal('0.0008')  # 0.08%
        self.xt_taker_fee = Decimal('0.0010')  # 0.10%
        
        # Комісії DEX (примірні значення)
        self.dex_fees = {
            'ethereum': Decimal('0.003'),    # 0.30% Uniswap
            'bsc': Decimal('0.0025'),        # 0.25% PancakeSwap  
            'solana': Decimal('0.0025'),     # 0.25% Raydium/Jupiter
        }
        
        # Slippage коефіцієнти
        self.slippage_rates = {
            'low': Decimal('0.001'),      # 0.1%
            'medium': Decimal('0.003'),   # 0.3%
            'high': Decimal('0.005'),     # 0.5%
        }
        
    def calculate_arbitrage_profit(self, 
                                 xt_price: float,
                                 dex_price: float,
                                 position_size_usdt: float,
                                 leverage: int = 10,
                                 dex_chain: str = 'ethereum',
                                 slippage_level: str = 'medium') -> Dict:
        """
        Розрахунок прибутковості арбітражної угоди
        
        Args:
            xt_price: Ціна на XT.com
            dex_price: Ціна на DEX
            position_size_usdt: Розмір позиції в USDT
            leverage: Плече
            dex_chain: Мережа DEX (ethereum/bsc/solana)
            slippage_level: Рівень slippage (low/medium/high)
        
        Returns:
            Dict з детальним розрахунком прибутку
        """
        try:
            # Конвертація у Decimal для точності
            xt_price_d = Decimal(str(xt_price))
            dex_price_d = Decimal(str(dex_price))
            position_size_d = Decimal(str(position_size_usdt))
            leverage_d = Decimal(str(leverage))
            
            # Визначення напряму арбітражу
            if xt_price_d > dex_price_d:
                # Купити на DEX, продати на XT
                direction = 'dex_to_xt'
                spread_percent = ((xt_price_d - dex_price_d) / dex_price_d) * 100
                buy_price = dex_price_d
                sell_price = xt_price_d
            else:
                # Купити на XT, продати на DEX  
                direction = 'xt_to_dex'
                spread_percent = ((dex_price_d - xt_price_d) / xt_price_d) * 100
                buy_price = xt_price_d
                sell_price = dex_price_d
            
            # Розрахунок кількості токенів
            tokens_to_trade = position_size_d / buy_price
            
            # Комісії
            xt_fee_rate = self.xt_taker_fee  # Використовуємо taker fee
            dex_fee_rate = self.dex_fees.get(dex_chain, self.dex_fees['ethereum'])
            slippage_rate = self.slippage_rates.get(slippage_level, self.slippage_rates['medium'])
            
            # Розрахунок витрат на покупку
            if direction == 'dex_to_xt':
                # Купівля на DEX
                buy_amount = tokens_to_trade * buy_price
                dex_fee = buy_amount * dex_fee_rate
                slippage_cost = buy_amount * slippage_rate
                total_buy_cost = buy_amount + dex_fee + slippage_cost
                
                # Продаж на XT
                sell_revenue_gross = tokens_to_trade * sell_price
                xt_fee = sell_revenue_gross * xt_fee_rate
                sell_revenue_net = sell_revenue_gross - xt_fee
            else:
                # Купівля на XT
                buy_amount = tokens_to_trade * buy_price
                xt_fee_buy = buy_amount * xt_fee_rate
                total_buy_cost = buy_amount + xt_fee_buy
                
                # Продаж на DEX
                sell_revenue_gross = tokens_to_trade * sell_price
                dex_fee = sell_revenue_gross * dex_fee_rate
                slippage_cost = sell_revenue_gross * slippage_rate
                sell_revenue_net = sell_revenue_gross - dex_fee - slippage_cost
            
            # Чистий прибуток
            gross_profit = sell_revenue_net - total_buy_cost
            
            # Урахування плеча
            required_margin = position_size_d / leverage_d
            leveraged_profit = gross_profit * leverage_d
            
            # Розрахунок ROI
            roi_percent = (leveraged_profit / required_margin) * 100 if required_margin > 0 else Decimal('0')
            
            # Мінімальна прибутковість для покриття ризиків
            min_profit_threshold = required_margin * Decimal('0.005')  # 0.5%
            
            result = {
                'is_profitable': leveraged_profit > min_profit_threshold,
                'direction': direction,
                'spread_percent': float(spread_percent),
                'gross_profit': float(gross_profit),
                'leveraged_profit': float(leveraged_profit),
                'required_margin': float(required_margin),
                'roi_percent': float(roi_percent),
                'position_size': float(position_size_d),
                'tokens_to_trade': float(tokens_to_trade),
                'fees': {
                    'xt_fee': float(xt_fee_rate * position_size_d) if direction == 'xt_to_dex' else float(sell_revenue_gross * xt_fee_rate),
                    'dex_fee': float(dex_fee_rate * position_size_d) if direction == 'dex_to_xt' else float(dex_fee),
                    'slippage_cost': float(slippage_cost),
                    'total_fees': float((dex_fee if 'dex_fee' in locals() else Decimal('0')) + 
                                       (xt_fee if 'xt_fee' in locals() else xt_fee_buy if 'xt_fee_buy' in locals() else Decimal('0')) + 
                                       slippage_cost)
                },
                'prices': {
                    'xt_price': float(xt_price_d),
                    'dex_price': float(dex_price_d),
                    'buy_price': float(buy_price),
                    'sell_price': float(sell_price)
                },
                'settings': {
                    'leverage': leverage,
                    'dex_chain': dex_chain,
                    'slippage_level': slippage_level
                },
                'recommendation': self._get_recommendation(leveraged_profit, roi_percent, spread_percent)
            }
            
            logger.debug(f"Розрахунок прибутку: {result['recommendation']}, ROI: {roi_percent:.2f}%")
            return result
            
        except Exception as e:
            logger.error(f"Помилка розрахунку прибутку: {e}")
            return {
                'is_profitable': False,
                'error': str(e),
                'gross_profit': 0.0,
                'leveraged_profit': 0.0,
                'roi_percent': 0.0
            }
    
    def _get_recommendation(self, leveraged_profit: Decimal, roi_percent: Decimal, spread_percent: Decimal) -> str:
        """Генерація рекомендації на основі розрахунків"""
        try:
            if leveraged_profit <= 0:
                return "🔴 НЕ ТОРГУВАТИ - збитки"
            elif roi_percent < Decimal('1'):
                return "🟡 СЛАБКИЙ - низька прибутковість"
            elif roi_percent < Decimal('3'):
                return "🟢 ДОБРИЙ - помірний прибуток"
            elif roi_percent < Decimal('8'):
                return "💚 ВІДМІННИЙ - високий прибуток"
            else:
                return "🚀 ІДЕАЛЬНИЙ - надвисокий прибуток"
        except:
            return "⚪ НЕВИЗНАЧЕНО"
    
    def calculate_stop_loss(self, entry_price: float, position_side: str, stop_loss_percent: float = 25.0) -> float:
        """Розрахунок ціни стоп-лосу"""
        try:
            entry_price_d = Decimal(str(entry_price))
            stop_loss_rate = Decimal(str(stop_loss_percent)) / 100
            
            if position_side.upper() == 'LONG':
                # Для довгих позицій стоп-лос нижче ціни входу
                stop_loss_price = entry_price_d * (Decimal('1') - stop_loss_rate)
            else:  # SHORT
                # Для коротких позицій стоп-лос вище ціни входу  
                stop_loss_price = entry_price_d * (Decimal('1') + stop_loss_rate)
            
            return float(stop_loss_price)
        except Exception as e:
            logger.error(f"Помилка розрахунку стоп-лосу: {e}")
            return entry_price * 0.75 if position_side.upper() == 'LONG' else entry_price * 1.25
    
    def calculate_take_profit(self, entry_price: float, position_side: str, take_profit_percent: float = 2.5) -> float:
        """Розрахунок ціни тейк-профіту"""
        try:
            entry_price_d = Decimal(str(entry_price))
            take_profit_rate = Decimal(str(take_profit_percent)) / 100
            
            if position_side.upper() == 'LONG':
                # Для довгих позицій тейк-профіт вище ціни входу
                take_profit_price = entry_price_d * (Decimal('1') + take_profit_rate)
            else:  # SHORT
                # Для коротких позицій тейк-профіт нижче ціни входу
                take_profit_price = entry_price_d * (Decimal('1') - take_profit_rate)
            
            return float(take_profit_price)
        except Exception as e:
            logger.error(f"Помилка розрахунку тейк-профіту: {e}")
            return entry_price * 1.025 if position_side.upper() == 'LONG' else entry_price * 0.975
    
    def calculate_position_size(self, account_balance: float, risk_percent: float = 2.0, leverage: int = 10) -> float:
        """Розрахунок розміру позиції на основі ризик-менеджменту"""
        try:
            balance_d = Decimal(str(account_balance))
            risk_rate = Decimal(str(risk_percent)) / 100
            leverage_d = Decimal(str(leverage))
            
            # Максимальна сума ризику
            max_risk_amount = balance_d * risk_rate
            
            # Розмір позиції з урахуванням плеча
            position_size = max_risk_amount * leverage_d
            
            # Обмеження максимального розміру позиції (не більше 10% балансу з плечем)
            max_position = balance_d * leverage_d * Decimal('0.10')
            position_size = min(position_size, max_position)
            
            logger.info(f"Розрахований розмір позиції: ${position_size:.2f} (ризик: {risk_percent}%)")
            return float(position_size)
        except Exception as e:
            logger.error(f"Помилка розрахунку розміру позиції: {e}")
            return min(account_balance * 0.02 * leverage, account_balance * leverage * 0.10)
    
    def analyze_spread_profitability(self, spreads: List[Dict]) -> List[Dict]:
        """Аналіз прибутковості списку спредів"""
        try:
            analyzed_spreads = []
            
            for spread in spreads:
                try:
                    profit_analysis = self.calculate_arbitrage_profit(
                        xt_price=spread.get('xt_price', 0),
                        dex_price=spread.get('dex_price', 0),
                        position_size_usdt=spread.get('position_size', 1000),
                        leverage=spread.get('leverage', 10),
                        dex_chain=spread.get('chain', 'ethereum'),
                        slippage_level='medium'
                    )
                    
                    # Додаємо розрахунки до оригінального спреду
                    enhanced_spread = {**spread, **profit_analysis}
                    analyzed_spreads.append(enhanced_spread)
                    
                except Exception as e:
                    logger.warning(f"Не вдалося проаналізувати спред для {spread.get('symbol', 'unknown')}: {e}")
                    continue
            
            # Сортуємо за прибутковістю
            analyzed_spreads.sort(key=lambda x: x.get('roi_percent', 0), reverse=True)
            
            logger.info(f"Проаналізовано {len(analyzed_spreads)} спредів")
            return analyzed_spreads
            
        except Exception as e:
            logger.error(f"Помилка аналізу спредів: {e}")
            return []

# Глобальний екземпляр калькулятора
profit_calculator = ProfitCalculator()

# Функції для експорту
def calculate_profit(xt_price: float, dex_price: float, position_size: float, leverage: int = 10) -> Dict:
    """Швидкий розрахунок прибутку"""
    return profit_calculator.calculate_arbitrage_profit(xt_price, dex_price, position_size, leverage)

def get_stop_loss_price(entry_price: float, side: str, stop_loss_pct: float = 25.0) -> float:
    """Отримати ціну стоп-лосу"""
    return profit_calculator.calculate_stop_loss(entry_price, side, stop_loss_pct)

def get_take_profit_price(entry_price: float, side: str, take_profit_pct: float = 2.5) -> float:
    """Отримати ціну тейк-профіту"""
    return profit_calculator.calculate_take_profit(entry_price, side, take_profit_pct)

def calculate_optimal_position_size(balance: float, risk_pct: float = 2.0, leverage: int = 10) -> float:
    """Розрахувати оптимальний розмір позиції"""
    return profit_calculator.calculate_position_size(balance, risk_pct, leverage)