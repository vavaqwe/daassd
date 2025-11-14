#!/usr/bin/env python3
"""
Backend server для Trinkenbot Enhanced
Імпортує та запускає FastAPI app з web_interface
"""

import sys
from pathlib import Path

# Додаємо кореневу папку в sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Імпортуємо FastAPI app з web_interface
from web_interface.server import app

# Експортуємо для uvicorn
__all__ = ['app']
