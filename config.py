from dotenv import load_dotenv
import os

load_dotenv()
# ПЕРЕД ЗАПУСКОМ: вставте свої ключі через Environment Variables на Replit
# ВИДАЛЕНО Gate.io - тепер тільки XT.com + DexCheck API
# GATE_API_KEY = os.getenv("GATE_API_KEY", "")   
# GATE_API_SECRET = os.getenv("GATE_API_SECRET", "")

# XT Біржа - ПЕРШИЙ АКАУНТ
XT_API_KEY = os.getenv("XT_API_KEY", "")
XT_API_SECRET = os.getenv("XT_API_SECRET", "")

# XT Біржа - ДРУГИЙ АКАУНТ (паралельна торгівля)
XT_ACCOUNT_2_API_KEY = os.getenv("XT_ACCOUNT_2_API_KEY", "")
XT_ACCOUNT_2_API_SECRET = os.getenv("XT_ACCOUNT_2_API_SECRET", "")

DEXCHECK_API_KEY = os.getenv("DEXCHECK_API_KEY", "")  # DexCheck API для потужної аналітики
# ВИДАЛЕНО APIFY_API_KEY - замінено на прямі блокчейн RPC запити (економія $39/місяць)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")  # Перший адмін
TELEGRAM_ADMIN_2_ID = os.getenv("TELEGRAM_ADMIN_2_ID", "")  # Другий адмін
TELEGRAM_ADMIN_3_ID = os.getenv("TELEGRAM_ADMIN_3_ID", "") # 3 адмін
TELEGRAM_GROUP_CHAT_ID = os.getenv("TELEGRAM_GROUP_CHAT_ID", "")  # Група для сигналів

# Безпека адмін панелі
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")  # ОБОВ'ЯЗКОВИЙ! БЕЗ ДЕФОЛТУ ДЛЯ БЕЗПЕКИ
if not ADMIN_PASSWORD:
    raise ValueError("❌ ADMIN_PASSWORD обов'язковий! Встановіть через Environment Variables")
ADMIN_2_PASSWORD = os.getenv("ADMIN_2_PASSWORD")  # Пароль другого адміна
ALLOW_LIVE_TRADING = True  # 🚀 ВІДНОВЛЕНО: Дозволяю системі моніторингу закрити позиції!

# Базові налаштування
BOT_NAME = "GateArbBot"
DRY_RUN = False  # 🚀 LIVE ТОРГІВЛЯ: Повна система увімкнена для деплоя!
SCAN_INTERVAL = 15  # ⚡ АКТИВНИЙ РЕЖИМ: швидке сканування для постійної активності  
ORDER_AMOUNT = 5.0  # 🔧 ПОВЕРНУТО: $5.0 маржа, з 7x левериджем = $35.0 позиція  
LEVERAGE = 7  # 7x плече як просить користувач (маржа $5.0)
MIN_SPREAD = 2  # 🎯 МІНІМАЛЬНИЙ СПРЕД: 1.5% як просить користувач
MAX_SPREAD = 3  # % МАКСИМАЛЬНИЙ СПРЕД 50% (як просить користувач)
MIN_NET_PROFIT_PERCENT = 0.1  # 🔧 ТЕСТ: ще більше зменшено для сигналів
ESTIMATED_TRADING_COSTS_PERCENT = 0.6  # Очікувані витрати (комісії + slippage)
MAX_OPEN_POSITIONS = 100  # Максимум 10 позицій для економії маржі
MAX_PYRAMID = 2  # 🎯 ЗБІЛЬШЕНО: 1 початкова позиція + 1 усереднення = максимум 2 входи
ORDER_BOOK_DEPTH = 20  # 🚀 ВИПРАВЛЕНО: збільшено до 20 рівнів для кращої аналітики ліквідності
PNL_LEVELS = [25.0, 30.0]  # внутрішні PNL рівні (проценти)
MAX_CONCURRENT_SYMBOLS = 50  # ⚡ ОПТИМІЗОВАНО: 50 паралельних threads для стабільності
LOG_TO_TELEGRAM = True  # 🚀 УВІМКНЕНО: Telegram сигнали активні!

# ❌ ДОКУПІВЛІ ВІДКЛЮЧЕНО ПОВНІСТЮ (як просив користувач)  
AVERAGING_ENABLED = False  # 🚫 ВИМКНЕНО повністю - НІ ДОКУПІВЕЛЬ!
AVERAGING_THRESHOLD_PCT = 2.0  # % руху проти позиції для усереднення (неактивно)
AVERAGING_MAX_ADDS = 0  # 🚫 НУЛЬ докупівель 
AVERAGING_SIZING = "fixed"  # "fixed" або "multiplier" для розміру додаткових входів (неактивно)
AVERAGING_MULTIPLIER = 1.0  # множник для "multiplier" режиму (неактивно)
AVERAGING_COOLDOWN_SEC = 300  # 🛡️ 5 хвилин cooldown між докупками для безпеки (неактивно)
MAX_POSITION_USDT_PER_SYMBOL = 4.5  # 🔧 ЗМЕНШЕНО до $4.5 для врахування комісій і буфера

# 🎯 НАЛАШТУВАННЯ АВТОМАТИЧНОГО ЗАКРИТТЯ ПОЗИЦІЙ
CLOSE_ON_CONVERGENCE = True  # Автоматично закривати коли ціни сходяться
CONVERGENCE_SPREAD_PCT = 0.5  # Поріг сходження (закривати якщо спред <= 0.5%)
HALF_MOVE_PCT = 0.5  # 50% руху від початкового спреду для закриття (Nazir)
TAKE_PROFIT_PCT = 10.0  # 🎯 ВИПРАВЛЕНО: Закривати позицію при +10% прибутку
STOP_LOSS_PCT = 10.0  # 🛡️ ВИПРАВЛЕНО: Стоп-лосс при -10% збитку
HALF_MOVE_CLOSE = True  # Закривати при 50% руху від початкового спреду (Nazir: додано)

# ⏰ НОВИЙ ФІЛЬТР: 1-годинний таймер позицій
ENABLE_TIME_STOP = True  # Автозакриття позицій через 1 годину
POSITION_MAX_AGE_SEC = 3600  # ⏰ ВІДНОВЛЕНО: 1 година для автозакриття позицій  
MONITOR_INTERVAL_SEC = 20  # ⚡ ШВИДКИЙ МОНІТОРИНГ: перевірка позицій кожні 20 сек
MIN_HOLD_SEC = 10  # Мінімальний час утримання позиції (уникнення миттєвого закриття)
USE_DEX_FOR_SPREAD = True  # Використовувати DEX ціни для розрахунку конвергенції
TELEGRAM_COOLDOWN_SEC = 60  # 🎯 КУЛДАУН: 1 хвилина між Telegram повідомленнями як просить користувач

# 🎯 ПОРОГИ ЗГІДНО З ВАШИМИ ВИМОГАМИ
MIN_24H_VOLUME_USD = 100  # 🚀 ПОВЕРНУТО: $1,000 для якісних монет
MIN_POOLED_LIQUIDITY_USD = 100  # 🔧 ТЕСТ: зменшив для сигналів
MAX_SLIPPAGE_PERCENT = 12.0  # Максимальний slippage
SLIPPAGE_PADDING = 0.5  # Додаткова маржа безпеки для slippage
COOLDOWN_SEC = 120  # 💰 ЕКОНОМІЯ API: 2 хвилини між сигналами (economy mode)

# 🎯 ДОДАТКОВІ ФІЛЬТРИ ДЛЯ СИГНАЛІВ
MIN_VOLATILITY_15MIN = 0.0  # Мінімальна волатильність за 15 хв (%)
MAX_VOLATILITY_15MIN = 20.0  # Максимальна волатильність за 15 хв (%)
MIN_ORDERBOOK_DEPTH_MULTIPLIER = 3.0  # Глибина ордербуку ≥ 3× від суми угоди
MIN_BUY_RATIO_PERCENT = 40.0  # Мінімум 40% покупок з останніх 100 угод

# 📊 НОВІ КРИТЕРІЇ: Глибина ринку та динаміка цін
MAX_BID_ASK_SPREAD_PERCENT = 1.0  # Максимальний спред між bid/ask на XT ≤ 1.0%
MIN_TOTAL_LIQUIDITY_MULTIPLIER = 5.0  # Загальна ліквідність ≥ 5× розміру ордеру
MAX_TOP3_CONCENTRATION_PERCENT = 90.0  # Максимальна концентрація ліквідності в топ-3 рівнях
MIN_DYNAMICS_QUALITY_SCORE = 30.0  # Мінімальна якість даних для аналізу динаміки
PRICE_DYNAMICS_PERIOD_MIN = 15  # Відстежування динаміки цін (хвилини)
PRICE_DYNAMICS_PERIOD_MAX = 60  # Максимальний період для динаміки (хвилини)

# 🎯 НАЛАШТУВАННЯ МЕРЕЖ: Тільки BSC, Ethereum і Solana як просить користувач
ALLOWED_CHAINS = ["ethereum", "bsc", "solana"]  # Основні мережі для якісних монет

# 🎯 НАЛАШТУВАННЯ DEX ПРОВАЙДЕРІВ: всі 20 платформ для максимального пошуку монет
ALLOWED_DEX_PROVIDERS = [
    # Ethereum Network DEXs
    "uniswap",          # №1 DEX на Ethereum
    "sushiswap",        # Мульти-ланцюгова платформа
    "curve",            # Стейблкойн свопи
    "balancer",         # Weighted пули
    "dydx",             # Perpetual торгівля
    
    # BSC Network DEXs  
    "pancakeswap",      # Домінантна BSC платформа
    "apeswap",          # Комьюніті-керована BSC
    "bakeryswap",       # BSC з NFT інтеграцією
    "biswap",           # Низькі комісії BSC
    "mdex",             # Мульти-ланцюгова BSC+ETH
    "wombat",           # Стейблкойн свопи BSC
    
    # Polygon Network DEXs
    "quickswap",        # №1 DEX на Polygon
    "sushiswap_polygon",# SushiSwap на Polygon
    "curve_polygon",    # Curve на Polygon
    
    # Avalanche Network DEXs
    "traderjoe",        # №1 DEX на Avalanche
    "pangolin",         # Native Avalanche DEX
    "sushiswap_avalanche", # SushiSwap на Avalanche
    
    # Multi-Chain Aggregators (всі мережі)
    "openocean",        # Головний агрегатор 40+ ланцюгів
    "rubic",            # Мульти-ланцюгові свопи  
    "li_fi",            # Кросс-ланцюгові мости
    "alium",            # Мульти-ланцюгова BSC+ETH+Polygon
    "jumper"            # 25 ланцюгів включно всі наші мережі
]  # 20 DEX провайдерів для максимального покриття всіх мереж