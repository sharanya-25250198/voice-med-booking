import os
import logging
from fastapi import FastAPI, WebSocket, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

try:
    from loguru import logger
except ImportError:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("main")

from database import init_db
from crm_service import (
    app as crm_app,
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
    get_database_dump,
    get_conversation_history,
    clear_conversation,
    simulate_voice
)
from bot import run_voice_bot

load_dotenv()

app = FastAPI(title="Pipecat Voice Assistant & CRM Unified Server")

# Allow CORS for frontends and Vercel deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    init_db()
    logger.info("NeonDB initialized successfully on server startup.")

@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Pipecat Voice Assistant & Hospital CRM Server",
        "database": "Neon PostgreSQL",
        "version": "2.1.0"
    }

# Expose all CRM and Conversation endpoints
app.add_api_route("/api/clinic-info", get_clinic_info, methods=["GET"])
app.add_api_route("/api/doctors", get_doctors, methods=["GET"])
app.add_api_route("/api/check-availability", check_availability, methods=["POST"])
app.add_api_route("/api/appointments", book_appointment, methods=["POST"])
app.add_api_route("/api/appointments", get_all_appointments, methods=["GET"])
app.add_api_route("/api/appointments/reschedule", reschedule_appointment, methods=["POST"])
app.add_api_route("/api/appointments/cancel", cancel_appointment, methods=["POST"])
app.add_api_route("/api/sync-calendar", sync_calendar, methods=["POST"])
app.add_api_route("/api/database-dump", get_database_dump, methods=["GET"])
app.add_api_route("/api/conversations/{session_id}", get_conversation_history, methods=["GET"])
app.add_api_route("/api/conversations/{session_id}", clear_conversation, methods=["DELETE"])
app.add_api_route("/api/simulate-voice", simulate_voice, methods=["POST"])

@app.websocket("/api/voice")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket voice client connected.")
    
    params = websocket.query_params
    lang = params.get("lang", "en")
    stt_provider = params.get("stt", "deepgram")
    tts_provider = params.get("tts", "deepgram")
    
    api_keys = {
        "gemini": params.get("gemini_key") or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY"),
        "deepgram": params.get("deepgram_key") or os.getenv("DEEPGRAM_API_KEY"),
        "elevenlabs": params.get("elevenlabs_key") or os.getenv("ELEVENLABS_API_KEY"),
        "sarvam": params.get("sarvam_key") or os.getenv("SARVAM_API_KEY")
    }
    
    if not api_keys["gemini"]:
        logger.error("Error: LLM API key (Gemini/OpenAI) is missing.")
        await websocket.close(code=1008, reason="LLM API Key is required")
        return

    try:
        await run_voice_bot(websocket, lang, stt_provider, tts_provider, api_keys)
    except Exception as e:
        logger.exception(f"Exception in voice bot execution: {e}")
    finally:
        logger.info("WebSocket client session closed.")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 7500))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
