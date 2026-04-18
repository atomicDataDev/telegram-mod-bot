#!/usr/bin/env python3
"""
Telegram Moderator + Interactive Duel + Reputation Bot
With configuration via bot private chat.
"""

import asyncio
import logging
import html
import random
import time as _time
from functools import wraps
from typing import Dict
from telegram.error import BadRequest

from telegram import (
    Update,
    ChatPermissions,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ChatMemberHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ChatMemberStatus

from config import (
    BOT_TOKEN, DB_PATH, OWNER_ID, DEFAULTS,
    SETTING_DESCRIPTIONS, SETTING_LIMITS,
)
from database import Database

# Keep logging minimal for the public repository:
# only real bot/library errors are written to console.
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.ERROR  # ERROR and CRITICAL only
)

# Project logger used across handlers and background jobs.
log = logging.getLogger("modbot")
log.setLevel(logging.ERROR)

# Reduce dependency noise so failures are easier to spot in logs.
logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger("telegram").setLevel(logging.ERROR)
logging.getLogger("apscheduler").setLevel(logging.ERROR)

if not BOT_TOKEN or BOT_TOKEN.startswith("YOUR"):
    print("ОШИБКА: Откройте config.py и вставьте токен бота!")
    exit(1)

# Database is initialized at startup; schema is created automatically.
db = Database(DB_PATH)

# Bot owner automatically gets access to global settings.
if OWNER_ID and OWNER_ID != 0:
    db.add_bot_admin(OWNER_ID)


# ══════════════════════════════════════════════
#  DYNAMIC SETTINGS
# ══════════════════════════════════════════════

def get_cfg(key: str) -> int:
    """Read a setting from DB first, then fall back to DEFAULTS."""
    val = db.get_setting(key)
    if val is not None:
        try:
            return int(val)
        except ValueError:
            pass
    return DEFAULTS.get(key, 0)


# Convenience wrappers
def DUEL_TIMEOUT():      return get_cfg("DUEL_TIMEOUT")
def DUEL_MUTE_SECONDS(): return get_cfg("DUEL_MUTE_SECONDS")
def DUEL_MAX_ROUNDS():   return get_cfg("DUEL_MAX_ROUNDS")
def DUEL_BASE_AIM():     return get_cfg("DUEL_BASE_AIM")
def DUEL_AIM_STEP():     return get_cfg("DUEL_AIM_STEP")
def DUEL_TURN_TIMEOUT(): return get_cfg("DUEL_TURN_TIMEOUT")
def MAX_WARNS():         return get_cfg("MAX_WARNS")


# ══════════════════════════════════════════════
#  PERMISSIONS
# ══════════════════════════════════════════════

FULL_PERMISSIONS = ChatPermissions(
    can_send_messages=True, can_send_audios=True,
    can_send_documents=True, can_send_photos=True,
    can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True,
    can_send_other_messages=True, can_add_web_page_previews=True,
    can_change_info=False, can_invite_users=True,
    can_pin_messages=True, can_manage_topics=False,
)
MUTED_PERMISSIONS = ChatPermissions(
    can_send_messages=False, can_send_audios=False,
    can_send_documents=False, can_send_photos=False,
    can_send_videos=False, can_send_video_notes=False,
    can_send_voice_notes=False, can_send_polls=False,
    can_send_other_messages=False, can_add_web_page_previews=False,
    can_change_info=False, can_invite_users=False,
    can_pin_messages=False, can_manage_topics=False,
)
TEXT_ONLY_PERMISSIONS = ChatPermissions(
    can_send_messages=True, can_send_audios=False,
    can_send_documents=False, can_send_photos=False,
    can_send_videos=False, can_send_video_notes=False,
    can_send_voice_notes=False, can_send_polls=False,
    can_send_other_messages=False, can_add_web_page_previews=False,
    can_change_info=False, can_invite_users=True,
    can_pin_messages=True, can_manage_topics=False,
)
NO_PIN_PERMISSIONS = ChatPermissions(
    can_send_messages=True, can_send_audios=True,
    can_send_documents=True, can_send_photos=True,
    can_send_videos=True, can_send_video_notes=True,
    can_send_voice_notes=True, can_send_polls=True,
    can_send_other_messages=True, can_add_web_page_previews=True,
    can_change_info=False, can_invite_users=True,
    can_pin_messages=False, can_manage_topics=False,
)

# ══════════════════════════════════════════════
#  RUNTIME STATE
# ══════════════════════════════════════════════

_recently_joined: Dict[str, float] = {}
active_challenges: Dict[str, dict] = {}
active_fights: Dict[str, dict] = {}

# User who selected a /config key is temporarily waiting for value input.
_waiting_setting_value: Dict[int, str] = {}

# ══════════════════════════════════════════════
#  DUEL TEXTS
# ══════════════════════════════════════════════

WEAPONS = [
    "⚔️ мечом", "🔫 бластером", "🏹 луком", "🪓 топором",
    "🔨 молотом", "🗡️ катаной", "💣 гранатой", "🧨 динамитом",
    "🪃 бумерангом", "🍳 сковородкой", "🧹 шваброй", "📱 смартфоном",
    "🎸 гитарой", "🐟 тухлой рыбой", "🌵 кактусом", "🪑 табуреткой",
    "📚 учебником", "🧲 магнитом", "🔧 гаечным ключом", "🎤 микрофоном",
    "💩 какашкой", "🧦 носком", "🎹 пианино", "🛹 скейтбордом",
    "🧊 льдом", "🌶️ перцем чили", "🥊 перчаткой", "🎯 дротиком", "🪚 пилой",
]

AIM_TEXTS = [
    "🎯 {name} тщательно прицеливается…",
    "🔭 {name} наводит прицел…",
    "👁 {name} сощурился и целится…",
    "🎯 {name} выбирает момент…",
]
DISRUPT_TEXTS = [
    "💨 {name} толкает {target}, сбивая прицел!",
    "🗣 {name} кричит {target} в ухо!",
    "🦶 {name} наступает {target} на ногу!",
    "🪨 {name} кидает песок в глаза {target}!",
    "🤡 {name} корчит рожу — {target} отвлёкся!",
]
SHOOT_HIT_TEXTS = [
    "💥 {name} стреляет {weapon} — ПОПАДАНИЕ!",
    "🎯 {name} точно бьёт {weapon}!",
    "⚡ {name} метко попал {weapon}!",
]
SHOOT_LUCKY_TEXTS = [
    "🍀 {name} случайно попал {weapon}!",
    "😲 {name} вслепую попал {weapon}!",
]
SHOOT_MISS_TEXTS = [
    "💨 {name} стреляет {weapon} — мимо!",
    "🌀 {name} бьёт {weapon}, промах!",
    "😅 {name} выстрелил {weapon} — не попал!",
]
KILL_TEXTS = [
    "☠️ {target} повержен! {name} побеждает!",
    "💀 {target} падает! Победа за {name}!",
    "🏆 {name} наносит финальный удар!",
]
DRAW_TEXTS = [
    "🤝 Ничья! Оба без сил!",
    "⚖️ Силы равны — никто не победил!",
    "🎭 Дуэлянты заключили перемирие!",
]


# ══════════════════════════════════════════════
#  UTILITIES
# ══════════════════════════════════════════════

async def is_admin(chat_id, user_id, context):
    try:
        m = await context.bot.get_chat_member(chat_id, user_id)
        return m.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False


def is_bot_admin_user(user_id: int) -> bool:
    """Check whether user is a bot admin (owner or explicitly added)."""
    if OWNER_ID and user_id == OWNER_ID:
        return True
    return db.is_bot_admin(user_id)


def user_link(uid, name):
    return f"<a href='tg://user?id={uid}'>{html.escape(name or str(uid))}</a>"


def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.type == "private":
            await update.message.reply_text("❌ Только в группах.")
            return
        if not await is_admin(update.effective_chat.id, update.effective_user.id, context):
            await update.message.reply_text("❌ Только для администраторов.")
            return
        return await func(update, context)
    return wrapper


def bot_admin_only(func):
    """Decorator: allow bot admins only (private chat)."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if not is_bot_admin_user(uid):
            await update.message.reply_text(
                "❌ У вас нет прав для управления настройками бота.\n"
                "Обратитесь к владельцу бота.")
            return
        return await func(update, context)
    return wrapper


async def resolve_target(update, context):
    # Unified target resolution for moderation commands:
    # reply, mention, text_mention, or numeric ID in args.
    msg = update.message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, u.first_name
    if msg.entities:
        for ent in msg.entities:
            if ent.type == "text_mention" and ent.user:
                return ent.user.id, ent.user.first_name
            if ent.type == "mention":
                username = msg.text[ent.offset + 1: ent.offset + ent.length]
                row = db.find_by_username(msg.chat.id, username)
                if row:
                    return row["user_id"], row["first_name"] or username
                return None, None
    if context.args:
        for arg in context.args:
            try:
                uid = int(arg)
                row = db.find_by_id(msg.chat.id, uid)
                return uid, (row["first_name"] if row else str(uid))
            except ValueError:
                continue
    return None, None


def parse_minutes(args, default=15):
    for a in (args or []):
        try:
            return max(1, int(a))
        except ValueError:
            continue
    return default


# ══════════════════════════════════════════════
#  /help
# ══════════════════════════════════════════════


def _build_help_group():
    """Help text for group chats (without private settings)."""
    return f"""
🤖 <b>Бот-модератор + Дуэли + Репутация</b>

<b>🛡 Авто-модерация:</b>
Новые участники ограничены до одобрения.

<b>👮 Админ-команды:</b>
/lock /unlock — чат
/lockmedia /unlockmedia — медиа
/lockpin /unlockpin — закрепление
/mute [мин] — замутить (15 по умолч.)
/unmute — размутить
/kick /ban /unban — кик/бан
/warn — предупреждение ({MAX_WARNS()} = бан)
/resetwarns — сброс варнов (всем или @ник)
/pending — ожидающие
/settings — настройки чата
/banduel /unbanduel — дуэли вкл/откл

<b>⚔️ Интерактивные дуэли ({DUEL_MAX_ROUNDS()} раундов):</b>
/duel — вызвать (ответом / @ник)
/duelstats — топ  /myduel — моя стата

Каждый раунд ТЫ выбираешь:
🎯 Прицелиться (+{DUEL_AIM_STEP()}%)
💨 Сбить прицел врагу (−{DUEL_AIM_STEP()}%)
🔫 Выстрелить (шанс = прицел%)

<b>⭐ Репутация (1 голос/день):</b>
/rep + / /rep - (ответом / @ник)
/myrep — моя  /toprep — топ
"""


def _build_help_private():
    """Help text for private chat (includes settings commands)."""
    return _build_help_group() + """
<b>⚙️ Настройки бота (только здесь, в ЛС):</b>
/config — меню настроек бота
/addadmin ID — добавить админа бота
/removeadmin ID — убрать админа бота
/admins — список админов бота

💡 <i>Настройки бота можно менять только в ЛС.</i>
"""


async def cmd_help(update, context):
    if update.effective_chat.type == "private":
        await update.message.reply_text(_build_help_private(), parse_mode="HTML")
    else:
        await update.message.reply_text(_build_help_group(), parse_mode="HTML")


# ══════════════════════════════════════════════
#  ⚙️ PRIVATE SETTINGS
# ══════════════════════════════════════════════

def _build_config_text():
    """Render current settings text."""
    lines = ["⚙️ <b>Настройки бота</b>\n"]
    for key in DEFAULTS:
        val = get_cfg(key)
        desc = SETTING_DESCRIPTIONS.get(key, key)
        default = DEFAULTS[key]
        is_custom = db.get_setting(key) is not None
        marker = "✏️" if is_custom else "📋"
        lines.append(f"{marker} {desc}: <b>{val}</b>"
                     + (f" (по умолч. {default})" if is_custom else ""))
    lines.append("\n📝 Нажмите кнопку для изменения:")
    return "\n".join(lines)


def _build_config_keyboard():
    """Build settings keyboard."""
    buttons = []
    keys = list(DEFAULTS.keys())
    for i in range(0, len(keys), 2):
        row = []
        for key in keys[i:i+2]:
            desc = SETTING_DESCRIPTIONS.get(key, key)
            # Short label for button text
            short = desc.split("(")[0].strip()
            row.append(InlineKeyboardButton(short, callback_data=f"cfg_edit:{key}"))
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🔄 Сброс всех", callback_data="cfg_reset_all")])
    return InlineKeyboardMarkup(buttons)


@bot_admin_only
async def cmd_config(update, context):
    """Settings menu: private chat only."""
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "⚙️ Настройки можно менять только в ЛС бота.\n"
            "👉 Напишите мне в личные сообщения и введите /config")
        return
    text = _build_config_text()
    kb = _build_config_keyboard()
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def callback_config(update, context):
    """Handle settings button callbacks."""
    q = update.callback_query
    uid = q.from_user.id

    if not is_bot_admin_user(uid):
        return await q.answer("❌ Нет доступа!", show_alert=True)

    data = q.data

    if data == "cfg_reset_all":
        # Check whether there is anything to reset.
        had_custom = False
        for key in DEFAULTS:
            if db.get_setting(key) is not None:
                had_custom = True
                break

        if not had_custom:
            return await q.answer("ℹ️ Все настройки уже по умолчанию!", show_alert=True)

        for key in DEFAULTS:
            with db.lock, db._conn() as c:
                c.execute("DELETE FROM global_settings WHERE key=?", (key,))
        _waiting_setting_value.pop(uid, None)
        text = _build_config_text()
        text += "\n\n✅ <b>Все настройки сброшены к значениям по умолчанию!</b>"
        kb = _build_config_keyboard()
        try:
            await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                raise
        return await q.answer("✅ Сброшено!")

    if data.startswith("cfg_edit:"):
        key = data.split(":", 1)[1]
        if key not in DEFAULTS:
            return await q.answer("❌ Неизвестный параметр!", show_alert=True)

        desc = SETTING_DESCRIPTIONS.get(key, key)
        current = get_cfg(key)
        limits = SETTING_LIMITS.get(key, (0, 99999))

        _waiting_setting_value[uid] = key

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Назад", callback_data="cfg_back")],
            [InlineKeyboardButton(f"🔄 Сброс ({DEFAULTS[key]})", callback_data=f"cfg_reset:{key}")],
        ])

        try:
            await q.edit_message_text(
                f"✏️ <b>{desc}</b>\n\n"
                f"Текущее значение: <b>{current}</b>\n"
                f"По умолчанию: <b>{DEFAULTS[key]}</b>\n"
                f"Допустимый диапазон: <b>{limits[0]} — {limits[1]}</b>\n\n"
                f"📝 <b>Отправьте новое значение числом:</b>",
                parse_mode="HTML", reply_markup=kb)
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                raise
        return await q.answer()

    if data == "cfg_back":
        _waiting_setting_value.pop(uid, None)
        text = _build_config_text()
        kb = _build_config_keyboard()
        try:
            await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                raise
        return await q.answer()

    if data.startswith("cfg_reset:"):
        key = data.split(":", 1)[1]

        # Check whether this key has an overridden value.
        if db.get_setting(key) is None:
            return await q.answer(
                f"ℹ️ {SETTING_DESCRIPTIONS.get(key, key)} уже по умолчанию!",
                show_alert=True)

        with db.lock, db._conn() as c:
            c.execute("DELETE FROM global_settings WHERE key=?", (key,))
        _waiting_setting_value.pop(uid, None)
        text = _build_config_text()
        text += f"\n\n✅ <b>{SETTING_DESCRIPTIONS.get(key, key)}</b> сброшен к {DEFAULTS.get(key)}!"
        kb = _build_config_keyboard()
        try:
            await q.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
        except BadRequest as e:
            if "not modified" not in str(e).lower():
                raise
        return await q.answer("✅ Сброшено!")


async def handle_setting_value(update, context):
    """Handle text input for a new settings value in private chat."""
    if update.effective_chat.type != "private":
        return
    uid = update.effective_user.id
    key = _waiting_setting_value.get(uid)
    if not key:
        return  # Not waiting for input, ignore message.

    if not is_bot_admin_user(uid):
        _waiting_setting_value.pop(uid, None)
        return

    text = update.message.text.strip()
    try:
        value = int(text)
    except ValueError:
        return await update.message.reply_text(
            "❌ Введите <b>целое число</b>.", parse_mode="HTML")

    limits = SETTING_LIMITS.get(key, (0, 99999))
    if value < limits[0] or value > limits[1]:
        return await update.message.reply_text(
            f"❌ Значение должно быть от <b>{limits[0]}</b> до <b>{limits[1]}</b>.",
            parse_mode="HTML")

    db.set_setting(key, str(value))
    _waiting_setting_value.pop(uid, None)

    desc = SETTING_DESCRIPTIONS.get(key, key)
    config_text = _build_config_text()
    config_text += f"\n\n✅ <b>{desc}</b> изменён на <b>{value}</b>!"
    kb = _build_config_keyboard()
    await update.message.reply_text(config_text, parse_mode="HTML", reply_markup=kb)


# ══════════════════════════════════════════════
#  BOT ADMIN MANAGEMENT
# ══════════════════════════════════════════════

async def cmd_addadmin(update, context):
    """Add a bot admin. Owner only, private chat only."""
    if update.effective_chat.type != "private":
        return await update.message.reply_text("⚙️ Эта команда работает только в ЛС бота.")
    uid = update.effective_user.id
    if OWNER_ID == 0:
        return await update.message.reply_text(
            "❌ OWNER_ID не задан в config.py!\n"
            "Откройте config.py и впишите свой Telegram ID.")
    if uid != OWNER_ID:
        return await update.message.reply_text("❌ Только владелец бота может добавлять админов.")
    if not context.args:
        return await update.message.reply_text("Использование: /addadmin <user_id>")
    try:
        target_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ Укажите числовой ID.")
    db.add_bot_admin(target_id)
    await update.message.reply_text(
        f"✅ Пользователь <code>{target_id}</code> добавлен как админ бота.\n"
        f"Теперь он может менять настройки через /config в ЛС.",
        parse_mode="HTML")


async def cmd_removeadmin(update, context):
    """Remove a bot admin. Owner only, private chat only."""
    if update.effective_chat.type != "private":
        return await update.message.reply_text("⚙️ Эта команда работает только в ЛС бота.")
    uid = update.effective_user.id
    if uid != OWNER_ID:
        return await update.message.reply_text("❌ Только владелец бота.")
    if not context.args:
        return await update.message.reply_text("Использование: /removeadmin <user_id>")
    try:
        target_id = int(context.args[0])
    except ValueError:
        return await update.message.reply_text("❌ Укажите числовой ID.")
    if target_id == OWNER_ID:
        return await update.message.reply_text("❌ Нельзя удалить владельца!")
    db.remove_bot_admin(target_id)
    await update.message.reply_text(
        f"✅ Пользователь <code>{target_id}</code> удалён из админов бота.",
        parse_mode="HTML")


async def cmd_admins(update, context):
    """List bot admins. Private chat only."""
    if update.effective_chat.type != "private":
        return await update.message.reply_text("⚙️ Эта команда работает только в ЛС бота.")
    uid = update.effective_user.id
    if not is_bot_admin_user(uid):
        return await update.message.reply_text("❌ Нет доступа.")
    admins = db.get_bot_admins()
    lines = ["👑 <b>Админы бота:</b>\n"]
    if OWNER_ID and OWNER_ID != 0:
        lines.append(f"👑 <code>{OWNER_ID}</code> (владелец)")
    for aid in admins:
        if aid != OWNER_ID:
            lines.append(f"🔧 <code>{aid}</code>")
    if len(admins) == 0 and (not OWNER_ID or OWNER_ID == 0):
        lines.append("— нет администраторов —")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ══════════════════════════════════════════════
#  TRACKING
# ══════════════════════════════════════════════

async def track_messages(update, context):
    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user or chat.type == "private" or user.is_bot:
        return
    db.upsert_user(chat.id, user.id, user.username, user.first_name)


# ══════════════════════════════════════════════
#  NEW MEMBERS
# ══════════════════════════════════════════════

async def _process_new_member(chat_id, user, context):
    # Restrict newcomers immediately until an admin reviews them.
    if user.is_bot or user.id == context.bot.id:
        return
    key = f"{chat_id}:{user.id}"
    now = _time.time()
    if now - _recently_joined.get(key, 0) < 30:
        return
    _recently_joined[key] = now
    for k in list(_recently_joined):
        if now - _recently_joined[k] > 120:
            del _recently_joined[k]

    try:
        await context.bot.restrict_chat_member(chat_id, user.id, MUTED_PERMISSIONS)
    except Exception as e:
        log.error("Restrict %s: %s", user.id, e)
        return

    db.add_pending(chat_id, user.id, user.username, user.first_name)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Принять", callback_data=f"approve:{chat_id}:{user.id}"),
        InlineKeyboardButton("❌ Бан", callback_data=f"ban:{chat_id}:{user.id}"),
    ]])
    link = user_link(user.id, user.first_name)
    uname = f" (@{user.username})" if user.username else ""
    await context.bot.send_message(
        chat_id,
        f"👤 Новый участник: {link}{uname}\n"
        f"🆔 <code>{user.id}</code>\n\n"
        f"🔇 <i>Не может писать до одобрения.</i>",
        reply_markup=kb, parse_mode="HTML")


async def on_new_member(update, context):
    msg = update.message
    if not msg or not msg.new_chat_members:
        return
    for m in msg.new_chat_members:
        if m.id == context.bot.id:
            await msg.reply_text(
                "👋 Привет! Назначьте меня админом.\n/help — команды",
                parse_mode="HTML")
            continue
        await _process_new_member(msg.chat.id, m, context)


async def on_chat_member_update(update, context):
    mu = update.chat_member
    if not mu:
        return
    old, new = mu.old_chat_member, mu.new_chat_member

    # Handle re-join the same way as a regular join.
    if old.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED) \
       and new.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED):
        await _process_new_member(mu.chat.id, new.user, context)

    # Cleanup user-related records on leave/ban to avoid stale DB state.
    elif old.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.RESTRICTED,
                        ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER) \
         and new.status in (ChatMemberStatus.LEFT, ChatMemberStatus.BANNED):
        if not new.user.is_bot:
            uid = new.user.id
            cid = mu.chat.id
            db.purge_user(cid, uid)
            log.info("Purged all data for user %s in chat %s", uid, cid)


async def on_left_member(update, context):
    msg = update.message
    if msg and msg.left_chat_member and not msg.left_chat_member.is_bot:
        uid = msg.left_chat_member.id
        cid = msg.chat.id
        db.purge_user(cid, uid)
        log.info("Purged all data for user %s in chat %s (left_chat_member)", uid, cid)


# ══════════════════════════════════════════════
#  MODERATION BUTTONS
# ══════════════════════════════════════════════

async def callback_moderation(update, context):
    # Buttons under "new member" messages are admin-only.
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) != 3:
        return await q.answer("❌")
    action, chat_id, user_id = parts[0], int(parts[1]), int(parts[2])
    if not await is_admin(chat_id, q.from_user.id, context):
        return await q.answer("❌ Только администраторы!", show_alert=True)
    aname = html.escape(q.from_user.first_name)
    link = user_link(user_id, str(user_id))
    if action == "approve":
        try:
            await context.bot.restrict_chat_member(chat_id, user_id, FULL_PERMISSIONS)
            db.approve_user(chat_id, user_id)
            await q.edit_message_text(f"✅ {link} одобрен ({aname})", parse_mode="HTML")
        except Exception as e:
            await q.answer(f"Ошибка: {e}", show_alert=True)
    elif action == "ban":
        try:
            await context.bot.ban_chat_member(chat_id, user_id)
            db.purge_user(chat_id, user_id)
            await q.edit_message_text(f"🚫 <code>{user_id}</code> забанен ({aname})", parse_mode="HTML")
        except Exception as e:
            await q.answer(f"Ошибка: {e}", show_alert=True)
    await q.answer()


# ══════════════════════════════════════════════
#  LOCK / UNLOCK
# ══════════════════════════════════════════════

@admin_only
async def cmd_lock(u, c):
    try:
        await c.bot.set_chat_permissions(u.effective_chat.id, MUTED_PERMISSIONS)
        await u.message.reply_text("🔒 Чат закрыт.")
    except Exception as e:
        await u.message.reply_text(f"❌ {e}")

@admin_only
async def cmd_unlock(u, c):
    try:
        await c.bot.set_chat_permissions(u.effective_chat.id, FULL_PERMISSIONS)
        await u.message.reply_text("🔓 Чат открыт.")
    except Exception as e:
        await u.message.reply_text(f"❌ {e}")

@admin_only
async def cmd_lockmedia(u, c):
    try:
        await c.bot.set_chat_permissions(u.effective_chat.id, TEXT_ONLY_PERMISSIONS)
        await u.message.reply_text("🔒 Медиа отключены.")
    except Exception as e:
        await u.message.reply_text(f"❌ {e}")

@admin_only
async def cmd_unlockmedia(u, c):
    try:
        await c.bot.set_chat_permissions(u.effective_chat.id, FULL_PERMISSIONS)
        await u.message.reply_text("🔓 Медиа разрешены.")
    except Exception as e:
        await u.message.reply_text(f"❌ {e}")

@admin_only
async def cmd_lockpin(u, c):
    try:
        await c.bot.set_chat_permissions(u.effective_chat.id, NO_PIN_PERMISSIONS)
        await u.message.reply_text("📌 Закрепление отключено.")
    except Exception as e:
        await u.message.reply_text(f"❌ {e}")

@admin_only
async def cmd_unlockpin(u, c):
    try:
        await c.bot.set_chat_permissions(u.effective_chat.id, FULL_PERMISSIONS)
        await u.message.reply_text("📌 Закрепление разрешено.")
    except Exception as e:
        await u.message.reply_text(f"❌ {e}")


# ══════════════════════════════════════════════
#  MUTE / UNMUTE / KICK / BAN / WARN
# ══════════════════════════════════════════════

@admin_only
async def cmd_mute(update, context):
    uid, name = await resolve_target(update, context)
    if not uid:
        return await update.message.reply_text("Ответом: /mute 30\nПо нику: /mute @ник 30")
    minutes = parse_minutes(context.args, 15)
    until = int(_time.time()) + minutes * 60
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id, uid, MUTED_PERMISSIONS, until_date=until)
        await update.message.reply_text(
            f"🔇 {user_link(uid, name)} замучен на {minutes} мин.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

@admin_only
async def cmd_unmute(update, context):
    uid, name = await resolve_target(update, context)
    if not uid:
        return await update.message.reply_text("Ответьте или: /unmute @ник")
    try:
        await context.bot.restrict_chat_member(update.effective_chat.id, uid, FULL_PERMISSIONS)
        await update.message.reply_text(f"🔊 {user_link(uid, name)} размучен.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

@admin_only
async def cmd_kick(update, context):
    uid, name = await resolve_target(update, context)
    if not uid:
        return await update.message.reply_text("Ответьте или: /kick @ник")
    try:
        cid = update.effective_chat.id
        await context.bot.ban_chat_member(cid, uid)
        await context.bot.unban_chat_member(cid, uid)
        db.purge_user(cid, uid)
        await update.message.reply_text(f"👢 {user_link(uid, name)} кикнут.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

@admin_only
async def cmd_ban(update, context):
    uid, name = await resolve_target(update, context)
    if not uid:
        return await update.message.reply_text("Ответьте или: /ban @ник")
    if uid == context.bot.id:
        return await update.message.reply_text("🤖 Нельзя забанить самого бота!")
    try:
        cid = update.effective_chat.id
        await context.bot.ban_chat_member(cid, uid)
        db.purge_user(cid, uid)
        await update.message.reply_text(f"🚫 {user_link(uid, name)} забанен.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

@admin_only
async def cmd_unban(update, context):
    uid, name = await resolve_target(update, context)
    if not uid:
        return await update.message.reply_text("/unban @ник или ID")
    if uid == context.bot.id:
        return await update.message.reply_text("❌ Нельзя применить /unban к самому боту!")
    try:
        await context.bot.unban_chat_member(update.effective_chat.id, uid)
        await update.message.reply_text(f"✅ <code>{uid}</code> разбанен.", parse_mode="HTML")
    except Exception as e:
        await update.message.reply_text(f"❌ {e}")

@admin_only
async def cmd_warn(update, context):
    uid, name = await resolve_target(update, context)
    if not uid:
        return await update.message.reply_text("Ответьте или: /warn @ник")
    cid = update.effective_chat.id
    try:
        member = await context.bot.get_chat_member(cid, uid)
        if member.user.is_bot:
            return await update.message.reply_text("🤖 Нельзя выдать предупреждение боту!")
    except Exception:
        pass
    max_warns = MAX_WARNS()
    count = db.add_warn(cid, uid)
    link = user_link(uid, name)
    if count >= max_warns:
        try:
            await context.bot.ban_chat_member(cid, uid)
            db.purge_user(cid, uid)
            await update.message.reply_text(
                f"🚫 {link} — {count}/{max_warns} — забанен!", parse_mode="HTML")
        except Exception as e:
            await update.message.reply_text(f"❌ {e}")
    else:
        await update.message.reply_text(
            f"⚠️ {link} — ({count}/{max_warns})", parse_mode="HTML")


@admin_only
async def cmd_resetwarns(update, context):
    cid = update.effective_chat.id
    uid, name = await resolve_target(update, context)
    if uid:
        old = db.get_warns(cid, uid)
        db.reset_warns(cid, uid)
        await update.message.reply_text(
            f"✅ Варны {user_link(uid, name)} сброшены ({old} → 0).", parse_mode="HTML")
    else:
        count = db.reset_all_warns(cid)
        await update.message.reply_text(
            f"✅ Все предупреждения сброшены.\n🗑 Очищено записей: <b>{count}</b>",
            parse_mode="HTML")


# ══════════════════════════════════════════════
#  PENDING / SETTINGS
# ══════════════════════════════════════════════

@admin_only
async def cmd_pending(update, context):
    rows = db.get_pending(update.effective_chat.id)
    if not rows:
        return await update.message.reply_text("✅ Нет ожидающих.")
    lines = ["⏳ <b>Ожидают одобрения:</b>\n"]
    for r in rows:
        n = html.escape(r["first_name"] or "—")
        u = f" @{r['username']}" if r["username"] else ""
        lines.append(f"• {n}{u} — <code>{r['user_id']}</code>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

@admin_only
async def cmd_settings(update, context):
    cid = update.effective_chat.id
    chat = await context.bot.get_chat(cid)
    p = chat.permissions
    yn = lambda v: "✅" if v else "❌"
    duels = "✅" if db.are_duels_enabled(cid) else "❌"
    await update.message.reply_text(
        f"⚙️ <b>Настройки чата</b>\n\n"
        f"💬 Сообщения: {yn(p.can_send_messages)}\n"
        f"🖼 Медиа: {yn(p.can_send_photos)}\n"
        f"📌 Закрепление: {yn(p.can_pin_messages)}\n"
        f"⚔️ Дуэли: {duels}\n"
        f"\n"
        f"👤 Известных: <b>{db.user_count(cid)}</b>\n"
        f"⏳ Ожидающих: <b>{db.pending_count(cid)}</b>\n\n"
        f"🔧 Глобальные: /config (в ЛС боту)",
        parse_mode="HTML")


# ══════════════════════════════════════════════
#  ⚔️ INTERACTIVE DUELS
# ══════════════════════════════════════════════

def _fight_key(chat_id, p1_id, p2_id):
    return f"fight:{chat_id}:{min(p1_id, p2_id)}:{max(p1_id, p2_id)}"


def _build_action_kb(fight_key, round_num):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎯 Прицел", callback_data=f"fa:{fight_key}:{round_num}:aim"),
        InlineKeyboardButton("💨 Сбить", callback_data=f"fa:{fight_key}:{round_num}:disrupt"),
        InlineKeyboardButton("🔫 Выстрел", callback_data=f"fa:{fight_key}:{round_num}:shoot"),
    ]])


def _render_status(fight):
    p1, p2 = fight["p1"], fight["p2"]
    # Duel settings are read dynamically so /config changes apply
    # without restarting the bot.
    max_rounds = DUEL_MAX_ROUNDS()
    text = (
        f"⚔️ <b>Раунд {fight['round']}/{max_rounds}</b>\n\n"
        f"🔴 {p1['link']} — 🎯 <b>{p1['aim']}%</b>"
        f" {'✅' if p1['chose'] else '⏳'}\n"
        f"🔵 {p2['link']} — 🎯 <b>{p2['aim']}%</b>"
        f" {'✅' if p2['chose'] else '⏳'}\n"
    )
    if fight["log"]:
        text += "\n" + "\n".join(fight["log"])
    return text


async def _start_round(fight, context):
    p1, p2 = fight["p1"], fight["p2"]
    p1["chose"] = p2["chose"] = False
    p1["action"] = p2["action"] = None

    text = _render_status(fight) + "\n\n⬇️ <b>Выберите действие!</b>"
    kb = _build_action_kb(fight["key"], fight["round"])

    try:
        if fight.get("message_id"):
            await context.bot.edit_message_text(
                text, chat_id=fight["chat_id"],
                message_id=fight["message_id"],
                parse_mode="HTML", reply_markup=kb)
        else:
            msg = await context.bot.send_message(
                fight["chat_id"], text, parse_mode="HTML", reply_markup=kb)
            fight["message_id"] = msg.message_id
    except Exception as e:
        log.error("Start round: %s", e)

    turn_timeout = DUEL_TURN_TIMEOUT()
    context.job_queue.run_once(
        _turn_timeout, turn_timeout,
        data={"key": fight["key"], "round": fight["round"]},
        name=f"ft_{fight['key']}_{fight['round']}")


async def _turn_timeout(context):
    d = context.job.data
    fight = active_fights.get(d["key"])
    if not fight or fight["round"] != d["round"]:
        return
    for p in [fight["p1"], fight["p2"]]:
        if not p["chose"]:
            p["action"] = random.choice(["aim", "disrupt", "shoot"])
            p["chose"] = True
    await _process_round(fight, context)


def _process_actions(fight):
    p1, p2 = fight["p1"], fight["p2"]
    max_rounds = DUEL_MAX_ROUNDS()
    base_aim = DUEL_BASE_AIM()
    aim_step = DUEL_AIM_STEP()

    lines = [f"\n<b>═══ Раунд {fight['round']}/{max_rounds} ═══</b>"]

    for atk, dfn in [(p1, p2), (p2, p1)]:
        if not atk["alive"] or not dfn["alive"]:
            break
        action = atk["action"]
        weapon = random.choice(WEAPONS)

        if action == "aim":
            atk["aim"] = min(95, atk["aim"] + aim_step)
            lines.append(random.choice(AIM_TEXTS).format(name=atk["name"]))

        elif action == "disrupt":
            dfn["aim"] = max(5, dfn["aim"] - aim_step)
            lines.append(random.choice(DISRUPT_TEXTS).format(
                name=atk["name"], target=dfn["name"]))

        elif action == "shoot":
            roll = random.randint(1, 100)/10
            hit = roll <= atk["aim"]
            if hit:
                tmpl = SHOOT_LUCKY_TEXTS if atk["aim"] <= base_aim else SHOOT_HIT_TEXTS
                lines.append(random.choice(tmpl).format(
                    name=atk["name"], weapon=weapon))
                lines.append(random.choice(KILL_TEXTS).format(
                    name=atk["name"], target=dfn["name"]))
                dfn["alive"] = False
            else:
                lines.append(random.choice(SHOOT_MISS_TEXTS).format(
                    name=atk["name"], weapon=weapon, target=dfn["name"]))
            atk["aim"] = base_aim

    if p1["alive"] and p2["alive"]:
        lines.append(
            f"\n📊 Прицел: {p1['name']} <b>{p1['aim']}%</b> | "
            f"{p2['name']} <b>{p2['aim']}%</b>")

    return lines


async def _process_round(fight, context):
    for job in context.job_queue.get_jobs_by_name(
            f"ft_{fight['key']}_{fight['round']}"):
        job.schedule_removal()

    round_lines = _process_actions(fight)
    fight["log"].extend(round_lines)

    p1, p2 = fight["p1"], fight["p2"]
    max_rounds = DUEL_MAX_ROUNDS()
    game_over = not p1["alive"] or not p2["alive"] or fight["round"] >= max_rounds

    if game_over:
        await _finish_duel(fight, context)
    else:
        fight["round"] += 1
        await _start_round(fight, context)


async def _finish_duel(fight, context):
    p1, p2 = fight["p1"], fight["p2"]
    chat_id = fight["chat_id"]
    mute_seconds = DUEL_MUTE_SECONDS()

    if p1["alive"] and not p2["alive"]:
        winner, loser = p1, p2
        is_draw = False
    elif p2["alive"] and not p1["alive"]:
        winner, loser = p2, p1
        is_draw = False
    else:
        winner = loser = None
        is_draw = True

    if is_draw:
        db.record_duel(chat_id, p1["id"], p2["id"], draw=True)
        result = random.choice(DRAW_TEXTS)
    else:
        db.record_duel(chat_id, winner["id"], loser["id"], draw=False)
        result = f"🏆 Победитель: {winner['link']}!"

        if mute_seconds > 0:
            until_date = int(_time.time()) + mute_seconds
            try:
                await context.bot.restrict_chat_member(
                    chat_id, loser["id"],
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=until_date,
                )
                mins = mute_seconds // 60
                secs = mute_seconds % 60
                if mins > 0 and secs > 0:
                    time_str = f"{mins} мин {secs} сек"
                elif mins > 0:
                    time_str = f"{mins} мин"
                else:
                    time_str = f"{secs} сек"
                result += f"\n🔇 {loser['link']} замучен на {time_str}!"
                log.info("Duel mute: user %s in chat %s for %ss",
                         loser["id"], chat_id, mute_seconds)
            except Exception as e:
                log.error("Failed to mute duel loser %s in %s: %s",
                          loser["id"], chat_id, e)
                result += f"\n⚠️ Не удалось замутить {loser['link']} (нет прав?)"

    ws1 = db.get_duel_stats(chat_id, p1["id"])
    ws2 = db.get_duel_stats(chat_id, p2["id"])

    text = f"⚔️ <b>ДУЭЛЬ ЗАВЕРШЕНА</b>\n🔴 {p1['link']} vs 🔵 {p2['link']}\n"
    text += "\n".join(fight["log"])
    text += (
        f"\n\n{'═' * 25}\n{result}\n\n"
        f"📊 {p1['link']}: {ws1['wins']}W/{ws1['losses']}L/{ws1['draws']}D\n"
        f"📊 {p2['link']}: {ws2['wins']}W/{ws2['losses']}L/{ws2['draws']}D")

    try:
        await context.bot.edit_message_text(
            text, chat_id=chat_id, message_id=fight["message_id"], parse_mode="HTML")
    except Exception:
        pass

    active_fights.pop(fight["key"], None)


# ── Challenge ──

async def cmd_duel(update, context):
    msg = update.message
    chat_id = msg.chat.id
    ch = update.effective_user

    if msg.chat.type == "private":
        return await msg.reply_text("⚔️ Только в группах!")
    if not db.are_duels_enabled(chat_id):
        return await msg.reply_text("⚔️ Дуэли отключены.")

    tid, tname = None, None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        tid, tname = u.id, u.first_name
    if not tid and msg.entities:
        for ent in msg.entities:
            if ent.type == "text_mention" and ent.user:
                tid, tname = ent.user.id, ent.user.first_name
                break
            if ent.type == "mention":
                un = msg.text[ent.offset + 1: ent.offset + ent.length]
                row = db.find_by_username(chat_id, un)
                if row:
                    tid, tname = row["user_id"], row["first_name"] or un
                else:
                    return await msg.reply_text(f"❌ @{un} не найден.")
                break

    max_rounds = DUEL_MAX_ROUNDS()
    base_aim = DUEL_BASE_AIM()
    aim_step = DUEL_AIM_STEP()
    duel_timeout = DUEL_TIMEOUT()

    if not tid:
        return await msg.reply_text(
            f"⚔️ <b>Дуэль ({max_rounds} раундов)</b>\n\n"
            "• Ответьте: /duel\n• Или: /duel @username\n\n"
            f"🎯+{aim_step}% / 💨−{aim_step}% / 🔫 выстрел",
            parse_mode="HTML")

    if tid == ch.id:
        return await msg.reply_text("🤦 Нельзя вызвать себя!")
    try:
        tm = await context.bot.get_chat_member(chat_id, tid)
        if tm.user.is_bot:
            return await msg.reply_text("🤖 Нельзя вызвать бота!")
    except Exception:
        pass

    fkey = _fight_key(chat_id, ch.id, tid)
    if fkey in active_fights:
        return await msg.reply_text("⏳ Между вами уже идёт дуэль!")

    ckey = f"ch:{chat_id}:{tid}"
    if ckey in active_challenges:
        return await msg.reply_text("⏳ У этого игрока уже есть вызов!")
    for k, v in list(active_challenges.items()):
        if k.startswith(f"ch:{chat_id}:") and v["challenger_id"] == ch.id:
            return await msg.reply_text("⏳ У вас уже есть вызов!")
    for k in active_fights:
        pts = k.split(":")
        if len(pts) == 4 and pts[1] == str(chat_id):
            if ch.id in (int(pts[2]), int(pts[3])):
                return await msg.reply_text("⏳ Вы уже в дуэли!")
            if tid in (int(pts[2]), int(pts[3])):
                return await msg.reply_text("⏳ Этот игрок уже в дуэли!")

    ch_link = user_link(ch.id, ch.first_name)
    tg_link = user_link(tid, tname)
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚔️ Принять!", callback_data=f"da:{chat_id}:{ch.id}:{tid}"),
        InlineKeyboardButton("🏳️ Отклонить", callback_data=f"dd:{chat_id}:{ch.id}:{tid}"),
    ]])
    sent = await msg.reply_text(
        f"⚔️ {ch_link} вызывает {tg_link}!\n\n"
        f"🎮 <b>{max_rounds} раундов</b> | 🎯 {base_aim}%\n"
        f"⏱ {duel_timeout} сек…",
        reply_markup=kb, parse_mode="HTML")

    # Keep pending challenges in a separate map and auto-expire them by timeout.
    active_challenges[ckey] = {
        "challenger_id": ch.id, "challenger_name": ch.first_name,
        "target_id": tid, "target_name": tname,
        "message_id": sent.message_id,
    }
    context.job_queue.run_once(
        _challenge_timeout, duel_timeout,
        data={"chat_id": chat_id, "key": ckey, "mid": sent.message_id},
        name=f"ct_{ckey}")


async def _challenge_timeout(context):
    d = context.job.data
    ch = active_challenges.pop(d["key"], None)
    if not ch:
        return
    try:
        await context.bot.edit_message_text(
            f"⏰ {user_link(ch['target_id'], ch['target_name'])} не ответил. Отменено.",
            chat_id=d["chat_id"], message_id=d["mid"], parse_mode="HTML")
    except Exception:
        pass


# ── Challenge buttons ──

async def callback_duel_challenge(update, context):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) != 4:
        return await q.answer("❌")
    action, chat_id, ch_id, tg_id = parts[0], int(parts[1]), int(parts[2]), int(parts[3])

    if q.from_user.id != tg_id:
        return await q.answer("❌ Не ваш вызов!", show_alert=True)

    ckey = f"ch:{chat_id}:{tg_id}"
    ch = active_challenges.pop(ckey, None)
    if not ch:
        return await q.answer("⏰ Вызов истёк!", show_alert=True)

    for job in context.job_queue.get_jobs_by_name(f"ct_{ckey}"):
        job.schedule_removal()

    ch_link = user_link(ch_id, ch["challenger_name"])
    tg_link = user_link(tg_id, ch["target_name"])

    if action == "dd":
        await q.edit_message_text(
            f"🏳️ {tg_link} отказался от дуэли с {ch_link}! 🐔", parse_mode="HTML")
        return await q.answer()

    await q.answer("⚔️ Поехали!")
    base_aim = DUEL_BASE_AIM()
    fkey = _fight_key(chat_id, ch_id, tg_id)
    # After acceptance, build full multi-round fight state.
    fight = {
        "key": fkey, "chat_id": chat_id, "round": 1, "message_id": None, "log": [],
        "p1": {
            "id": ch_id, "name": html.escape(ch["challenger_name"]),
            "link": ch_link, "aim": base_aim, "alive": True,
            "chose": False, "action": None,
        },
        "p2": {
            "id": tg_id, "name": html.escape(ch["target_name"]),
            "link": tg_link, "aim": base_aim, "alive": True,
            "chose": False, "action": None,
        },
    }
    active_fights[fkey] = fight
    try:
        await q.edit_message_text(
            f"⚔️ {ch_link} vs {tg_link} — дуэль началась!", parse_mode="HTML")
    except Exception:
        pass
    await _start_round(fight, context)


# ── Action buttons ──

async def callback_fight_action(update, context):
    q = update.callback_query
    parts = q.data.split(":")
    if len(parts) != 7 or parts[0] != "fa":
        return await q.answer("❌")

    fkey = f"{parts[1]}:{parts[2]}:{parts[3]}:{parts[4]}"
    round_num = int(parts[5])
    action = parts[6]

    fight = active_fights.get(fkey)
    if not fight:
        return await q.answer("❌ Дуэль не найдена!", show_alert=True)
    if fight["round"] != round_num:
        return await q.answer("⏳ Раунд завершён!", show_alert=True)

    uid = q.from_user.id
    p1, p2 = fight["p1"], fight["p2"]
    if uid == p1["id"]:
        player = p1
    elif uid == p2["id"]:
        player = p2
    else:
        return await q.answer("❌ Вы не участвуете!", show_alert=True)

    if player["chose"]:
        return await q.answer("✅ Уже выбрано!", show_alert=True)

    player["action"] = action
    player["chose"] = True
    emoji = {"aim": "🎯", "disrupt": "💨", "shoot": "🔫"}
    await q.answer(f"{emoji.get(action)} Принято!")

    try:
        text = _render_status(fight) + "\n\n⬇️ <b>Выберите действие!</b>"
        kb = _build_action_kb(fkey, round_num)
        await context.bot.edit_message_text(
            text, chat_id=fight["chat_id"], message_id=fight["message_id"],
            parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass

    if p1["chose"] and p2["chose"]:
        await _process_round(fight, context)


# ── Admin: disable/enable duels ──

@admin_only
async def cmd_banduel(update, context):
    cid = update.effective_chat.id
    db.set_duels_enabled(cid, False)
    cancelled = 0
    for key in list(active_challenges):
        if key.startswith(f"ch:{cid}:"):
            ch = active_challenges.pop(key)
            cancelled += 1
            for job in context.job_queue.get_jobs_by_name(f"ct_{key}"):
                job.schedule_removal()
            try:
                await context.bot.edit_message_text(
                    "⚔️ Отменено админом.", chat_id=cid, message_id=ch["message_id"])
            except Exception:
                pass
    for key in list(active_fights):
        if f":{cid}:" in key:
            f = active_fights.pop(key)
            cancelled += 1
            try:
                await context.bot.edit_message_text(
                    "⚔️ Прервано админом.", chat_id=cid, message_id=f["message_id"])
            except Exception:
                pass
    t = "⚔️ Дуэли отключены."
    if cancelled:
        t += f"\n🗑 Отменено: {cancelled}"
    await update.message.reply_text(t)

@admin_only
async def cmd_unbanduel(update, context):
    db.set_duels_enabled(update.effective_chat.id, True)
    await update.message.reply_text("⚔️ Дуэли включены!")

# ── Stats ──

async def cmd_duelstats(update, context):
    cid = update.effective_chat.id
    top = db.get_duel_leaderboard(cid, 10)
    if not top:
        return await update.message.reply_text("📊 Дуэлей ещё не было.")
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Топ дуэлянтов:</b>\n"]
    for i, r in enumerate(top):
        m = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        n = html.escape(r["first_name"] or str(r["user_id"]))
        t = r["wins"] + r["losses"] + r["draws"]
        wr = (r["wins"] / t * 100) if t else 0
        lines.append(f"{m} {n} — ✅{r['wins']} ❌{r['losses']} 🤝{r['draws']} ({wr:.0f}%)")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")

async def cmd_myduel(update, context):
    cid = update.effective_chat.id
    uid = update.effective_user.id
    s = db.get_duel_stats(cid, uid)
    t = s["wins"] + s["losses"] + s["draws"]
    if t == 0:
        return await update.message.reply_text("📊 Вы ещё не дрались.")
    wr = s["wins"] / t * 100
    n = html.escape(update.effective_user.first_name)
    await update.message.reply_text(
        f"📊 <b>{n}</b>\n✅{s['wins']} ❌{s['losses']} 🤝{s['draws']}\n"
        f"📈 {wr:.1f}% | 🎮 {t}", parse_mode="HTML")


# ══════════════════════════════════════════════
#  ⭐ REPUTATION
# ══════════════════════════════════════════════

async def cmd_rep(update, context):
    msg = update.message
    cid = msg.chat.id
    voter = update.effective_user
    if msg.chat.type == "private":
        return await msg.reply_text("⭐ Только в группах!")
    args = context.args or []
    if not args or args[0] not in ("+", "-"):
        return await msg.reply_text(
            "⭐ /rep + @ник — повысить\n/rep - @ник — понизить\n"
            "Или ответом: /rep +\n📌 1 раз в день.", parse_mode="HTML")
    delta = 1 if args[0] == "+" else -1
    tid, tname = await resolve_target(update, context)
    if not tid:
        return await msg.reply_text("❌ Укажите пользователя.")
    if tid == voter.id:
        return await msg.reply_text("🙅 Нельзя себе!")
    try:
        tm = await context.bot.get_chat_member(cid, tid)
        if tm.user.is_bot:
            return await msg.reply_text("🤖 Нельзя боту!")
    except Exception:
        pass
    if not db.can_vote_today(cid, voter.id):
        return await msg.reply_text("⏰ Уже голосовали сегодня!")
    db.change_rep(cid, tid, delta)
    db.record_vote(cid, voter.id)
    score = db.get_rep(cid, tid)
    e = "⬆️" if delta > 0 else "⬇️"
    await msg.reply_text(f"{e} {user_link(tid, tname)} — <b>{score:+d}</b>", parse_mode="HTML")

async def cmd_myrep(update, context):
    cid = update.effective_chat.id
    score = db.get_rep(cid, update.effective_user.id)
    n = html.escape(update.effective_user.first_name)
    await update.message.reply_text(f"⭐ <b>{n}</b> — <b>{score:+d}</b>", parse_mode="HTML")

async def cmd_toprep(update, context):
    cid = update.effective_chat.id
    top = db.get_rep_leaderboard(cid, 10)
    if not top:
        return await update.message.reply_text("⭐ Пока пусто.")
    medals = ["🥇", "🥈", "🥉"]
    lines = ["⭐ <b>Топ репутации:</b>\n"]
    for i, r in enumerate(top):
        m = medals[i] if i < 3 else f"<b>{i+1}.</b>"
        n = html.escape(r["first_name"] or str(r["user_id"]))
        lines.append(f"{m} {n} — <b>{r['score']:+d}</b>")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ══════════════════════════════════════════════
#  STARTUP
# ══════════════════════════════════════════════

def main():
    print("=" * 50)
    print("  🤖 Moderator + Interactive Duel Bot")
    print(f"  ⚔️ Настройки через /config в ЛС")
    if OWNER_ID and OWNER_ID != 0:
        print(f"  👑 Owner ID: {OWNER_ID}")
    else:
        print("  ⚠️  OWNER_ID не задан в config.py!")
    print("=" * 50)

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    # Job queue is used for challenge timeouts and deferred actions.
    app = Application.builder().token(BOT_TOKEN).build()

    # Core commands
    app.add_handler(CommandHandler("start", cmd_help))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("lock", cmd_lock))
    app.add_handler(CommandHandler("unlock", cmd_unlock))
    app.add_handler(CommandHandler("lockmedia", cmd_lockmedia))
    app.add_handler(CommandHandler("unlockmedia", cmd_unlockmedia))
    app.add_handler(CommandHandler("lockpin", cmd_lockpin))
    app.add_handler(CommandHandler("unlockpin", cmd_unlockpin))
    app.add_handler(CommandHandler("mute", cmd_mute))
    app.add_handler(CommandHandler("unmute", cmd_unmute))
    app.add_handler(CommandHandler("kick", cmd_kick))
    app.add_handler(CommandHandler("ban", cmd_ban))
    app.add_handler(CommandHandler("unban", cmd_unban))
    app.add_handler(CommandHandler("warn", cmd_warn))
    app.add_handler(CommandHandler("resetwarns", cmd_resetwarns))
    app.add_handler(CommandHandler("pending", cmd_pending))
    app.add_handler(CommandHandler("settings", cmd_settings))

    # Duels
    app.add_handler(CommandHandler("duel", cmd_duel))
    app.add_handler(CommandHandler("duelstats", cmd_duelstats))
    app.add_handler(CommandHandler("topduel", cmd_duelstats))
    app.add_handler(CommandHandler("myduel", cmd_myduel))
    app.add_handler(CommandHandler("banduel", cmd_banduel))
    app.add_handler(CommandHandler("unbanduel", cmd_unbanduel))

    # Reputation
    app.add_handler(CommandHandler("rep", cmd_rep))
    app.add_handler(CommandHandler("myrep", cmd_myrep))
    app.add_handler(CommandHandler("toprep", cmd_toprep))

    # Private settings
    app.add_handler(CommandHandler("config", cmd_config))
    app.add_handler(CommandHandler("addadmin", cmd_addadmin))
    app.add_handler(CommandHandler("removeadmin", cmd_removeadmin))
    app.add_handler(CommandHandler("admins", cmd_admins))

    # Events
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, on_new_member))
    app.add_handler(ChatMemberHandler(on_chat_member_update, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, on_left_member))

    # Callback buttons
    app.add_handler(CallbackQueryHandler(callback_moderation, pattern=r"^(approve|ban):"))
    app.add_handler(CallbackQueryHandler(callback_duel_challenge, pattern=r"^(da|dd):"))
    app.add_handler(CallbackQueryHandler(callback_fight_action, pattern=r"^fa:"))
    app.add_handler(CallbackQueryHandler(callback_config, pattern=r"^cfg_"))

    # Settings value input (private chat, plain text only, no commands)
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
        handle_setting_value), group=0)

    # Message tracking
    app.add_handler(MessageHandler(filters.ALL, track_messages), group=1)

    print(f"\n🚀 Бот запущен!\n")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
