import os
import sys

# Add backend directory to sys.path
backend_dir = os.path.join(os.path.dirname(__file__), '..', 'backend')
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from database import init_db
from crm_service import (
    app,
    get_db,
    Doctor,
    Appointment,
    ClinicInfo,
    ChatMessage,
    AvailabilityCheck,
    BookingRequest,
    RescheduleRequest,
    CancelRequest,
    CalendarSyncRequest,
    VoiceSimulationRequest,
    get_clinic_info,
    get_doctors,
    check_availability,
    book_appointment,
    reschedule_appointment,
    cancel_appointment,
    sync_calendar,
    get_all_appointments,
    get_consolidated_clinic_data,
    get_database_dump,
    get_conversation_history,
    clear_conversation,
    simulate_voice
)

# Initialize database schema on cold start
try:
    init_db()
except Exception as e:
    print(f"Startup DB init notice: {e}")

@app.get("/")
def root():
    return {
        "status": "online",
        "service": "MediConnect Voice & Hospital CRM API (Neon PostgreSQL)",
        "version": "2.2.0",
        "endpoints": [
            "/api/clinic-data",
            "/api/clinic-info",
            "/api/doctors",
            "/api/appointments",
            "/api/check-availability",
            "/api/conversations/{session_id}",
            "/api/simulate-voice",
            "/api/database-dump"
        ]
    }
