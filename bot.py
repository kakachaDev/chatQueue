#!/usr/bin/env python3
"""
Бот канала "ubi."

/posts — карточки постов на завтра. Всё взаимодействие происходит внутри
         одного сообщения на пост — никаких дополнительных сообщений.

Состояния карточки:
  normal   → заголовок + blockquote + кнопки действий
  editing  → заголовок + текущий текст/время + инструкция + [❌ Отменить]

Публикация в канал — в назначенное время или кнопкой "Сейчас".
"""

import json
import logging
import os
import sys
from datetime import date, datetime, time as dtime, timedelta
from html import escape
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

BASE_DIR = Path(__file__).parent
POSTS_FILE = BASE_DIR / "posts.json"
STATE_FILE = BASE_DIR / "state.json"
CONFIG_FILE = BASE_DIR / "config.json"
LOG_FILE = BASE_DIR / "bot.log"
PID_FILE = BASE_DIR / "bot.pid"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

# Логирование: ротируемый файл (5 МБ × 3 файла)
_fmt = logging.Formatter("%(asctime)s  %(levelname)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
_file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_file_handler.setFormatter(_fmt)
logging.basicConfig(level=logging.INFO, handlers=[_file_handler])
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Конфиг
# ---------------------------------------------------------------------------

def load_config() -> dict:
    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8")) if CONFIG_FILE.exists() else {}

    raw_start = os.getenv("START_DATE") or cfg.get("start_date", "")
    if not raw_start:
        raise ValueError("start_date не задан в config.json или START_DATE")

    admin_id = os.getenv("ADMIN_USER_ID") or cfg.get("admin_user_id")
    if not admin_id:
        raise ValueError("admin_user_id не задан в config.json или ADMIN_USER_ID")

    reminder_time = cfg.get("reminder_time", "21:00")
    reminder_h, reminder_m = map(int, reminder_time.split(":"))

    return {
        "bot_token": os.getenv("BOT_TOKEN") or cfg.get("bot_token", ""),
        "channel_id": os.getenv("CHANNEL_ID") or cfg.get("channel_id", ""),
        "admin_user_id": int(admin_id),
        "start_date": date.fromisoformat(raw_start),
        "reminder_hour": reminder_h,
        "reminder_minute": reminder_m,
    }


# ---------------------------------------------------------------------------
# Состояние (персистентное)
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"posts": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def post_key(day: int, time_str: str) -> str:
    return f"day_{day}_{time_str}"


# ---------------------------------------------------------------------------
# Форматирование
# ---------------------------------------------------------------------------

STATUS_LABELS = {
    "pending":   "⏳ Ожидает",
    "approved":  "✅ Одобрен",
    "published": "📢 Опубликован",
    "skipped":   "⏭ Пропущен",
}


def get_publish_html(post_data: dict) -> str:
    """HTML текста для публикации в канал."""
    return post_data.get("edited_html") or escape(post_data["text"])


def _header(post_data: dict) -> str:
    time_str = post_data.get("edited_time") or post_data["time"]
    status = STATUS_LABELS.get(post_data["status"], post_data["status"])
    return (
        f"📅 <b>{escape(post_data['date'])}</b>  "
        f"🕐 <b>{escape(time_str)} МСК</b>\n"
        f"{escape(status)}"
    )


def fmt_normal(post_data: dict) -> str:
    """Карточка в обычном состоянии."""
    return f"{_header(post_data)}\n\n<blockquote>{get_publish_html(post_data)}</blockquote>"


def fmt_edit_text(post_data: dict) -> str:
    """Карточка в режиме редактирования текста.
    Текст БЕЗ blockquote — чтобы можно было скопировать без лишней разметки.
    """
    return (
        f"{_header(post_data)}\n\n"
        f"✏️ <b>Редактирование текста</b>\n\n"
        f"{get_publish_html(post_data)}\n\n"
        f"<i>Пришли новый текст. Форматирование Telegram сохранится.</i>"
    )


def fmt_edit_time(post_data: dict, error: str = "") -> str:
    """Карточка в режиме редактирования времени."""
    err_line = f"\n\n⚠️ {escape(error)}" if error else ""
    return (
        f"{_header(post_data)}\n\n"
        f"🕐 <b>Редактирование времени</b>\n\n"
        f"Пришли новое время (ЧЧ:ММ, московское):{err_line}"
    )


# ---------------------------------------------------------------------------
# Клавиатуры
# ---------------------------------------------------------------------------

def kb_normal(key: str, status: str) -> InlineKeyboardMarkup:
    if status == "pending":
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ Текст",      callback_data=f"edit_text:{key}"),
                InlineKeyboardButton("🕐 Время",      callback_data=f"edit_time:{key}"),
            ],
            [
                InlineKeyboardButton("✅ Одобрить",   callback_data=f"approve:{key}"),
                InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip:{key}"),
            ],
        ])
    elif status == "approved":
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Опубликовать сейчас", callback_data=f"publish_now:{key}")],
            [InlineKeyboardButton("↩️ Вернуть в ожидание", callback_data=f"unapprove:{key}")],
        ])
    elif status == "skipped":
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ Вернуть в ожидание", callback_data=f"unapprove:{key}"),
        ]])
    else:
        return InlineKeyboardMarkup([[]])


def kb_cancel(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ Отменить", callback_data=f"cancel:{key}"),
    ]])


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

async def try_delete(bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass


async def restore_card(bot, cfg: dict, post_data: dict, key: str) -> None:
    """Возвращает карточку в нормальное состояние."""
    if not post_data.get("tg_message_id"):
        return
    try:
        await bot.edit_message_text(
            chat_id=cfg["admin_user_id"],
            message_id=post_data["tg_message_id"],
            text=fmt_normal(post_data),
            parse_mode="HTML",
            reply_markup=kb_normal(key, post_data["status"]),
        )
    except Exception as e:
        log.warning("restore_card failed: %s", e)


# ---------------------------------------------------------------------------
# /posts — карточки постов на завтра
# ---------------------------------------------------------------------------

async def cmd_posts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: dict = context.bot_data["cfg"]
    if update.effective_user.id != cfg["admin_user_id"]:
        return

    schedule: list = context.bot_data["schedule"]
    state: dict = context.bot_data["state"]

    now_msk = datetime.now(tz=MOSCOW_TZ)
    tomorrow = (now_msk + timedelta(days=1)).date()
    day_number = (tomorrow - cfg["start_date"]).days + 1

    await try_delete(context.bot, cfg["admin_user_id"], update.message.message_id)

    if day_number < 1:
        await context.bot.send_message(
            chat_id=cfg["admin_user_id"],
            text=f"Расписание начинается с {cfg['start_date']}.",
        )
        return

    tomorrow_posts = [p for p in schedule if p["day"] == day_number]
    if not tomorrow_posts:
        await context.bot.send_message(
            chat_id=cfg["admin_user_id"],
            text=f"Постов на {tomorrow} нет.",
        )
        return

    # Сбрасываем активную сессию редактирования если есть
    editing_sessions.pop(cfg["admin_user_id"], None)

    for post in sorted(tomorrow_posts, key=lambda p: p["time"]):
        key = post_key(post["day"], post["time"])

        if key not in state["posts"]:
            state["posts"][key] = {
                "day": post["day"],
                "date": str(tomorrow),
                "time": post["time"],
                "text": post["text"],
                "edited_html": None,
                "edited_time": None,
                "status": "pending",
                "tg_message_id": None,
            }

        post_data = state["posts"][key]

        # Удаляем старую карточку — пришлём свежую внизу
        if post_data.get("tg_message_id"):
            await try_delete(context.bot, cfg["admin_user_id"], post_data["tg_message_id"])
            post_data["tg_message_id"] = None

        msg = await context.bot.send_message(
            chat_id=cfg["admin_user_id"],
            text=fmt_normal(post_data),
            parse_mode="HTML",
            reply_markup=kb_normal(key, post_data["status"]),
        )
        post_data["tg_message_id"] = msg.message_id
        save_state(state)


# ---------------------------------------------------------------------------
# Публикация одобренных постов по расписанию
# ---------------------------------------------------------------------------

async def publish_due_posts(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: dict = context.bot_data["cfg"]
    state: dict = context.bot_data["state"]
    now_msk = datetime.now(tz=MOSCOW_TZ)

    for key, post_data in list(state["posts"].items()):
        if post_data["status"] != "approved":
            continue

        target_date = date.fromisoformat(post_data["date"])
        time_str = post_data.get("edited_time") or post_data["time"]
        h, m = map(int, time_str.split(":"))
        publish_dt = datetime(target_date.year, target_date.month, target_date.day,
                              h, m, tzinfo=MOSCOW_TZ)
        if now_msk < publish_dt:
            continue

        try:
            await context.bot.send_message(
                chat_id=cfg["channel_id"],
                text=get_publish_html(post_data),
                parse_mode="HTML",
            )
            post_data["status"] = "published"
            save_state(state)
            log.info("Опубликован пост %s.", key)

            if post_data.get("tg_message_id"):
                await context.bot.edit_message_text(
                    chat_id=cfg["admin_user_id"],
                    message_id=post_data["tg_message_id"],
                    text=fmt_normal(post_data),
                    parse_mode="HTML",
                    reply_markup=kb_normal(key, "published"),
                )
        except Exception as e:
            log.error("Ошибка публикации поста %s: %s", key, e)


# ---------------------------------------------------------------------------
# Напоминание о непроверенных постах
# ---------------------------------------------------------------------------

async def remind_pending_posts(context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg: dict = context.bot_data["cfg"]
    state: dict = context.bot_data["state"]
    tomorrow = (datetime.now(tz=MOSCOW_TZ) + timedelta(days=1)).date()

    pending = [
        p for p in state["posts"].values()
        if p.get("date") == str(tomorrow) and p["status"] == "pending"
    ]
    if not pending:
        return

    times = ", ".join(
        p.get("edited_time") or p["time"]
        for p in sorted(pending, key=lambda x: x.get("edited_time") or x["time"])
    )
    await context.bot.send_message(
        chat_id=cfg["admin_user_id"],
        text=(
            f"⚠️ <b>Не одобрены посты на {tomorrow}:</b> {escape(times)}\n\n"
            f"Используй /posts чтобы их просмотреть."
        ),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Активные сессии редактирования: user_id → {"key": str, "mode": "text"|"time"}
# ---------------------------------------------------------------------------

editing_sessions: dict = {}


# ---------------------------------------------------------------------------
# Обработчик кнопок
# ---------------------------------------------------------------------------

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    state: dict = context.bot_data["state"]
    cfg: dict = context.bot_data["cfg"]
    user_id = query.from_user.id
    action, key = query.data.split(":", 1)
    post_data = state["posts"].get(key)

    if not post_data:
        await query.answer("Пост не найден.", show_alert=True)
        return

    # --- Одобрить ---
    if action == "approve":
        post_data["status"] = "approved"
        save_state(state)
        editing_sessions.pop(user_id, None)
        await query.edit_message_text(
            text=fmt_normal(post_data),
            parse_mode="HTML",
            reply_markup=kb_normal(key, "approved"),
        )

    # --- Вернуть в ожидание ---
    elif action == "unapprove":
        post_data["status"] = "pending"
        save_state(state)
        await query.edit_message_text(
            text=fmt_normal(post_data),
            parse_mode="HTML",
            reply_markup=kb_normal(key, "pending"),
        )

    # --- Пропустить ---
    elif action == "skip":
        post_data["status"] = "skipped"
        save_state(state)
        editing_sessions.pop(user_id, None)
        await query.edit_message_text(
            text=fmt_normal(post_data),
            parse_mode="HTML",
            reply_markup=kb_normal(key, "skipped"),
        )

    # --- Опубликовать сейчас ---
    elif action == "publish_now":
        try:
            await context.bot.send_message(
                chat_id=cfg["channel_id"],
                text=get_publish_html(post_data),
                parse_mode="HTML",
            )
            post_data["status"] = "published"
            save_state(state)
            editing_sessions.pop(user_id, None)
            await query.edit_message_text(
                text=fmt_normal(post_data),
                parse_mode="HTML",
                reply_markup=kb_normal(key, "published"),
            )
            log.info("Пост %s опубликован вручную.", key)
        except Exception as e:
            log.error("Ошибка немедленной публикации %s: %s", key, e)
            await query.answer(f"Ошибка: {e}", show_alert=True)

    # --- Редактировать текст ---
    elif action == "edit_text":
        # Если редактировали другой пост — восстановить его карточку
        existing = editing_sessions.get(user_id)
        if existing and existing["key"] != key:
            old = state["posts"].get(existing["key"])
            if old:
                await restore_card(context.bot, cfg, old, existing["key"])

        editing_sessions[user_id] = {"key": key, "mode": "text"}
        await query.edit_message_text(
            text=fmt_edit_text(post_data),
            parse_mode="HTML",
            reply_markup=kb_cancel(key),
        )

    # --- Редактировать время ---
    elif action == "edit_time":
        existing = editing_sessions.get(user_id)
        if existing and existing["key"] != key:
            old = state["posts"].get(existing["key"])
            if old:
                await restore_card(context.bot, cfg, old, existing["key"])

        editing_sessions[user_id] = {"key": key, "mode": "time"}
        await query.edit_message_text(
            text=fmt_edit_time(post_data),
            parse_mode="HTML",
            reply_markup=kb_cancel(key),
        )

    # --- Отменить редактирование ---
    elif action == "cancel":
        editing_sessions.pop(user_id, None)
        await query.edit_message_text(
            text=fmt_normal(post_data),
            parse_mode="HTML",
            reply_markup=kb_normal(key, post_data["status"]),
        )


# ---------------------------------------------------------------------------
# Обработчик текстовых сообщений (ввод при редактировании)
# ---------------------------------------------------------------------------

async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    cfg: dict = context.bot_data["cfg"]

    if user_id != cfg["admin_user_id"]:
        return

    session = editing_sessions.get(user_id)
    if not session:
        return

    state: dict = context.bot_data["state"]
    key = session["key"]
    mode = session["mode"]
    post_data = state["posts"].get(key)

    # Сразу удаляем сообщение пользователя
    await try_delete(context.bot, cfg["admin_user_id"], update.message.message_id)

    if not post_data:
        editing_sessions.pop(user_id, None)
        return

    if mode == "text":
        post_data["edited_html"] = update.message.text_html
        save_state(state)
        editing_sessions.pop(user_id, None)
        await restore_card(context.bot, cfg, post_data, key)

    elif mode == "time":
        raw = update.message.text.strip()
        try:
            parts = raw.split(":")
            assert len(parts) == 2
            h, m = int(parts[0]), int(parts[1])
            assert 0 <= h <= 23 and 0 <= m <= 59
        except (AssertionError, ValueError):
            # Показываем ошибку прямо в карточке, не выходим из режима редактирования
            if post_data.get("tg_message_id"):
                try:
                    await context.bot.edit_message_text(
                        chat_id=cfg["admin_user_id"],
                        message_id=post_data["tg_message_id"],
                        text=fmt_edit_time(
                            post_data,
                            error=f"«{escape(raw)}» — неверный формат. Нужно ЧЧ:ММ, например 14:30",
                        ),
                        parse_mode="HTML",
                        reply_markup=kb_cancel(key),
                    )
                except Exception as e:
                    log.warning("Не удалось показать ошибку времени: %s", e)
            return

        post_data["edited_time"] = f"{h:02d}:{m:02d}"
        save_state(state)
        editing_sessions.pop(user_id, None)
        await restore_card(context.bot, cfg, post_data, key)


# ---------------------------------------------------------------------------
# Запуск
# ---------------------------------------------------------------------------

def _acquire_pid_lock() -> None:
    """Записывает PID в bot.pid. Завершается, если другой экземпляр уже запущен."""
    if PID_FILE.exists():
        old_pid = int(PID_FILE.read_text().strip())
        try:
            os.kill(old_pid, 0)
            log.error("Уже запущен другой экземпляр (PID %d). Выход.", old_pid)
            sys.exit(1)
        except ProcessLookupError:
            pass  # устаревший PID-файл — перезапишем
    PID_FILE.write_text(str(os.getpid()))


def main() -> None:
    _acquire_pid_lock()
    cfg = load_config()
    posts_data = json.loads(POSTS_FILE.read_text(encoding="utf-8"))
    state = load_state()

    app = Application.builder().token(cfg["bot_token"]).build()
    app.bot_data["cfg"] = cfg
    app.bot_data["schedule"] = posts_data["schedule"]
    app.bot_data["state"] = state

    app.add_handler(CommandHandler("posts", cmd_posts))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    jq = app.job_queue
    reminder_utc = dtime(
        hour=(cfg["reminder_hour"] - 3) % 24,
        minute=cfg["reminder_minute"],
        tzinfo=ZoneInfo("UTC"),
    )
    jq.run_daily(remind_pending_posts, time=reminder_utc, name="daily_reminder")
    jq.run_repeating(publish_due_posts, interval=30, first=5, name="publish_checker")

    log.info("Бот запущен (PID %d). Напоминание в %02d:%02d МСК.",
             os.getpid(), cfg["reminder_hour"], cfg["reminder_minute"])
    try:
        app.run_polling(drop_pending_updates=True)
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
