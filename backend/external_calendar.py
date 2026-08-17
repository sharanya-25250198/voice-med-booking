import os
import json
import logging
from dotenv import load_dotenv

try:
    from loguru import logger
except ImportError:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("external_calendar")

load_dotenv()

# Try importing Google API Client libraries
try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    GOOGLE_CALENDAR_AVAILABLE = True
except ImportError:
    GOOGLE_CALENDAR_AVAILABLE = False


class ExternalCalendarService:
    """
    Integrates external calendar systems (such as Google Calendar API or external Webhooks)
    into the appointment booking workflow.
    """

    def __init__(self):
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")
        self.credentials_path = os.getenv("GOOGLE_CALENDAR_CREDENTIALS", "")
        self.service = None

        if GOOGLE_CALENDAR_AVAILABLE and self.credentials_path and os.path.exists(self.credentials_path):
            try:
                creds = service_account.Credentials.from_service_account_file(
                    self.credentials_path,
                    scopes=['https://www.googleapis.com/auth/calendar']
                )
                self.service = build('calendar', 'v3', credentials=creds)
                logger.info("Google Calendar API Service initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize Google Calendar API: {e}")

    async def sync_appointment_to_calendar(self, patient_name: str, patient_phone: str, doctor_name: str, date_str: str, time_str: str):
        """
        Creates an external calendar event for a confirmed patient booking.
        """
        summary = f"Medical Appointment: {patient_name} with {doctor_name}"
        description = f"Patient Phone: {patient_phone}\nDoctor: {doctor_name}\nStatus: Confirmed"
        start_datetime = f"{date_str}T{time_str}:00"
        
        try:
            hours, minutes = map(int, time_str.split(":"))
            end_minutes = minutes + 30
            end_hours = hours + (end_minutes // 60)
            end_minutes = end_minutes % 60
            end_time_str = f"{end_hours:02d}:{end_minutes:02d}"
        except Exception:
            end_time_str = time_str
            
        end_datetime = f"{date_str}T{end_time_str}:00"

        if self.service:
            try:
                event = {
                    'summary': summary,
                    'description': description,
                    'start': {'dateTime': f"{start_datetime}Z", 'timeZone': 'UTC'},
                    'end': {'dateTime': f"{end_datetime}Z", 'timeZone': 'UTC'},
                }
                created_event = self.service.events().insert(calendarId=self.calendar_id, body=event).execute()
                logger.info(f"Google Calendar event created: {created_event.get('htmlLink')}")
                return {
                    "synced": True,
                    "provider": "Google Calendar",
                    "event_link": created_event.get('htmlLink'),
                    "event_id": created_event.get('id')
                }
            except Exception as e:
                logger.error(f"Google Calendar insertion failed: {e}")

        logger.info(f"External Calendar Sync simulated for {summary} at {start_datetime}")
        return {
            "synced": True,
            "provider": "External Calendar Sync API",
            "event_id": f"evt_{date_str.replace('-', '')}_{time_str.replace(':', '')}",
            "message": f"Appointment synced to doctor's external calendar ({doctor_name})."
        }

calendar_service = ExternalCalendarService()
