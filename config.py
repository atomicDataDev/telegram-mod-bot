"""
Base bot configuration.

Secrets and local runtime parameters are loaded from .env or environment variables.
"""

import os
from pathlib import Path

from dotenv import load_dotenv


# Load .env from the project root if present.
load_dotenv(Path(__file__).with_name(".env"))

# ══════════════════════════════════════════════
#  SECRETS AND LOCAL SETTINGS
# ══════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")


DB_PATH = os.getenv("DB_PATH", "modbot.db")

# This user ID is treated as the bot owner and has full access
# to global settings in the bot's private chat.
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

DEFAULTS = {
    "DUEL_TIMEOUT": 120,
    "DUEL_MUTE_SECONDS": 60,
    "DUEL_MAX_ROUNDS": 5,
    "DUEL_BASE_AIM": 20,
    "DUEL_AIM_STEP": 10,
    "DUEL_TURN_TIMEOUT": 30,
    "MAX_WARNS": 5,
}

# Labels used in the private settings menu.
SETTING_DESCRIPTIONS = {
    "DUEL_TIMEOUT": "⏱ Таймаут вызова на дуэль (сек)",
    "DUEL_MUTE_SECONDS": "🔇 Мут проигравшему (сек, 0=откл)",
    "DUEL_MAX_ROUNDS": "🎮 Количество раундов",
    "DUEL_BASE_AIM": "🎯 Начальный прицел (%)",
    "DUEL_AIM_STEP": "📐 Шаг изменения прицела (%)",
    "DUEL_TURN_TIMEOUT": "⏳ Таймаут хода (сек)",
    "MAX_WARNS": "⚠️ Варнов до бана",
}

# Validation limits for settings values: (min, max).
SETTING_LIMITS = {
    "DUEL_TIMEOUT": (10, 600),
    "DUEL_MUTE_SECONDS": (0, 86400),
    "DUEL_MAX_ROUNDS": (1, 20),
    "DUEL_BASE_AIM": (5, 95),
    "DUEL_AIM_STEP": (1, 50),
    "DUEL_TURN_TIMEOUT": (5, 300),
    "MAX_WARNS": (1, 50),
}
