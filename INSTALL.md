# 🚀 Trinkenbot Enhanced - Installation Guide

**⚠️ ВАЖЛИВО:** Цей репозиторій не містить `node_modules` (400MB) для економії місця на GitHub.

## 📦 ШВИДКЕ ВСТАНОВЛЕННЯ:

### 1. Клонувати репозиторій:
```bash
git clone https://github.com/labritaliy063-sgs/obana.git
cd obana
```

### 2. Встановити залежності:

**Frontend (React):**
```bash
cd frontend
yarn install
# Або: npm install
cd ..
```

**Backend (Python):**
```bash
cd backend  
pip install -r requirements.txt
cd ..
```

### 3. Налаштувати API ключі:
Файли `.env` вже налаштовані з вашими ключами:
- `backend/.env` - XT API ключі та налаштування
- `frontend/.env` - URL backend сервера

### 4. Запустити систему:

**Варіант A: Все разом (рекомендовано)**
```bash
python start_trinkenbot_enhanced.py
```

**Варіант B: Окремо**
```bash
# Terminal 1: Backend
cd backend && python server.py

# Terminal 2: Frontend  
cd frontend && yarn start

# Terminal 3: Ваш оригінальний бот
python main.py
```

## 🌐 Доступ до системи:
- **Web Dashboard:** http://localhost:3000
- **API Backend:** http://localhost:8001
- **Вхід:** API ключі з .env + пароль `trinken2024`

## ✅ Що працює:
- ✅ 790+ фьючерсних пар з XT.com
- ✅ Технічні індикатори (RSI, MACD, Bollinger)
- ✅ DEX арбітраж (Ethereum, BSC, Solana)
- ✅ Веб-інтерфейс українською мовою
- ✅ Ваша повна торгова логіка

## 🔧 Структура проекту:
```
obana/
├── bot.py              # 🤖 Ваш оригінальний арбітражний бот
├── main.py             # 🚀 Запуск вашого бота  
├── config.py           # ⚙️ Налаштування
├── xt_client.py        # 📡 XT.com клієнт (виправлений)
├── technical_indicators.py  # 📊 RSI, MACD, TA-Lib
├── profit_calculator.py     # 💰 P&L розрахунки
├── real_dex_client.py       # 🌐 Blockchain інтеграція
├── web_interface/      # 🌍 FastAPI сервер
├── frontend/           # ⚛️ React Dashboard
└── start_trinkenbot_enhanced.py  # 🔗 Інтегрований запуск
```

---
**Створено:** Emergent AI Agent  
**Розмір після встановлення:** ~487MB  
**Статус:** Production Ready ✅