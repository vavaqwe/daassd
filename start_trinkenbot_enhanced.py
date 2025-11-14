#!/usr/bin/env python3
"""
🚀 Trinkenbot Enhanced - Повна інтеграція
Запуск оригінального бота + веб-інтерфейсу
Створено Emergent AI Agent - 30 вересня 2025
"""

import os
import sys
import subprocess
import threading
import time
import logging
from pathlib import Path

# Налаштування логування
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TrinkenbotEnhanced:
    def __init__(self):
        self.base_dir = Path(__file__).parent
        self.original_bot_process = None
        self.web_api_process = None
        self.web_frontend_process = None
        self.running = False

    def check_dependencies(self):
        """Перевірка залежностей та API ключів"""
        logger.info("🔍 Перевірка залежностей...")
        
        # Перевірка Python пакетів
        required_packages = ['ccxt', 'fastapi', 'uvicorn']
        missing = []
        
        for package in required_packages:
            try:
                __import__(package)
                logger.info(f"✅ {package} встановлено")
            except ImportError:
                missing.append(package)
                logger.warning(f"❌ {package} відсутній")
        
        if missing:
            logger.info("📦 Встановлення відсутніх пакетів...")
            for package in missing:
                subprocess.run([sys.executable, '-m', 'pip', 'install', package])
        
        # Перевірка API ключів
        from dotenv import load_dotenv
        load_dotenv()
        
        api_key = os.getenv('XT_API_KEY')
        api_secret = os.getenv('XT_API_SECRET')
        
        if not api_key or not api_secret:
            logger.error("❌ XT API ключі не налаштовані в .env файлі!")
            return False
        
        # Тест XT підключення
        try:
            import ccxt
            xt = ccxt.xt({
                'apiKey': api_key,
                'secret': api_secret,
                'sandbox': False
            })
            markets = xt.load_markets()
            futures_count = len([s for s, m in markets.items() if m.get('type') in ['swap', 'future']])
            logger.info(f"✅ XT.com підключення OK: {futures_count} фьючерсних пар")
        except Exception as e:
            logger.error(f"❌ XT.com підключення: {e}")
            return False
        
        return True

    def start_original_bot(self):
        """Запуск оригінального торгового бота"""
        try:
            logger.info("🤖 Запуск оригінального Trinkenbot...")
            
            # Перевірка чи існує main.py
            if not (self.base_dir / 'main.py').exists():
                logger.warning("⚠️ main.py не знайдено, пропускаємо запуск оригінального бота")
                return True
            
            self.original_bot_process = subprocess.Popen([
                sys.executable, 'main.py'
            ], cwd=self.base_dir)
            
            logger.info("✅ Оригінальний бот запущено")
            return True
        except Exception as e:
            logger.error(f"❌ Помилка запуску оригінального бота: {e}")
            return False

    def start_web_api(self):
        """Запуск FastAPI веб-сервера"""
        try:
            logger.info("🌐 Запуск Web API сервера...")
            
            web_server_file = self.base_dir / 'web_interface' / 'server.py'
            if not web_server_file.exists():
                logger.error("❌ Web API сервер не знайдено")
                return False
            
            self.web_api_process = subprocess.Popen([
                sys.executable, str(web_server_file)
            ])
            
            # Чекаємо запуску
            time.sleep(3)
            logger.info("✅ Web API запущено на http://localhost:8001")
            return True
        except Exception as e:
            logger.error(f"❌ Помилка запуску Web API: {e}")
            return False

    def start_web_frontend(self):
        """Запуск React frontend"""
        try:
            logger.info("⚛️ Запуск React Frontend...")
            
            frontend_dir = self.base_dir / 'frontend'
            if not frontend_dir.exists():
                logger.error("❌ Frontend директорія не знайдена")
                return False
            
            # Перевірка package.json
            if not (frontend_dir / 'package.json').exists():
                logger.error("❌ package.json не знайдено")
                return False
            
            # Встановлення залежностей якщо потрібно
            if not (frontend_dir / 'node_modules').exists():
                logger.info("📦 Встановлення frontend залежностей...")
                subprocess.run(['yarn', 'install'], cwd=frontend_dir, check=True)
            
            # Запуск frontend
            self.web_frontend_process = subprocess.Popen([
                'yarn', 'start'
            ], cwd=frontend_dir)
            
            # Чекаємо запуску
            time.sleep(5)
            logger.info("✅ React Frontend запущено на http://localhost:3000")
            return True
        except Exception as e:
            logger.error(f"❌ Помилка запуску frontend: {e}")
            return False

    def monitor_processes(self):
        """Моніторинг процесів"""
        logger.info("👁️ Запуск моніторингу процесів...")
        
        while self.running:
            time.sleep(30)  # Перевірка кожні 30 секунд
            
            processes = [
                ("Оригінальний бот", self.original_bot_process),
                ("Web API", self.web_api_process),
                ("React Frontend", self.web_frontend_process)
            ]
            
            for name, process in processes:
                if process and process.poll() is not None:
                    logger.warning(f"⚠️ {name} зупинився (код: {process.returncode})")

    def start_all(self):
        """Запуск всієї системи"""
        logger.info("🚀 Запуск Trinkenbot Enhanced...")
        print("━" * 60)
        print("🤖 TRINKENBOT ENHANCED - Startup")
        print("━" * 60)
        
        if not self.check_dependencies():
            return False
        
        self.running = True
        
        # Запуск компонентів
        success_count = 0
        total_components = 3
        
        if self.start_original_bot():
            success_count += 1
            
        if self.start_web_api():
            success_count += 1
            
        if self.start_web_frontend():
            success_count += 1
        
        if success_count >= 2:  # Мінімум Web API + Frontend
            logger.info("✅ Система запущена успішно!")
            self.print_status()
            
            # Запуск моніторингу
            monitor_thread = threading.Thread(target=self.monitor_processes, daemon=True)
            monitor_thread.start()
            
            return True
        else:
            logger.error("❌ Критична помилка запуску системи")
            return False

    def print_status(self):
        """Виведення статусу системи"""
        print("━" * 60)
        print("🎉 TRINKENBOT ENHANCED - ГОТОВИЙ!")
        print("━" * 60)
        
        if self.original_bot_process:
            print("🤖 Оригінальний бот: ✅ Активний")
        else:
            print("🤖 Оригінальний бот: ⚠️ Не запущено")
            
        if self.web_api_process:
            print("🌐 Web API: ✅ http://localhost:8001")
        else:
            print("🌐 Web API: ❌ Не запущено")
            
        if self.web_frontend_process:
            print("⚛️ Web Dashboard: ✅ http://localhost:3000")
        else:
            print("⚛️ Web Dashboard: ❌ Не запущено")
            
        print("━" * 60)
        print("🔑 ВХІД В DASHBOARD:")
        print("   • API Key: edbae47c-5dd1-4e17-85a5-4ddbf9a0198d")
        print("   • API Secret: dc15cbd32da51249b35326dcc0bafb9045771fa8")
        print("   • Password: trinken2024")
        print("━" * 60)
        print("💡 Відкрийте http://localhost:3000 в браузері")
        print("⚠️  Натисніть Ctrl+C для зупинки")
        print("━" * 60)

    def stop_all(self):
        """Зупинка всіх процесів"""
        logger.info("🛑 Зупинка системи...")
        self.running = False
        
        processes = [
            ("React Frontend", self.web_frontend_process),
            ("Web API", self.web_api_process),
            ("Оригінальний бот", self.original_bot_process),
        ]
        
        for name, process in processes:
            if process:
                try:
                    process.terminate()
                    process.wait(timeout=10)
                    logger.info(f"✅ {name} зупинено")
                except:
                    try:
                        process.kill()
                        logger.warning(f"⚠️ {name} примусово закрито")
                    except:
                        pass

if __name__ == "__main__":
    bot = TrinkenbotEnhanced()
    
    try:
        if bot.start_all():
            # Очікування сигналу зупинки
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n🛑 Отримано сигнал зупинки...")
    except Exception as e:
        logger.error(f"💥 Критична помилка: {e}")
    finally:
        bot.stop_all()
        print("\n👋 Trinkenbot Enhanced зупинено")
        print("🙏 Дякуємо за використання!")