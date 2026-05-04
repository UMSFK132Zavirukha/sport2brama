import logging
import os
from datetime import datetime, timedelta
from typing import List
import pytz
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton,
)
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
BOT_TOKEN   = os.environ["BOT_TOKEN"]
GROUP_ID    = os.environ["GROUP_ID"]
TOPIC_ID    = int(os.environ["TOPIC_ID"])
CALENDAR_ID = os.environ["CALENDAR_ID"]
TIMEZONE    = pytz.timezone("Europe/Kiev")

WORK_START    = int(os.environ.get("WORK_START", 8))
WORK_END      = int(os.environ.get("WORK_END", 21))
SLOT_DURATION = int(os.environ.get("SLOT_DURATION", 1))

# Стани ConversationHandler
(
    BOOK_SELECT_DATE, BOOK_SELECT_TIME, BOOK_CONFIRM,
    CHECK_SELECT_DATE,
    CANCEL_SELECT,
) = range(5)

# Тексти кнопок головного меню
BTN_BOOK   = "📅 Забронювати"
BTN_CHECK  = "🔍 Перевірити зайнятість"
BTN_MY     = "📋 Мої бронювання"
BTN_CANCEL = "❌ Скасувати бронювання"

calendar_service = CalendarService(CALENDAR_ID, TIMEZONE)


# ─── ГОЛОВНЕ МЕНЮ ──────────────────────────────────────────────────────────

def main_menu() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(BTN_BOOK),  KeyboardButton(BTN_CHECK)],
        [KeyboardButton(BTN_MY),    KeyboardButton(BTN_CANCEL)],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 <b>Бот бронювання спортивного майданчику</b>\n\n"
        "Оберіть дію з меню 👇",
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# ─── INLINE-КЛАВІАТУРИ ─────────────────────────────────────────────────────

def date_keyboard(prefix: str) -> InlineKeyboardMarkup:
    today = datetime.now(TIMEZONE).date()
    buttons, row = [], []
    for i in range(14):
        d = today + timedelta(days=i)
        label = d.strftime("%d.%m") + (" 〔сьогодні〕" if i == 0 else "")
        row.append(InlineKeyboardButton(label, callback_data=f"{prefix}{d.isoformat()}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def time_keyboard(date_str: str, busy_slots: List[str]) -> InlineKeyboardMarkup:
    buttons, row = [], []
    for hour in range(WORK_START, WORK_END):
        slot = f"{hour:02d}:00"
        if slot in busy_slots:
            label, cb = f"🔴 {slot}", "busy"
        else:
            label, cb = f"🟢 {slot}", f"time_{date_str}_{slot}"
        row.append(InlineKeyboardButton(label, callback_data=cb))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([
        InlineKeyboardButton("⬅️ Назад",  callback_data="back_to_date"),
        InlineKeyboardButton("🏠 Меню",   callback_data="main_menu"),
    ])
    return InlineKeyboardMarkup(buttons)


async def notify_group(context: ContextTypes.DEFAULT_TYPE, text: str):
    await context.bot.send_message(
        chat_id=GROUP_ID,
        message_thread_id=TOPIC_ID,
        text=text,
        parse_mode="HTML"
    )


async def go_main_menu(query, context):
    await query.edit_message_text("Оберіть дію 👇")
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Головне меню:",
        reply_markup=main_menu()
    )


# ─── БРОНЮВАННЯ ────────────────────────────────────────────────────────────

async def book_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📅 Виберіть дату бронювання:",
        reply_markup=date_keyboard("book_date_")
    )
    return BOOK_SELECT_DATE


async def book_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        await go_main_menu(query, context)
        return ConversationHandler.END

    date_str = query.data.replace("book_date_", "")
    context.user_data["booking_date"] = date_str

    busy = calendar_service.get_busy_slots(date_str)
    context.user_data["busy_slots"] = busy

    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    free_count = (WORK_END - WORK_START) - len(busy)

    await query.edit_message_text(
        f"📅 <b>{date_display}</b>\n"
        f"🟢 Вільних: {free_count}  🔴 Зайнятих: {len(busy)}\n\n"
        "Виберіть час:",
        parse_mode="HTML",
        reply_markup=time_keyboard(date_str, busy)
    )
    return BOOK_SELECT_TIME


async def book_time_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "busy":
        await query.answer("⛔️ Цей час вже зайнятий!", show_alert=True)
        return BOOK_SELECT_TIME

    if query.data == "back_to_date":
        await query.edit_message_text(
            "📅 Виберіть дату бронювання:",
            reply_markup=date_keyboard("book_date_")
        )
        return BOOK_SELECT_DATE

    if query.data == "main_menu":
        await go_main_menu(query, context)
        return ConversationHandler.END

    _, date_str, time_str = query.data.split("_", 2)
    context.user_data["booking_time"] = time_str
    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")
    end_hour = f"{int(time_str[:2]) + 1:02d}:00"

    await query.edit_message_text(
        f"📋 <b>Підтвердження бронювання</b>\n\n"
        f"👤 {update.effective_user.full_name}\n"
        f"📅 {date_display}\n"
        f"⏰ {time_str} – {end_hour}\n\n"
        "Підтвердити?",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Підтвердити", callback_data="confirm"),
             InlineKeyboardButton("🏠 Меню",        callback_data="main_menu")]
        ])
    )
    return BOOK_CONFIRM


async def book_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        await go_main_menu(query, context)
        return ConversationHandler.END

    user     = update.effective_user
    date_str = context.user_data["booking_date"]
    time_str = context.user_data["booking_time"]
    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")

    event_id = calendar_service.create_booking(
        date_str=date_str,
        hour=int(time_str[:2]),
        user_id=str(user.id),
        user_name=user.full_name
    )

    if event_id:
        await query.edit_message_text(
            f"✅ <b>Бронювання підтверджено!</b>\n\n"
            f"📅 {date_display} о {time_str}\n"
            f"ID: <code>{event_id[:8]}</code>",
            parse_mode="HTML"
        )
        await notify_group(
            context,
            f"🔴 <b>Зайнято!</b> {date_display} о {time_str} — заброньовано ({user.full_name})"
        )
    else:
        await query.edit_message_text("⚠️ Помилка. Спробуйте ще раз.")

    return ConversationHandler.END


# ─── ПЕРЕВІРКА ЗАЙНЯТОСТІ ──────────────────────────────────────────────────

async def check_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔍 Виберіть дату для перевірки:",
        reply_markup=date_keyboard("check_date_")
    )
    return CHECK_SELECT_DATE


async def check_date_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        await go_main_menu(query, context)
        return ConversationHandler.END

    if query.data == "check_again":
        await query.edit_message_text(
            "🔍 Виберіть дату для перевірки:",
            reply_markup=date_keyboard("check_date_")
        )
        return CHECK_SELECT_DATE

    date_str = query.data.replace("check_date_", "")
    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")

    busy = calendar_service.get_busy_slots(date_str)
    free = [f"{h:02d}:00" for h in range(WORK_START, WORK_END)
            if f"{h:02d}:00" not in busy]

    text = f"📅 <b>{date_display}</b>\n\n"
    text += ("🟢 <b>Вільні:</b> " + ", ".join(free) + "\n\n") if free else "🟢 Вільних слотів немає\n\n"
    text += ("🔴 <b>Зайняті:</b> " + ", ".join(busy)) if busy else "🔴 Зайнятих слотів немає"

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔍 Інша дата",    callback_data="check_again"),
             InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")]
        ])
    )
    return CHECK_SELECT_DATE


# ─── МОЇ БРОНЮВАННЯ ────────────────────────────────────────────────────────

async def my_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bookings = calendar_service.get_user_bookings(str(update.effective_user.id))
    if not bookings:
        await update.message.reply_text(
            "У вас немає активних бронювань.",
            reply_markup=main_menu()
        )
        return
    text = "📋 <b>Ваші бронювання:</b>\n\n"
    for b in bookings:
        text += f"• {b['date_display']} о {b['time']}\n"
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_menu())


# ─── СКАСУВАННЯ БРОНЮВАННЯ ─────────────────────────────────────────────────

async def cancel_booking_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bookings = calendar_service.get_user_bookings(str(update.effective_user.id))
    if not bookings:
        await update.message.reply_text(
            "У вас немає активних бронювань.",
            reply_markup=main_menu()
        )
        return ConversationHandler.END

    buttons = [
        [InlineKeyboardButton(
            f"{b['date_display']} о {b['time']}",
            callback_data=f"del_{b['event_id']}"
        )]
        for b in bookings
    ]
    buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])

    await update.message.reply_text(
        "Виберіть бронювання для скасування:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return CANCEL_SELECT


async def cancel_booking_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "main_menu":
        await go_main_menu(query, context)
        return ConversationHandler.END

    event_id   = query.data[4:]  # безпечніше за replace("del_", "")
    event_info = calendar_service.get_event_info(event_id)
    success    = calendar_service.delete_booking(event_id)

    if success and event_info:
        await notify_group(
            context,
            f"🟢 <b>Вільно!</b> {event_info['date_display']} о {event_info['time']} — скасовано"
        )
    else:
        await query.edit_message_text("⚠️ Не вдалося скасувати. Спробуйте ще раз.")
        return ConversationHandler.END

    # Показуємо оновлений список бронювань замість завершення діалогу
    remaining = calendar_service.get_user_bookings(str(update.effective_user.id))
    if not remaining:
        await query.edit_message_text(
            f"✅ Бронювання <b>{event_info['date_display']} о {event_info['time']}</b> скасовано.\n\n"
            "Активних бронювань більше немає.",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    buttons = [
        [InlineKeyboardButton(
            f"{b['date_display']} о {b['time']}",
            callback_data=f"del_{b['event_id']}"
        )]
        for b in remaining
    ]
    buttons.append([InlineKeyboardButton("🏠 Головне меню", callback_data="main_menu")])

    await query.edit_message_text(
        f"✅ Бронювання <b>{event_info['date_display']} о {event_info['time']}</b> скасовано.\n\n"
        "Виберіть ще бронювання для скасування або поверніться в меню:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return CANCEL_SELECT


# ─── MAIN ──────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Fallback просто завершує поточний conversation — далі повідомлення
    # підхоплює відповідний ConversationHandler через свої entry_points
    async def _end_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
        return ConversationHandler.END

    end_fallbacks = [
        CommandHandler("start", start),
        MessageHandler(
            filters.Regex(f"^({BTN_BOOK}|{BTN_CHECK}|{BTN_CANCEL}|{BTN_MY})$"),
            _end_conversation,
        ),
    ]

    # Флоу бронювання
    book_conv = ConversationHandler(
        entry_points=[
            CommandHandler("book", book_start),
            MessageHandler(filters.Regex(f"^{BTN_BOOK}$"), book_start),
        ],
        states={
            BOOK_SELECT_DATE: [
                CallbackQueryHandler(book_date_selected, pattern="^book_date_|^main_menu$"),
            ],
            BOOK_SELECT_TIME: [
                CallbackQueryHandler(book_time_selected, pattern="^time_|^back_to_date$|^busy$|^main_menu$"),
            ],
            BOOK_CONFIRM: [
                CallbackQueryHandler(book_confirm, pattern="^confirm$|^main_menu$"),
            ],
        },
        fallbacks=end_fallbacks,
        allow_reentry=True,
    )

    # Флоу перевірки зайнятості
    check_conv = ConversationHandler(
        entry_points=[
            CommandHandler("check", check_start),
            MessageHandler(filters.Regex(f"^{BTN_CHECK}$"), check_start),
        ],
        states={
            CHECK_SELECT_DATE: [
                CallbackQueryHandler(check_date_selected, pattern="^check_date_|^check_again$|^main_menu$"),
            ],
        },
        fallbacks=end_fallbacks,
        allow_reentry=True,
    )

    # Флоу скасування
    cancel_conv = ConversationHandler(
        entry_points=[
            CommandHandler("cancel_booking", cancel_booking_start),
            MessageHandler(filters.Regex(f"^{BTN_CANCEL}$"), cancel_booking_start),
        ],
        states={
            CANCEL_SELECT: [
                CallbackQueryHandler(cancel_booking_selected, pattern="^del_|^main_menu$"),
            ],
        },
        fallbacks=end_fallbacks,
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(book_conv)
    app.add_handler(check_conv)
    app.add_handler(cancel_conv)
    app.add_handler(MessageHandler(filters.Regex(f"^{BTN_MY}$"), my_bookings))

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
