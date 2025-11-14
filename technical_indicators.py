"""
🔍 Технічні індикатори для Trinkenbot
Інтеграція з TA-Lib для розрахунку RSI, MACD, Bollinger Bands тощо
Створено Emergent AI Agent - 30 вересня 2025
"""

import numpy as np
import pandas as pd
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Спробуємо імпортувати TA-Lib, якщо недоступний - використовуємо власні розрахунки
try:
    import talib
    TALIB_AVAILABLE = True
    logger.info("✅ TA-Lib доступний - використовуємо повний набір індикаторів")
except ImportError:
    TALIB_AVAILABLE = False
    logger.warning("⚠️ TA-Lib недоступний - використовуємо базові індикатори")

class TechnicalIndicators:
    """Клас для розрахунку технічних індикаторів"""
    
    def __init__(self):
        self.cache = {}
        self.cache_ttl = 300  # 5 хвилин
    
    def _get_cached_result(self, cache_key: str) -> Optional[dict]:
        """Отримати закешований результат"""
        if cache_key in self.cache:
            timestamp, result = self.cache[cache_key]
            if datetime.now().timestamp() - timestamp < self.cache_ttl:
                return result
        return None
    
    def _cache_result(self, cache_key: str, result: dict):
        """Закешувати результат"""
        self.cache[cache_key] = (datetime.now().timestamp(), result)
    
    def calculate_rsi(self, prices: List[float], period: int = 14) -> float:
        """Розрахунок RSI (Relative Strength Index)"""
        try:
            if TALIB_AVAILABLE and len(prices) >= period:
                rsi_values = talib.RSI(np.array(prices), timeperiod=period)
                return float(rsi_values[-1]) if not np.isnan(rsi_values[-1]) else 50.0
            else:
                # Власний розрахунок RSI
                return self._calculate_rsi_manual(prices, period)
        except Exception as e:
            logger.error(f"Помилка розрахунку RSI: {e}")
            return 50.0  # Нейтральне значення
    
    def _calculate_rsi_manual(self, prices: List[float], period: int = 14) -> float:
        """Власний розрахунок RSI"""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        avg_gain = np.mean(gains[-period:])
        avg_loss = np.mean(losses[-period:])
        
        if avg_loss == 0:
            return 100.0
        
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)
    
    def calculate_macd(self, prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, float]:
        """Розрахунок MACD"""
        try:
            if TALIB_AVAILABLE and len(prices) >= slow:
                macd_line, signal_line, histogram = talib.MACD(
                    np.array(prices), 
                    fastperiod=fast, 
                    slowperiod=slow, 
                    signalperiod=signal
                )
                
                return {
                    'macd': float(macd_line[-1]) if not np.isnan(macd_line[-1]) else 0.0,
                    'signal': float(signal_line[-1]) if not np.isnan(signal_line[-1]) else 0.0,
                    'histogram': float(histogram[-1]) if not np.isnan(histogram[-1]) else 0.0
                }
            else:
                return self._calculate_macd_manual(prices, fast, slow, signal)
        except Exception as e:
            logger.error(f"Помилка розрахунку MACD: {e}")
            return {'macd': 0.0, 'signal': 0.0, 'histogram': 0.0}
    
    def _calculate_macd_manual(self, prices: List[float], fast: int, slow: int, signal: int) -> Dict[str, float]:
        """Власний розрахунок MACD"""
        if len(prices) < slow:
            return {'macd': 0.0, 'signal': 0.0, 'histogram': 0.0}
        
        prices_array = np.array(prices)
        
        # EMA розрахунок
        def ema(data, period):
            alpha = 2.0 / (period + 1)
            ema_values = np.zeros_like(data)
            ema_values[0] = data[0]
            for i in range(1, len(data)):
                ema_values[i] = alpha * data[i] + (1 - alpha) * ema_values[i-1]
            return ema_values
        
        ema_fast = ema(prices_array, fast)
        ema_slow = ema(prices_array, slow)
        
        macd_line = ema_fast - ema_slow
        signal_line = ema(macd_line, signal)
        histogram = macd_line - signal_line
        
        return {
            'macd': float(macd_line[-1]),
            'signal': float(signal_line[-1]),  
            'histogram': float(histogram[-1])
        }
    
    def calculate_bollinger_bands(self, prices: List[float], period: int = 20, std_dev: float = 2.0) -> Dict[str, float]:
        """Розрахунок Bollinger Bands"""
        try:
            if TALIB_AVAILABLE and len(prices) >= period:
                upper, middle, lower = talib.BBANDS(
                    np.array(prices), 
                    timeperiod=period, 
                    nbdevup=std_dev, 
                    nbdevdn=std_dev
                )
                
                return {
                    'upper': float(upper[-1]) if not np.isnan(upper[-1]) else prices[-1] * 1.02,
                    'middle': float(middle[-1]) if not np.isnan(middle[-1]) else prices[-1],
                    'lower': float(lower[-1]) if not np.isnan(lower[-1]) else prices[-1] * 0.98
                }
            else:
                return self._calculate_bollinger_manual(prices, period, std_dev)
        except Exception as e:
            logger.error(f"Помилка розрахунку Bollinger Bands: {e}")
            current_price = prices[-1] if prices else 100.0
            return {
                'upper': current_price * 1.02,
                'middle': current_price,
                'lower': current_price * 0.98
            }
    
    def _calculate_bollinger_manual(self, prices: List[float], period: int, std_dev: float) -> Dict[str, float]:
        """Власний розрахунок Bollinger Bands"""
        if len(prices) < period:
            current_price = prices[-1] if prices else 100.0
            return {
                'upper': current_price * 1.02,
                'middle': current_price,
                'lower': current_price * 0.98
            }
        
        recent_prices = prices[-period:]
        middle = np.mean(recent_prices)
        std = np.std(recent_prices)
        
        upper = middle + (std_dev * std)
        lower = middle - (std_dev * std)
        
        return {
            'upper': float(upper),
            'middle': float(middle),
            'lower': float(lower)
        }
    
    def calculate_moving_averages(self, prices: List[float], periods: List[int] = [20, 50, 200]) -> Dict[str, float]:
        """Розрахунок ковзних середніх"""
        try:
            ma_results = {}
            
            for period in periods:
                if len(prices) >= period:
                    if TALIB_AVAILABLE:
                        ma = talib.SMA(np.array(prices), timeperiod=period)
                        ma_results[f'sma_{period}'] = float(ma[-1]) if not np.isnan(ma[-1]) else prices[-1]
                    else:
                        ma = np.mean(prices[-period:])
                        ma_results[f'sma_{period}'] = float(ma)
                else:
                    ma_results[f'sma_{period}'] = prices[-1] if prices else 100.0
            
            return ma_results
        except Exception as e:
            logger.error(f"Помилка розрахунку MA: {e}")
            return {f'sma_{p}': prices[-1] if prices else 100.0 for p in periods}
    
    def calculate_vwap(self, prices: List[float], volumes: List[float]) -> float:
        """Розрахунок VWAP (Volume Weighted Average Price)"""
        try:
            if len(prices) != len(volumes) or len(prices) == 0:
                return prices[-1] if prices else 100.0
            
            prices_array = np.array(prices)
            volumes_array = np.array(volumes)
            
            vwap = np.sum(prices_array * volumes_array) / np.sum(volumes_array)
            return float(vwap)
        except Exception as e:
            logger.error(f"Помилка розрахунку VWAP: {e}")
            return prices[-1] if prices else 100.0
    
    def calculate_atr(self, highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
        """Розрахунок ATR (Average True Range)"""
        try:
            if TALIB_AVAILABLE and len(highs) >= period:
                atr = talib.ATR(
                    np.array(highs), 
                    np.array(lows), 
                    np.array(closes), 
                    timeperiod=period
                )
                return float(atr[-1]) if not np.isnan(atr[-1]) else closes[-1] * 0.02
            else:
                return self._calculate_atr_manual(highs, lows, closes, period)
        except Exception as e:
            logger.error(f"Помилка розрахунку ATR: {e}")
            return closes[-1] * 0.02 if closes else 2.0
    
    def _calculate_atr_manual(self, highs: List[float], lows: List[float], closes: List[float], period: int) -> float:
        """Власний розрахунок ATR"""
        if len(highs) < 2 or len(lows) < 2 or len(closes) < 2:
            return closes[-1] * 0.02 if closes else 2.0
        
        true_ranges = []
        for i in range(1, len(closes)):
            tr1 = highs[i] - lows[i]
            tr2 = abs(highs[i] - closes[i-1])  
            tr3 = abs(lows[i] - closes[i-1])
            true_ranges.append(max(tr1, tr2, tr3))
        
        if len(true_ranges) >= period:
            atr = np.mean(true_ranges[-period:])
        else:
            atr = np.mean(true_ranges)
        
        return float(atr)
    
    def analyze_symbol_full(self, symbol: str, price_data: Dict) -> Dict:
        """Повний технічний аналіз символу"""
        cache_key = f"full_analysis_{symbol}_{hash(str(price_data))}"
        cached = self._get_cached_result(cache_key)
        if cached:
            return cached
        
        try:
            # Отримання даних
            prices = price_data.get('prices', [])
            volumes = price_data.get('volumes', [])
            highs = price_data.get('highs', prices)
            lows = price_data.get('lows', prices)
            
            if not prices:
                # Мок дані для тестування
                current_price = price_data.get('current_price', 100.0)
                prices = [current_price * (1 + (i-25)*0.001) for i in range(50)]
                volumes = [1000000 + (i * 10000) for i in range(50)]
            
            # Розрахунок всіх індикаторів
            analysis = {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'current_price': prices[-1],
                
                # Основні індикатори
                'rsi': self.calculate_rsi(prices),
                'macd': self.calculate_macd(prices),
                'bollinger': self.calculate_bollinger_bands(prices),
                'ma': self.calculate_moving_averages(prices),
                'vwap': self.calculate_vwap(prices, volumes),
                'atr': self.calculate_atr(highs, lows, prices),
                
                # Сигнали
                'signals': self._generate_signals(prices, volumes)
            }
            
            self._cache_result(cache_key, analysis)
            return analysis
            
        except Exception as e:
            logger.error(f"Помилка повного аналізу {symbol}: {e}")
            # Повертаємо базовий аналіз
            current_price = price_data.get('current_price', 100.0)
            return {
                'symbol': symbol,
                'timestamp': datetime.now().isoformat(),
                'current_price': current_price,
                'rsi': 50.0,
                'macd': {'macd': 0.0, 'signal': 0.0, 'histogram': 0.0},
                'bollinger': {
                    'upper': current_price * 1.02,
                    'middle': current_price,
                    'lower': current_price * 0.98
                },
                'ma': {'sma_20': current_price, 'sma_50': current_price},
                'vwap': current_price,
                'atr': current_price * 0.02,
                'signals': {'trend': 'neutral', 'strength': 'weak'}
            }
    
    def _generate_signals(self, prices: List[float], volumes: List[float]) -> Dict:
        """Генерація торгових сигналів"""
        try:
            if len(prices) < 20:
                return {'trend': 'neutral', 'strength': 'weak'}
            
            # RSI сигнали
            rsi = self.calculate_rsi(prices)
            rsi_signal = 'overbought' if rsi > 70 else 'oversold' if rsi < 30 else 'neutral'
            
            # MA тренд
            ma_short = np.mean(prices[-10:])
            ma_long = np.mean(prices[-20:])
            trend = 'bullish' if ma_short > ma_long else 'bearish' if ma_short < ma_long else 'neutral'
            
            # Волатильність
            volatility = np.std(prices[-20:]) / np.mean(prices[-20:])
            strength = 'strong' if volatility > 0.03 else 'medium' if volatility > 0.015 else 'weak'
            
            return {
                'trend': trend,
                'rsi_signal': rsi_signal,
                'strength': strength,
                'volatility': float(volatility)
            }
        except Exception as e:
            logger.error(f"Помилка генерації сигналів: {e}")
            return {'trend': 'neutral', 'strength': 'weak'}

# Глобальний екземпляр
technical_indicators = TechnicalIndicators()

# Функції для експорту
def get_rsi(prices: List[float], period: int = 14) -> float:
    """Отримати RSI"""
    return technical_indicators.calculate_rsi(prices, period)

def get_macd(prices: List[float]) -> Dict[str, float]:
    """Отримати MACD"""
    return technical_indicators.calculate_macd(prices)

def get_bollinger_bands(prices: List[float]) -> Dict[str, float]:
    """Отримати Bollinger Bands"""
    return technical_indicators.calculate_bollinger_bands(prices)

def analyze_symbol(symbol: str, price_data: Dict) -> Dict:
    """Повний аналіз символу"""
    return technical_indicators.analyze_symbol_full(symbol, price_data)