"""
Example configuration for the first run.

This file shows the values structure you can set via .env.
"""

BOT_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
DB_PATH = "modbot.db"
OWNER_ID = 0

DEFAULTS = {
    "DUEL_TIMEOUT": 120,
    "DUEL_MUTE_SECONDS": 60,
    "DUEL_MAX_ROUNDS": 5,
    "DUEL_BASE_AIM": 20,
    "DUEL_AIM_STEP": 10,
    "DUEL_TURN_TIMEOUT": 30,
    "MAX_WARNS": 5,
}

SETTING_DESCRIPTIONS = {
    "DUEL_TIMEOUT": "⏱ Таймаут вызова на дуэль (сек)",
    "DUEL_MUTE_SECONDS": "🔇 Мут проигравшему (сек, 0=откл)",
    "DUEL_MAX_ROUNDS": "🎮 Количество раундов",
    "DUEL_BASE_AIM": "🎯 Начальный прицел (%)",
    "DUEL_AIM_STEP": "📐 Шаг изменения прицела (%)",
    "DUEL_TURN_TIMEOUT": "⏳ Таймаут хода (сек)",
    "MAX_WARNS": "⚠️ Варнов до бана",
}

SETTING_LIMITS = {
    "DUEL_TIMEOUT": (10, 600),
    "DUEL_MUTE_SECONDS": (0, 86400),
    "DUEL_MAX_ROUNDS": (1, 20),
    "DUEL_BASE_AIM": (5, 95),
    "DUEL_AIM_STEP": (1, 50),
    "DUEL_TURN_TIMEOUT": (5, 300),
    "MAX_WARNS": (1, 50),
}
