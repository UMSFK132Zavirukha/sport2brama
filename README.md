# Бот бронювання спортивного майданчику

## Структура файлів

```
booking_bot/
├── bot.py              # Основний файл бота
├── google_calendar.py  # Сервіс роботи з Google Calendar
├── requirements.txt    # Залежності
├── render.yaml         # Конфігурація Render.com
└── credentials.json    # (локально) Ключ Service Account — НЕ завантажувати на GitHub!
```

## Покрокове налаштування

### 1. Google Cloud Console

1. Перейдіть на https://console.cloud.google.com
2. Створіть новий проєкт
3. APIs & Services → Enable APIs → **Google Calendar API** → Enable
4. IAM & Admin → Service Accounts → **Create Service Account**
   - Назва: `booking-bot`
   - Role: не додавайте
5. Клікніть на акаунт → Keys → **Add Key → JSON**
6. Збережіть файл як `credentials.json`

### 2. Google Calendar — доступ

1. Google Calendar → ваш календар → три крапки → Settings and sharing
2. Share with specific people → Add people
3. Email: (з `credentials.json`, поле `client_email`)
4. Права: **Make changes to events** → Save

### 3. Telegram Bot

1. Напишіть @BotFather → /newbot → введіть назву та username
2. Збережіть токен (BOT_TOKEN)

### 4. Telegram Channel для push-повідомлень

1. Створіть канал або використайте існуючий
2. Додайте бота як **адміністратора** каналу (права: Post messages)
3. Отримайте CHANNEL_ID:
   - Перешліть будь-яке повідомлення з каналу боту @userinfobot
   - або додайте @username_to_id_bot в канал
   - ID зазвичай виглядає як `-1001234567890`

### 5. Локальний запуск (для тесту)

```bash
pip install -r requirements.txt

export BOT_TOKEN="ваш_токен"
export CHANNEL_ID="-1001234567890"
export CALENDAR_ID="your_calendar@gmail.com"
# credentials.json має бути в тій же папці

python bot.py
```

### 6. Деплой на Render.com

1. Завантажте файли на GitHub (без credentials.json!)
2. Render.com → New → **Background Worker** → підключіть репозиторій
3. Environment Variables → додайте всі 4 змінні:
   - `BOT_TOKEN` — токен від @BotFather
   - `CHANNEL_ID` — ID каналу
   - `CALENDAR_ID` — ID календаря
   - `GOOGLE_CREDENTIALS_JSON` — вставте **весь вміст** credentials.json як один рядок

## Команди бота

| Команда | Опис |
|---------|------|
| /start | Головне меню |
| /book | Забронювати час |
| /mybookings | Переглянути мої бронювання |
| /check 05.05.2026 | Перевірити зайнятість на дату |
| /cancel_booking | Скасувати бронювання |

## Налаштування годин роботи

У файлі `bot.py` змініть:
```python
WORK_START = 8   # початок роботи (8:00)
WORK_END = 21    # кінець роботи (21:00)
SLOT_DURATION = 1  # тривалість слоту в годинах
```

## Важливо

- `credentials.json` **ніколи** не завантажуйте на GitHub
- Додайте `credentials.json` в `.gitignore`
- На Render передавайте credentials через змінну `GOOGLE_CREDENTIALS_JSON`
