#!/usr/bin/env python3
"""
Test script to verify PnL calculation fix
"""

# Моделюємо дані позиції як вони зберігаються в active_positions
position_before_fix = {
    'symbol': 'AVA/USDT:USDT',
    'side': 'SHORT',
    'avg_entry': 0.3492,  # Entry price
    'entryPrice': 0.3492,
    'size_usdt': 34.92,
    'leverage': 7,
    # ПРОБЛЕМА: currentPrice і markPrice відсутні!
    # Це було причиною PnL=0
}

position_after_fix = {
    'symbol': 'AVA/USDT:USDT',
    'side': 'SHORT',
    'avg_entry': 0.3492,  # Entry price  
    'entryPrice': 0.3492,
    'size_usdt': 34.92,
    'leverage': 7,
    # ФІКС: Тепер додаємо current price
    'currentPrice': 0.3597,  # Поточна ціна (як з біржі)
    'markPrice': 0.3597
}

def calculate_pnl_percentage_test(position, use_leverage=True):
    """Тестова версія функції calculate_pnl_percentage"""
    try:
        symbol = position.get('symbol', 'UNKNOWN')
        
        # FALLBACK для entry price
        entry_price = float(
            position.get('entryPrice') or 
            position.get('avg_entry') or 
            position.get('entry_price') or 0
        )
        
        # FALLBACK для current price
        current_price = float(
            position.get('markPrice') or 
            position.get('currentPrice') or 
            position.get('current_price') or 0
        )
        
        # Нормалізація сторони
        side = str(position.get('side', 'LONG')).upper()
        if side.lower() in ['buy', 'long']:
            side = 'LONG'
        elif side.lower() in ['sell', 'short']:
            side = 'SHORT'
        
        # Валідація даних
        if entry_price <= 0 or current_price <= 0:
            print(f"⚠️ [{symbol}] P&L неможливо: entry={entry_price}, current={current_price}")
            return 0.0
        
        # Розрахунок базового P&L%
        if side == 'LONG':
            pnl_pct = ((current_price - entry_price) / entry_price) * 100
        else:  # SHORT
            pnl_pct = ((entry_price - current_price) / entry_price) * 100
        
        # Застосування левериджу
        if use_leverage:
            leverage = float(position.get('leverage', 7))
            pnl_pct = pnl_pct * leverage
        
        print(f"✅ [{symbol}] P&L: {side} {pnl_pct:.2f}% (entry=${entry_price}, current=${current_price}, lev={use_leverage})")
        return round(pnl_pct, 2)
        
    except Exception as e:
        symbol = position.get('symbol', 'UNKNOWN') if isinstance(position, dict) else 'UNKNOWN'
        print(f"❌ P&L помилка [{symbol}]: {e}")
        return 0.0


print("=" * 70)
print("🔍 ТЕСТ ФІКСУ PnL РОЗРАХУНКУ")
print("=" * 70)

print("\n📊 СИТУАЦІЯ ДО ФІКСУ (currentPrice відсутня):")
print("-" * 70)
pnl_before = calculate_pnl_percentage_test(position_before_fix, use_leverage=True)
print(f"Результат: PnL = {pnl_before:+.2f}%")
print(f"Проблема: {'❌ PnL = 0%' if pnl_before == 0 else '✅ PnL розраховано'}")

print("\n" + "=" * 70)
print("📊 СИТУАЦІЯ ПІСЛЯ ФІКСУ (currentPrice додано):")
print("-" * 70)
pnl_after = calculate_pnl_percentage_test(position_after_fix, use_leverage=True)
print(f"Результат: PnL = {pnl_after:+.2f}%")
print(f"Статус: {'✅ PnL правильно розраховано!' if pnl_after != 0 else '❌ Все ще проблема'}")

print("\n" + "=" * 70)
print("📈 ОЧІКУВАНИЙ РОЗРАХУНОК:")
print("-" * 70)
entry = 0.3492
current = 0.3597
price_change = ((entry - current) / entry) * 100  # SHORT: прибуток коли ціна падає
leverage = 7
expected_pnl = price_change * leverage

print(f"Entry Price: ${entry}")
print(f"Current Price: ${current}")
print(f"Сторона: SHORT")
print(f"Зміна ціни: {price_change:.2f}%")
print(f"Leverage: {leverage}x")
print(f"Очікуваний PnL: {expected_pnl:.2f}%")

print("\n" + "=" * 70)
print("🎯 ПОРІВНЯННЯ:")
print("-" * 70)
print(f"До фіксу: {pnl_before:+.2f}%")
print(f"Після фіксу: {pnl_after:+.2f}%")
print(f"Очікувано: {expected_pnl:+.2f}%")
print(f"Різниця: {abs(pnl_after - expected_pnl):.2f}%")

if abs(pnl_after - expected_pnl) < 0.1 and pnl_before == 0:
    print("\n✅ ФІКС ПРАЦЮЄ ПРАВИЛЬНО! ✅")
    print("PnL тепер розраховується коректно з поточною ціною.")
else:
    print("\n⚠️ ПОТРІБНА ДОДАТКОВА ПЕРЕВІРКА")

print("=" * 70)
