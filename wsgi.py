"""
WSGI entry point for production deployment with Gunicorn
"""
import logging
import threading

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Import Flask app
from main import app, start_trading_bot

# Start trading bot in background thread when Gunicorn starts
logging.info("🚀 WSGI: Ініціалізація торгового бота...")
bot_thread = threading.Thread(target=start_trading_bot, daemon=True)
bot_thread.start()
logging.info("✅ WSGI: Торговий бот запущено в фоновому режимі")

# Expose app for Gunicorn
if __name__ == "__main__":
    # This won't be called by Gunicorn, but useful for testing
    app.run(host='0.0.0.0', port=5000, debug=False)
