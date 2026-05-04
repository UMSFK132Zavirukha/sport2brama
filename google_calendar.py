"""
Google Calendar service для бота бронювання.
Використовує Service Account — не потребує OAuth-авторизації.
"""
import json
import os
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict
import pytz
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Ключ для ідентифікації бронювань бота в описі події
BOT_BOOKING_TAG = "BOOKING_BOT"


class CalendarService:
    def __init__(self, calendar_id: str, timezone: pytz.BaseTzInfo):
        self.calendar_id = calendar_id
        self.timezone = timezone
        self._service = None

    @property
    def service(self):
        if self._service is None:
            self._service = self._build_service()
        return self._service

    def _build_service(self):
        """Ініціалізація Google Calendar API через Service Account."""
        creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
        creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")

        if creds_json:
            # Варіант 1 — JSON-рядок з env (Render/Railway)
            creds = service_account.Credentials.from_service_account_info(
                json.loads(creds_json), scopes=SCOPES
            )
        else:
            # Варіант 2 — локальний файл
            creds = service_account.Credentials.from_service_account_file(
                creds_file, scopes=SCOPES
            )
        return build("calendar", "v3", credentials=creds)

    # ─── Читання ─────────────────────────────────────────────────────────

    def get_busy_slots(self, date_str: str) -> List[str]:
        """Повертає список зайнятих часових слотів у форматі ['09:00', '11:00', ...]."""
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        # Запит подій за весь день
        day_start = self.timezone.localize(date_obj.replace(hour=0, minute=0, second=0))
        day_end = self.timezone.localize(date_obj.replace(hour=23, minute=59, second=59))

        try:
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
                orderBy="startTime"
            ).execute()
        except Exception as e:
            logger.error(f"Calendar API error: {e}")
            return []

        busy = []
        for event in events_result.get("items", []):
            start = event.get("start", {}).get("dateTime")
            if start:
                dt = datetime.fromisoformat(start).astimezone(self.timezone)
                busy.append(dt.strftime("%H:%M"))
        return busy

    def get_user_bookings(self, user_id: str) -> List[Dict]:
        """Повертає майбутні бронювання конкретного користувача."""
        now = datetime.now(self.timezone)
        max_time = now + timedelta(days=60)

        try:
            events_result = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=now.isoformat(),
                timeMax=max_time.isoformat(),
                singleEvents=True,
                orderBy="startTime",
                q=f"{BOT_BOOKING_TAG}:{user_id}"
            ).execute()
        except Exception as e:
            logger.error(f"Calendar API error: {e}")
            return []

        bookings = []
        for event in events_result.get("items", []):
            desc = event.get("description", "")
            if f"{BOT_BOOKING_TAG}:{user_id}" not in desc:
                continue
            start = event.get("start", {}).get("dateTime")
            if not start:
                continue
            dt = datetime.fromisoformat(start).astimezone(self.timezone)
            bookings.append({
                "event_id": event["id"],
                "date_display": dt.strftime("%d.%m.%Y"),
                "time": dt.strftime("%H:%M"),
                "summary": event.get("summary", "")
            })
        return bookings

    def get_event_info(self, event_id: str) -> Optional[dict]:
        """Отримує інформацію про конкретну подію."""
        try:
            event = self.service.events().get(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            start = event.get("start", {}).get("dateTime")
            if not start:
                return None
            dt = datetime.fromisoformat(start).astimezone(self.timezone)
            return {
                "event_id": event["id"],
                "date_display": dt.strftime("%d.%m.%Y"),
                "time": dt.strftime("%H:%M"),
            }
        except Exception as e:
            logger.error(f"get_event_info error: {e}")
            return None

    # ─── Запис ───────────────────────────────────────────────────────────

    def create_booking(self, date_str: str, hour: int,
                       user_id: str, user_name: str) -> Optional[str]:
        """Створює подію в календарі. Повертає event_id або None."""
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        start_dt = self.timezone.localize(date_obj.replace(hour=hour, minute=0, second=0))
        end_dt = start_dt + timedelta(hours=1)

        event = {
            "summary": f"Бронювання: {user_name}",
            "description": (
                f"{BOT_BOOKING_TAG}:{user_id}\n"
                f"Заброньовано через бота"
            ),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": str(self.timezone)},
            "end":   {"dateTime": end_dt.isoformat(),   "timeZone": str(self.timezone)},
        }

        try:
            created = self.service.events().insert(
                calendarId=self.calendar_id, body=event
            ).execute()
            return created.get("id")
        except Exception as e:
            logger.error(f"create_booking error: {e}")
            return None

    def delete_booking(self, event_id: str) -> bool:
        """Видаляє подію з календаря. Повертає True при успіху."""
        try:
            self.service.events().delete(
                calendarId=self.calendar_id,
                eventId=event_id
            ).execute()
            return True
        except Exception as e:
            logger.error(f"delete_booking error: {e}")
            return False
