# XT.com Arbitrage Trading Bot (Trinkenbot Enhanced)

## Overview

This project is a sophisticated cryptocurrency arbitrage trading bot designed for XT.com futures markets. It automates the process of identifying and exploiting price discrepancies between XT.com futures and decentralized exchanges (Ethereum, BSC, Solana). **The bot automatically scans 700+ futures pairs on XT.com (USDT, USD, USDC markets) and can fetch DEX prices for any of these tokens through a multi-provider system (Direct Blockchain Pools → CoinGecko → DexScreener fallback API).** It calculates spreads and executes trades to capitalize on profitable opportunities. The system integrates a React web dashboard, FastAPI backend, Flask admin panel, and a Telegram bot for comprehensive management and monitoring. The bot incorporates advanced risk management, dual-account trading, and automatic multi-provider price discovery for maximum market coverage. The bot is optimized for 24/7 activity on a VM deployment.

## User Preferences

Preferred communication style: Simple, everyday language.
Language: Ukrainian (українська мова)

## System Architecture

### Core Trading Engine
- **Main Bot Logic**: Implements arbitrage detection and trading algorithms using threaded workers for concurrent symbol scanning.
- **Market Scanner**: Discovers and monitors XT.com futures markets with runtime enable/disable controls.
- **Spread Calculation**: Compares XT.com futures prices with DEX reference prices to identify arbitrage.
- **Position Management**: Tracks active positions with pyramiding support.
- **Risk Management**: Internal Take-Profit/Stop-Loss logic for flexible exit strategies without publishing orders.

### Exchange Integration
- **XT.com Client**: CCXT-based integration for futures trading on XT.com, supporting dual-account parallel trading, **700+ futures market coverage (USDT, USD, USDC settlement currencies)**, order book depth analysis, balance management, and market order execution with leverage.
- **DEX Integration**: Multi-provider price discovery system with automatic fallback chain:
  1. **Direct Blockchain Pools** (35 major tokens): Uniswap V2/V3, PancakeSwap V2, Raydium via Web3 RPC calls
  2. **CoinGecko API** (25 major tokens): Free, reliable price data for top cryptocurrencies
  3. **DexScreener Symbol Search** (unlimited tokens): Automatic symbol-based search finds any token on any DEX with quality liquidity filters
  
  This three-tier system ensures **700+ token coverage** - any token trading on XT.com can automatically get a DEX reference price for spread calculation.

### Administrative Interfaces
- **Flask Web Admin**: Comprehensive web-based control panel with dual admin support, real-time balance and position monitoring, symbol-level trading controls, configuration management, and live/dry-run mode switching.
- **Telegram Bot Admin**: Mobile-friendly administration interface with multi-admin support, group notifications, real-time status updates, position monitoring, and configuration adjustments via chat.

### Configuration Management
- **Environment-Based Config**: Centralized configuration using environment variables for API keys, trading parameters (amounts, spreads, leverage, position limits), safety controls, and authentication settings.

### Utility Systems
- **Utils Module**: Provides supporting functions for spread calculation, a centralized notification system (sending critical messages to both administrators and a Telegram group), Telegram message sending, and logging.

### Application Entry Points
- **Main Runner**: Orchestrates system startup, launching the trading bot, Telegram admin bot, and Flask web admin panel in separate processes/threads for graceful service coordination.

## External Dependencies

### Trading Infrastructure
- **XT.com API**: Primary trading venue for futures contracts, accessed via the CCXT library for market data, order execution, and account management.

### Price Reference Sources
- **Ethereum RPC (eth.llamarpc.com)**: For Uniswap V2/V3 price fetching.
- **BSC RPC (bsc-dataseed.binance.org)**: For PancakeSwap V2 price fetching.
- **Solana RPC (api.mainnet-beta.solana.com)**: For Raydium price fetching.
- **Web3.py**: Python library for interacting with Ethereum and BSC blockchains.
- **Solana**: Python library for interacting with the Solana blockchain.

### Communication Services
- **Telegram Bot API**: Used for mobile administration, real-time alerts, and notifications.

### Development and Deployment
- **FastAPI**: Backend web framework.
- **Flask**: Web framework for the admin panel interface.
- **React**: Frontend for the web dashboard.
- **Uvicorn**: ASGI server for FastAPI.
- **Gunicorn**: WSGI HTTP server for Python web applications, used for deployment.
- **CCXT**: Unified cryptocurrency exchange API library.
- **Python-Telegram-Bot**: Library for Telegram bot interaction.
- **TA-Lib**: Technical analysis library for indicators like RSI, MACD, Bollinger Bands.
- **Pandas**: Data analysis and manipulation library.
- **NumPy**: Numerical computing library.