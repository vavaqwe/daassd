import re
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass

@dataclass
class ArbitrageSignal:
    """Структура арбітражного сигналу"""
    asset: str = ""
    action: str = ""  # LONG/SHORT
    xt_price: float = 0.0
    dex_price: float = 0.0
    spread_percent: float = 0.0
    size_usd: float = 0.0
    tp: float = 0.0  # Take Profit
    sl: float = 0.0  # Stop Loss
    leverage: int = 1
    liquidity_usd: float = 0.0
    volume_24h_usd: float = 0.0
    
    @property
    def is_valid(self) -> bool:
        """Перевіряє чи сигнал має всі обов'язкові поля"""
        required_fields = [
            self.asset, self.action, self.xt_price, self.dex_price, 
            self.spread_percent, self.size_usd, self.tp, self.sl
        ]
        return all(field for field in required_fields)

class SignalParser:
    """
    Парсер сигналів для арбітражного бота
    
    Очікуваний формат:
    🚨 ARBITRAGE SIGNAL 🚨
    ASSET: PEOPLE
    ACTION: LONG
    XT_PRICE: $0.020940
    DEX_PRICE: $0.021319
    SPREAD: +1.72%
    SIZE_USD: $5.0
    TP: $0.021191
    SL: $0.018846
    LEVERAGE: 5x
    LIQUIDITY: $391,982
    VOLUME_24H: $497,000
    """
    
    def __init__(self):
        # Регулярні вирази для витягання даних
        self.patterns = {
            'asset': r'ASSET:\s*([A-Z0-9]+)',
            'action': r'ACTION:\s*(LONG|SHORT)',
            'xt_price': r'XT_PRICE:\s*\$?([0-9]+\.?[0-9]*)',
            'dex_price': r'DEX_PRICE:\s*\$?([0-9]+\.?[0-9]*)',
            'spread': r'SPREAD:\s*([+-]?[0-9]+\.?[0-9]*)%?',
            'size_usd': r'SIZE_USD:\s*\$?([0-9]+\.?[0-9]*)',
            'tp': r'TP:\s*\$?([0-9]+\.?[0-9]*)',
            'sl': r'SL:\s*\$?([0-9]+\.?[0-9]*)',
            'leverage': r'LEVERAGE:\s*([0-9]+)x?',
            'liquidity': r'LIQUIDITY:\s*\$?([0-9,]+(?:\.[0-9]*)?)',
            'volume_24h': r'VOLUME_24H:\s*\$?([0-9,]+(?:\.[0-9]*)?)'
        }
    
    def parse_signal(self, text: str) -> Optional[ArbitrageSignal]:
        """
        Парсить текст сигналу та повертає структуру ArbitrageSignal
        
        Args:
            text: Текст повідомлення з сигналом
            
        Returns:
            ArbitrageSignal або None якщо парсинг невдалий
        """
        try:
            signal = ArbitrageSignal()
            
            # Видаляємо зайві символи та переводимо в верхній регістр для пошуку
            text_upper = text.upper().replace(',', '')
            
            # Витягуємо дані за патернами
            for field, pattern in self.patterns.items():
                match = re.search(pattern, text_upper, re.IGNORECASE)
                if match:
                    value = match.group(1)
                    
                    # Обробляємо різні типи даних
                    if field == 'asset':
                        signal.asset = value.upper()
                    elif field == 'action':
                        signal.action = value.upper()
                    elif field in ['xt_price', 'dex_price', 'spread', 'tp', 'sl']:
                        signal.__setattr__(field.replace('spread', 'spread_percent'), float(value))
                    elif field == 'size_usd':
                        signal.size_usd = float(value)
                    elif field == 'leverage':
                        signal.leverage = int(value)
                    elif field in ['liquidity', 'volume_24h']:
                        # Обробляємо числа з комами (наприклад 391,982)
                        clean_value = value.replace(',', '')
                        signal.__setattr__(field.replace('volume_24h', 'volume_24h_usd').replace('liquidity', 'liquidity_usd'), float(clean_value))
            
            # Перевіряємо чи сигнал має мінімальні обов'язкові поля
            if signal.asset and signal.action and signal.xt_price > 0 and signal.dex_price > 0:
                logging.info(f"✅ Успішно парсований сигнал: {signal.asset} {signal.action} ${signal.xt_price:.6f}")
                return signal
            else:
                logging.warning(f"❌ Неповний сигнал: {signal.asset} | XT:{signal.xt_price} | DEX:{signal.dex_price}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Помилка парсингу сигналу: {e}")
            return None
    
    def validate_signal_thresholds(self, signal: ArbitrageSignal) -> Dict[str, Any]:
        """
        Перевіряє сигнал згідно з пороговими значеннями
        
        Returns:
            dict з результатами перевірки
        """
        from config import MIN_SPREAD, MAX_SPREAD
        
        # Пороги згідно з вашими вимогами
        from config import MIN_24H_VOLUME_USD, MIN_POOLED_LIQUIDITY_USD
        
        validation_result = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        # Перевірка спреду
        spread = abs(signal.spread_percent)
        if spread < MIN_SPREAD:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Спред {spread:.2f}% < мінімум {MIN_SPREAD}%")
        
        if spread > MAX_SPREAD:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Спред {spread:.2f}% > максимум {MAX_SPREAD}%")
        
        # Перевірка об'єму за 24 години
        if signal.volume_24h_usd > 0 and signal.volume_24h_usd < MIN_24H_VOLUME_USD:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Об'єм ${signal.volume_24h_usd:,.0f} < мінімум ${MIN_24H_VOLUME_USD:,.0f}")
        
        # Перевірка ліквідності
        if signal.liquidity_usd > 0 and signal.liquidity_usd < MIN_POOLED_LIQUIDITY_USD:
            validation_result['valid'] = False
            validation_result['errors'].append(f"Ліквідність ${signal.liquidity_usd:,.0f} < мінімум ${MIN_POOLED_LIQUIDITY_USD:,.0f}")
        
        # Перевірка розумності цін (чи не занадто великий спред = підозріло)
        price_ratio = max(signal.xt_price, signal.dex_price) / min(signal.xt_price, signal.dex_price)
        if price_ratio > 1.5:  # >50% різниця цін підозріло
            validation_result['warnings'].append(f"Підозріла різниця цін: {price_ratio:.2f}x")
        
        return validation_result

# Глобальний парсер для використання в інших модулях
signal_parser = SignalParser()

def parse_arbitrage_signal(text: str) -> Optional[ArbitrageSignal]:
    """Зручна функція для парсингу сигналу"""
    return signal_parser.parse_signal(text)

def validate_signal(signal: ArbitrageSignal) -> Dict[str, Any]:
    """Зручна функція для валідації сигналу"""
    return signal_parser.validate_signal_thresholds(signal)