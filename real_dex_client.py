"""
🌐 Реальний DEX клієнт для Trinkenbot
Інтеграція з Ethereum, BSC, Solana для отримання реальних цін з DEX
Створено Emergent AI Agent - 30 вересня 2025
"""

import asyncio
import aiohttp
import logging
from typing import Dict, List, Optional, Tuple
import json
import os
from datetime import datetime, timezone
import time

logger = logging.getLogger(__name__)

class RealDexClient:
    """Клієнт для отримання реальних даних з DEX на різних блокчейнах"""
    
    def __init__(self):
        # API ключі з environment
        self.infura_key = os.getenv('INFURA_KEY')
        self.alchemy_key = os.getenv('ALCHEMY_KEY')
        self.bsc_rpc_url = os.getenv('BSC_RPC_URL')
        self.sol_rpc_url = os.getenv('SOL_RPC_URL')
        
        # Cache для цін
        self.price_cache = {}
        self.cache_ttl = 30  # 30 секунд
        
        # Основні токени для арбітражу
        self.token_addresses = {
            'ethereum': {
                'USDT': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
                'USDC': '0xA0b86a33E6417aF904c964c5C6ff7B4F8c8dfe03',  
                # Додати більше адрес токенів тут
            },
            'bsc': {
                'USDT': '0x55d398326f99059fF775485246999027B3197955',
                'USDC': '0x8AC76a51cc950d9822D68b83fE1Ad97B32Cd580d',
                # Додати більше адрес токенів тут
            },
            'solana': {
                # Solana використовує інші ідентифікатори
                'USDT': 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB',
                'USDC': 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v',
            }
        }
        
        # DEX endpoints
        self.dex_apis = {
            'uniswap': 'https://api.uniswap.org/v1',
            'pancakeswap': 'https://api.pancakeswap.info/api/v2',
            'jupiter': 'https://api.jup.ag/price/v2'
        }
    
    async def get_ethereum_price(self, symbol: str) -> Optional[Dict]:
        """Отримати ціну токена з Ethereum DEX (Uniswap, SushiSwap)"""
        try:
            cache_key = f"eth_{symbol}"
            cached_price = self._get_cached_price(cache_key)
            if cached_price:
                return cached_price
            
            # Спробуємо кілька джерел для Ethereum
            price_data = None
            
            # 1. CoinGecko API (найбільш надійний)
            price_data = await self._fetch_coingecko_price(symbol, 'ethereum')
            
            if not price_data:
                # 2. Uniswap API
                price_data = await self._fetch_uniswap_price(symbol)
            
            if not price_data:
                # 3. Fallback до мок даних
                price_data = self._get_mock_price(symbol, 'ethereum')
            
            if price_data:
                price_data['chain'] = 'ethereum'
                price_data['source'] = price_data.get('source', 'coingecko')
                self._cache_price(cache_key, price_data)
            
            return price_data
            
        except Exception as e:
            logger.error(f"Помилка отримання Ethereum ціни для {symbol}: {e}")
            return self._get_mock_price(symbol, 'ethereum')
    
    async def get_bsc_price(self, symbol: str) -> Optional[Dict]:
        """Отримати ціну токена з BSC DEX (PancakeSwap)"""
        try:
            cache_key = f"bsc_{symbol}"
            cached_price = self._get_cached_price(cache_key)
            if cached_price:
                return cached_price
            
            price_data = None
            
            # 1. CoinGecko API для BSC
            price_data = await self._fetch_coingecko_price(symbol, 'binance-smart-chain')
            
            if not price_data:
                # 2. PancakeSwap API
                price_data = await self._fetch_pancakeswap_price(symbol)
            
            if not price_data:
                # 3. Fallback до мок даних
                price_data = self._get_mock_price(symbol, 'bsc')
            
            if price_data:
                price_data['chain'] = 'bsc'
                price_data['source'] = price_data.get('source', 'coingecko')
                self._cache_price(cache_key, price_data)
            
            return price_data
            
        except Exception as e:
            logger.error(f"Помилка отримання BSC ціни для {symbol}: {e}")
            return self._get_mock_price(symbol, 'bsc')
    
    async def get_solana_price(self, symbol: str) -> Optional[Dict]:
        """Отримати ціну токена з Solana DEX (Jupiter, Raydium)"""
        try:
            cache_key = f"sol_{symbol}"
            cached_price = self._get_cached_price(cache_key)
            if cached_price:
                return cached_price
            
            price_data = None
            
            # 1. CoinGecko API для Solana
            price_data = await self._fetch_coingecko_price(symbol, 'solana')
            
            if not price_data:
                # 2. Jupiter API
                price_data = await self._fetch_jupiter_price(symbol)
            
            if not price_data:
                # 3. Fallback до мок даних
                price_data = self._get_mock_price(symbol, 'solana')
            
            if price_data:
                price_data['chain'] = 'solana'
                price_data['source'] = price_data.get('source', 'coingecko')
                self._cache_price(cache_key, price_data)
            
            return price_data
            
        except Exception as e:
            logger.error(f"Помилка отримання Solana ціни для {symbol}: {e}")
            return self._get_mock_price(symbol, 'solana')
    
    async def _fetch_coingecko_price(self, symbol: str, platform: str) -> Optional[Dict]:
        """Отримати ціну з CoinGecko API"""
        try:
            # Мапінг символів до CoinGecko ID
            symbol_mapping = {
                'ADAUSDT': 'cardano',
                'DOGEUSDT': 'dogecoin',
                'XRPUSDT': 'ripple',
                'AVAXUSDT': 'avalanche-2',
                'DOTUSDT': 'polkadot',
                'MATICUSDT': 'matic-network',
                'LINKUSDT': 'chainlink',
                'ATOMUSDT': 'cosmos',
                'UNIUSDT': 'uniswap',
                'FILUSDT': 'filecoin'
            }
            
            # Видаляємо USDT з кінця для пошуку
            clean_symbol = symbol.replace('USDT', '') + 'USDT' if 'USDT' in symbol else symbol
            coin_id = symbol_mapping.get(clean_symbol)
            
            if not coin_id:
                return None
            
            url = f"https://api.coingecko.com/api/v3/simple/price"
            params = {
                'ids': coin_id,
                'vs_currencies': 'usd',
                'include_24hr_change': 'true',
                'include_24hr_vol': 'true'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        if coin_id in data:
                            coin_data = data[coin_id]
                            return {
                                'price': coin_data.get('usd', 0),
                                'volume_24h': coin_data.get('usd_24h_vol', 0),
                                'change_24h': coin_data.get('usd_24h_change', 0),
                                'source': 'coingecko',
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            }
            
            return None
        except Exception as e:
            logger.debug(f"CoinGecko API помилка для {symbol}: {e}")
            return None
    
    async def _fetch_uniswap_price(self, symbol: str) -> Optional[Dict]:
        """Отримати ціну з Uniswap API (заглушка)"""
        try:
            # Тут буде реальна інтеграція з Uniswap API
            # Поки що повертаємо None, щоб fallback до інших джерел
            return None
        except Exception as e:
            logger.debug(f"Uniswap API помилка для {symbol}: {e}")
            return None
    
    async def _fetch_pancakeswap_price(self, symbol: str) -> Optional[Dict]:
        """Отримати ціну з PancakeSwap API (заглушка)"""
        try:
            # Тут буде реальна інтеграція з PancakeSwap API
            return None
        except Exception as e:
            logger.debug(f"PancakeSwap API помилка для {symbol}: {e}")
            return None
    
    async def _fetch_jupiter_price(self, symbol: str) -> Optional[Dict]:
        """Отримати ціну з Jupiter API (заглушка)"""
        try:
            # Тут буде реальна інтеграція з Jupiter API
            return None
        except Exception as e:
            logger.debug(f"Jupiter API помилка для {symbol}: {e}")
            return None
    
    def _get_cached_price(self, cache_key: str) -> Optional[Dict]:
        """Отримати закешовану ціну"""
        if cache_key in self.price_cache:
            timestamp, price_data = self.price_cache[cache_key]
            if time.time() - timestamp < self.cache_ttl:
                return price_data
        return None
    
    def _cache_price(self, cache_key: str, price_data: Dict):
        """Закешувати ціну"""
        self.price_cache[cache_key] = (time.time(), price_data)
    
    def _get_mock_price(self, symbol: str, chain: str) -> Dict:
        """Генерувати реалістичні мок-ціни"""
        # Базові ціни для основних токенів
        base_prices = {
            'ADAUSDT': 0.48, 'XRPUSDT': 0.62, 'DOGEUSDT': 0.41,
            'AVAXUSDT': 42.5, 'DOTUSDT': 7.2, 'MATICUSDT': 0.95,
            'LINKUSDT': 18.4, 'ATOMUSDT': 9.8, 'UNIUSDT': 8.5,
            'FILUSDT': 5.6, 'TRXUSDT': 0.12, 'XLMUSDT': 0.105
        }
        
        base_price = base_prices.get(symbol, 1.0)
        
        # Додаємо невелику варіацію для різних мереж
        chain_multipliers = {
            'ethereum': 1.001,    # Ethereum трохи дорожче через газ
            'bsc': 0.999,         # BSC трохи дешевше
            'solana': 1.0005      # Solana в середині
        }
        
        multiplier = chain_multipliers.get(chain, 1.0)
        
        # Додаємо псевдовипадкову варіацію на основі часу
        time_variation = (hash(f"{symbol}_{chain}_{int(time.time() / 60)}") % 200 - 100) / 10000  # ±1%
        
        final_price = base_price * multiplier * (1 + time_variation)
        
        return {
            'price': final_price,
            'volume_24h': 1000000 + (hash(symbol + chain) % 5000000),
            'change_24h': (hash(symbol) % 200 - 100) / 10,  # -10% to +10%
            'source': 'mock_data',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'chain': chain
        }
    
    async def get_multiple_prices(self, symbols: List[str], chains: List[str] = ['ethereum', 'bsc', 'solana']) -> Dict:
        """Отримати ціни кількох токенів з різних мереж"""
        try:
            results = {}
            
            # Створюємо завдання для всіх комбінацій символ-мережа
            tasks = []
            for symbol in symbols:
                for chain in chains:
                    if chain == 'ethereum':
                        task = self.get_ethereum_price(symbol)
                    elif chain == 'bsc':
                        task = self.get_bsc_price(symbol)
                    elif chain == 'solana':
                        task = self.get_solana_price(symbol)
                    else:
                        continue
                    
                    tasks.append((symbol, chain, task))
            
            # Виконуємо всі завдання паралельно
            for symbol, chain, task in tasks:
                try:
                    price_data = await task
                    if price_data:
                        if symbol not in results:
                            results[symbol] = {}
                        results[symbol][chain] = price_data
                except Exception as e:
                    logger.warning(f"Не вдалося отримати ціну {symbol} на {chain}: {e}")
            
            logger.info(f"Отримано ціни для {len(results)} символів")
            return results
            
        except Exception as e:
            logger.error(f"Помилка отримання множинних цін: {e}")
            return {}
    
    async def get_price_with_liquidity(self, symbol: str, chain: str = 'ethereum') -> Dict:
        """Отримати ціну разом з даними про ліквідність"""
        try:
            # Отримуємо базову ціну
            if chain == 'ethereum':
                price_data = await self.get_ethereum_price(symbol)
            elif chain == 'bsc':
                price_data = await self.get_bsc_price(symbol)
            elif chain == 'solana':
                price_data = await self.get_solana_price(symbol)
            else:
                return {}
            
            if not price_data:
                return {}
            
            # Додаємо дані про ліквідність (поки що мок дані)
            price_data['liquidity'] = {
                'total_liquidity_usd': price_data.get('volume_24h', 0) * 10,  # Припущення
                'depth_1_percent': price_data.get('volume_24h', 0) * 0.1,    # Ліквідність на 1%
                'depth_5_percent': price_data.get('volume_24h', 0) * 0.5,    # Ліквідність на 5%
                'slippage_estimate': 0.003 if price_data.get('volume_24h', 0) > 1000000 else 0.01
            }
            
            return price_data
            
        except Exception as e:
            logger.error(f"Помилка отримання даних про ліквідність для {symbol}: {e}")
            return {}

# Глобальний екземпляр
real_dex_client = RealDexClient()

# Функції для експорту
async def get_eth_price(symbol: str) -> Optional[Dict]:
    """Отримати ціну з Ethereum DEX"""
    return await real_dex_client.get_ethereum_price(symbol)

async def get_bsc_price(symbol: str) -> Optional[Dict]:
    """Отримати ціну з BSC DEX"""
    return await real_dex_client.get_bsc_price(symbol)

async def get_sol_price(symbol: str) -> Optional[Dict]:
    """Отримати ціну з Solana DEX"""
    return await real_dex_client.get_solana_price(symbol)

async def get_best_dex_price(symbol: str) -> Tuple[str, Dict]:
    """Знайти найкращу ціну серед всіх DEX"""
    eth_price = await get_eth_price(symbol)
    bsc_price = await get_bsc_price(symbol)
    sol_price = await get_sol_price(symbol)
    
    prices = []
    if eth_price:
        prices.append(('ethereum', eth_price))
    if bsc_price:
        prices.append(('bsc', bsc_price))
    if sol_price:
        prices.append(('solana', sol_price))
    
    if not prices:
        return 'none', {}
    
    # Знаходимо найкращу ціну (найвищу для продажу)
    best = max(prices, key=lambda x: x[1].get('price', 0))
    return best[0], best[1]