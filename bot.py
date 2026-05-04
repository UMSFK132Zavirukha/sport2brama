import logging
import os
from datetime import datetime, timedelta, time
from typing import List
import pytz
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # на Render/Railway змінні задані через dashboard
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from google_calendar import CalendarService

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Конфіг ---
BOT_TOKEN = os.environ["BOT_TOKEN"]
GROUP_ID = os.environ["GROUP_ID"]              # наприклад -1001234567890
TOPIC_ID = int(os.environ["TOPIC_ID"])         # ID гілки (message_thread_id)
CALENDAR_ID = os.environ["CALENDAR_ID"]        # наприклад abc@group.calendar.google.com
TIMEZONE = pytz.timezone("Europe/Kiev")

# Робочі години майданчику (можна змінювати в .env)
WORK_START = int(os.environ.get("WORK_START", 8))
WORK_END = int(os.environ.get("WORK_END", 21))
SLOT_DURATION = int(os.environ.get("SLOT_DURATION", 1))

# Стани розмови
SELECT_DATE, SELECT_TIME, CONFIRM = range(3)


calendar_service = CalendarService(CALENDAR_ID, TIMEZONE)


# ─── HELPERS ───────────────────────────────────────────────────────────────

def get_date_keyboard(offset_days: int = 0) -> InlineKeyboardMarkup:
    """Клавіатура вибору дати (14 днів вперед)."""
    today = datetime.now(TIMEZONE).date()
    buttons = []
    row = []
    for i in range(14):
        d = today + timedelta(days=i + offset_days)
        label = d.strftime("%d.%m") + (" (сьогодні)" if i == 0 else "")
        row.append(InlineKeyboardButton(label, callback_data=f"date_{d.isoformat()}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Скасувати", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


def get_time_keyboard(date_str: str, busy_slots: List[str]) -> InlineKeyboardMarkup:
    """Клавіатура вибору часу з позначенням зайнятих слотів."""
    buttons = []
    row = []
    for hour in range(WORK_START, WORK_END):
        slot = f"{hour:02d}:00"
        if slot in busy_slots:
            label = f"🔴 {slot}"
            cb = "busy"
        else:
            label = f"🟢 {slot}"
            cb = f"time_{date_str}_{slot}"
        row.append(InlineKeyboardButton(label, callback_data=cb))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("⬅️ Назад", callback_data="back_to_date"),
                    InlineKeyboardButton("❌ Скасувати", callback_data="cancel")])
    return InlineKeyboardMarkup(buttons)


async def notify_channel(context: ContextTypes.DEFAULT_TYPE, text: str):
    """Надсилає повідомлення в гілку (topic) групи."""
    await context.bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=TOPIC_ID,
        text=text,
        parse_mode="HTML"
    )


# ─── КОМАНДИ ───────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 <b>Бот бронювання спортивного майданчику</b>\n\n"
        "Що бажаєте зробити?\n\n"
        "/book — забронювати час\n"
        "/mybookings — мої бронювання\n"
        "/check — перевірити зайнятість на дату\n"
        "/cancel_booking — скасувати бронювання"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 Виберіть дату бронювання:",
        reply_markup=get_date_keyboard()
    )
    return SELECT_DATE


async def date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ Бронювання скасовано.")
        return ConversationHandler.END

    date_str = query.data.replace("date_", "")
    context.user_data["booking_date"] = date_str

    busy = calendar_service.get_busy_slots(date_str)
    context.user_data["busy_slots"] = busy

    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    free_count = (WORK_END - WORK_START) - len(busy)

    await query.edit_message_text(
        f"📅 <b>{date_display}</b>\n"
        f"🟢 Вільних слотів: {free_count}  🔴 Зайнятих: {len(busy)}\n\n"
        "Виберіть час:",
        parse_mode="HTML",
        reply_markup=get_time_keyboard(date_str, busy)
    )
    return SELECT_TIME


async def time_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "busy":
        await query.answer("⛔️ Цей час вже зайнятий!", show_alert=True)
        return SELECT_TIME

    if query.data == "back_to_date":
        await query.edit_message_text(
            "📅 Виберіть дату бронювання:",
            reply_markup=get_date_keyboard()
        )
        return SELECT_DATE

    if query.data == "cancel":
        await query.edit_message_text("❌ Бронювання скасовано.")
        return ConversationHandler.END

    _, date_str, time_str = query.data.split("_", 2)
    context.user_data["booking_time"] = time_str

    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    user_name = update.effective_user.full_name

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Підтвердити", callback_data="confirm"),
         InlineKeyboardButton("❌ Скасувати", callback_data="cancel")]
    ])

    await query.edit_message_text(
        f"📋 <b>Підтвердження бронювання</b>\n\n"
        f"👤 Ім'я: {user_name}\n"
        f"📅 Дата: {date_display}\n"
        f"⏰ Час: {time_str} – {int(time_str[:2])+1:02d}:00\n\n"
        "Підтвердити?",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    return CONFIRM


async def confirm_booking(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("❌ Бронювання скасовано.")
        return ConversationHandler.END

    user = update.effective_user
    date_str = context.user_data["booking_date"]
    time_str = context.user_data["booking_time"]
    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    hour = int(time_str[:2])

    event_id = calendar_service.create_booking(
        date_str=date_str,
        hour=hour,
        user_id=str(user.id),
        user_name=user.full_name
    )

    if event_id:
        await query.edit_message_text(
            f"✅ <b>Бронювання підтверджено!</b>\n\n"
            f"📅 {date_display} о {time_str}\n"
            f"ID: <code>{event_id[:8]}</code>\n\n"
            "Для скасування використайте /cancel_booking",
            parse_mode="HTML"
        )
        await notify_channel(
            context,
            f"🔴 <b>Зайнято!</b> {date_display} о {time_str} — заброньовано"
        )
    else:
        await query.edit_message_text("⚠️ Помилка бронювання. Спробуйте ще раз.")

    return ConversationHandler.END


async def my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    bookings = calendar_service.get_user_bookings(user_id)

    if not bookings:
        await update.message.reply_text("У вас немає активних бронювань.")
        return

    text = "📋 <b>Ваші бронювання:</b>\n\n"
    for b in bookings:
        text += f"• {b['date_display']} о {b['time']} (ID: <code>{b['event_id'][:8]}</code>)\n"
    await update.message.reply_text(text, parse_mode="HTML")


async def cancel_booking_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    bookings = calendar_service.get_user_bookings(user_id)

    if not bookings:
        await update.message.reply_text("У вас немає активних бронювань.")
        return

    buttons = []
    for b in bookings:
        label = f"{b['date_display']} о {b['time']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"del_{b['event_id']}")])
    buttons.append([InlineKeyboardButton("❌ Закрити", callback_data="close")])

    await update.message.reply_text(
        "Виберіть бронювання для скасування:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def cancel_booking_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "close":
        await query.edit_message_text("Закрито.")
        return

    event_id = query.data.replace("del_", "")
    event_info = calendar_service.get_event_info(event_id)
    success = calendar_service.delete_booking(event_id)

    if success and event_info:
        await query.edit_message_text(
            f"✅ Бронювання <b>{event_info['date_display']} о {event_info['time']}</b> скасовано.",
            parse_mode="HTML"
        )
        await notify_channel(
            context,
            f"🟢 <b>Вільно!</b> {event_info['date_display']} о {event_info['time']} — бронювання скасовано"
        )
    else:
        await query.edit_message_text("⚠️ Не вдалося скасувати. Спробуйте ще раз.")


async def check_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показує зайнятість на конкретну дату. Використання: /check 05.05.2026"""
    args = context.args
    if not args:
        await update.message.reply_text("Використання: /check 05.05.2026")
        return
    try:
        date_obj = datetime.strptime(args[0], "%d.%m.%Y")
        date_str = date_obj.strftime("%Y-%m-%d")
        date_display = args[0]
    except ValueError:
        await update.message.reply_text("Неправильний формат дати. Використовуйте: 05.05.2026")
        return

    busy = calendar_service.get_busy_slots(date_str)
    free = [f"{h:02d}:00" for h in range(WORK_START, WORK_END) if f"{h:02d}:00" not in busy]

    text = f"📅 <b>{date_display}</b>\n\n"
    if free:
        text += "🟢 <b>Вільні слоти:</b>\n" + ", ".join(free) + "\n\n"
    if busy:
        text += "🔴 <b>Зайняті слоти:</b>\n" + ", ".join(busy)
    if not free and not busy:
        text += "Немає даних на цю дату."

    await update.message.reply_text(text, parse_mode="HTML")


# ─── MAIN ──────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    booking_conv = ConversationHandler(
        entry_points=[CommandHandler("book", book_start)],
        states={
            SELECT_DATE: [CallbackQueryHandler(date_selected)],
            SELECT_TIME: [CallbackQueryHandler(time_selected)],
            CONFIRM: [CallbackQueryHandler(confirm_booking)],
        },
        fallbacks=[CommandHandler("start", start)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(booking_conv)
    app.add_handler(CommandHandler("mybookings", my_bookings))
    app.add_handler(CommandHandler("check", check_date))
    app.add_handler(CommandHandler("cancel_booking", cancel_booking_start))
    app.add_handler(CallbackQueryHandler(cancel_booking_callback, pattern="^del_|^close$"))

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
