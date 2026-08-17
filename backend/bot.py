import os
import sys
import asyncio
import aiohttp
import httpx
import logging
from dotenv import load_dotenv

try:
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
except ImportError:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("pipecat_bot")

from pipecat.frames.frames import TTSSpeakFrame, TextFrame
from pipecat.transports.websocket.fastapi import FastAPIWebsocketTransport, FastAPIWebsocketParams
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregator

# STT Services
from pipecat.services.deepgram.stt import DeepgramSTTService

# LLM Services
from pipecat.services.google.llm import GoogleLLMService
try:
    from pipecat.services.openai.llm import OpenAILLMService
except ImportError:
    OpenAILLMService = None

# TTS Services
from pipecat.services.deepgram.tts import DeepgramTTSService

try:
    from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
except ImportError:
    ElevenLabsTTSService = None

try:
    from pipecat.services.elevenlabs.stt import ElevenLabsSTTService
except ImportError:
    ElevenLabsSTTService = None

# Check Sarvam AI imports safely
import importlib.util
if importlib.util.find_spec("sarvamai") is not None:
    try:
        from pipecat.services.sarvam.stt import SarvamSTTService
        from pipecat.services.sarvam.tts import SarvamTTSService
    except Exception:
        SarvamSTTService = None
        SarvamTTSService = None
else:
    SarvamSTTService = None
    SarvamTTSService = None

# Local/Host CRM URL resolution
CRM_HOST = os.getenv("CRM_HOST", "127.0.0.1")
CRM_PORT = os.getenv("CRM_PORT", "9090")
CRM_URL = f"http://{CRM_HOST}:{CRM_PORT}/api"

# Multi-lingual System Prompts with strict requirements
SYSTEM_PROMPTS = {
    "en": """You are a friendly, professional AI receptionist for "MediConnect Clinic".
Your goal is to assist patients with booking, rescheduling, cancelling, and inquiring about doctor appointments using natural speech.

Strict Rules & Guidelines:
1. Speak in a natural, polite, receptionist manner, as if speaking on a phone call. Keep sentences short and clear for natural audio.
2. Maintain English throughout the conversation.
3. MUST NOT hallucinate doctor availability or working hours. ALWAYS use the `check_availability` tool to verify if a slot is available before confirming any booking or reschedule.
4. When a patient asks to book an appointment:
   - First check doctor availability using `check_availability`.
   - If available, state the details and ask the patient for confirmation (e.g., "Dr. Rohan Sharma is available tomorrow at 4 PM. Would you like me to confirm this booking for you?").
   - Only call `book_appointment` AFTER the patient gives verbal confirmation.
5. If requested information is not available in the database or tools, strictly say: "I don't have that information."
6. If no clinic or doctor data exists in the backend system, strictly say: "No clinic data configured. Please contact support."
7. Always use defined tools for any external system actions or queries.
""",

    "hi": """आप "MediConnect Clinic" के एक मित्रवत और पेशेवर AI रिसेप्शनिस्ट हैं।
आपका लक्ष्य मरीजों को बातचीत के माध्यम से डॉक्टर के अपॉइंटमेंट बुक करने, बदलने, रद्द करने और पूछताछ में सहायता करना है।

सख्त नियम और दिशानिर्देश:
1. बहुत ही विनम्र, प्राकृतिक और संक्षिप्त रूप से बात करें जैसे कि आप फोन कॉल पर बात कर रहे हों।
2. पूरी बातचीत हिंदी भाषा में ही संचालित करें।
3. डॉक्टरों की उपलब्धता के बारे में कभी भी खुद से अनुमान न लगाएं। किसी भी बुकिंग से पहले `check_availability` टूल का उपयोग करके उपलब्धता जांचें।
4. जब मरीज अपॉइंटमेंट बुक करने के लिए कहे:
   - पहले `check_availability` टूल से उपलब्धता जांचें।
   - यदि स्लॉट खाली है, तो विवरण बताएं और मरीज से पुष्टि करने के लिए कहें (जैसे: "डॉ. रोहन शर्मा कल शाम 4 बजे उपलब्ध हैं। क्या मैं आपके लिए यह बुकिंग पक्की कर दूँ?")।
   - मरीज की मौखिक पुष्टि के बाद ही `book_appointment` टूल को कॉल करें।
5. यदि पूछी गई जानकारी उपलब्ध नहीं है, तो strictly कहें: "मेरे पास यह जानकारी नहीं है।"
6. यदि बैकएंड सिस्टम में कोई क्लिनिक डेटा नहीं है, तो कहें: "No clinic data configured. Please contact support."
""",

    "ta": """நீங்கள் "MediConnect Clinic"-ன் நட்பு மற்றும் தொழில்முறை AI வரவேற்பாளர் (Receptionist).
இயற்கையான குரல் உரையாடல் மூலம் நோயாளிகளுக்கு மருத்துவர் முன்பதிவு (Appointment Booking), மறுஅட்டவணை (Reschedule), ரத்து (Cancel) மற்றும் கேள்விகளுக்கு உதவ வேண்டும்.

கண்டிப்பான விதிகள்:
1. தொலைபேசியில் பேசுவது போல் சுருக்கமாகவும் தெளிவாகவும் பேசவும்.
2. முழு உரையாடலையும் தமிழ் மொழியிலேயே தொடரவும்.
3. மருத்துவரின் இருப்பை நீங்களாகவே ஊகிக்கக் கூடாது. `check_availability` கருவியைப் பயன்படுத்தியே சரிபார்க்க வேண்டும்.
4. நோயாளி முன்பதிவு செய்யக் கேட்கும் போது:
   - முதலில் `check_availability` மூலம் சரிபார்க்கவும்.
   - நேரம் காலியாக இருந்தால், விபரங்களைக் கூறி அவர்களிடம் உறுதிப்படுத்தல் கேட்கவும்.
   - நோயாளி "சரி" என்று உறுதிப்படுத்திய பிறகே `book_appointment` கருவியை இயக்கவும்.
5. தகவல் இல்லையெனில்: "I don't have that information." என்று கூறவும்.
6. கிளினிக் தரவு இல்லையெனில்: "No clinic data configured. Please contact support." என்று கூறவும்.
""",

    "es": """Eres un recepcionista de IA amigable y profesional para la "Clínica MediConnect".
Tu objetivo es ayudar a los pacientes a reservar, reprogramar, cancelar y consultar citas médicas mediante voz natural.

Reglas Estrictas:
1. Habla de manera natural y educada, como en una llamada telefónica real. Respuestas cortas.
2. Mantén toda la conversación en Español.
3. NUNCA inventes disponibilidad de médicos. SIEMPRE usa la herramienta `check_availability` para verificar antes de confirmar.
4. Si solicitan reservar:
   - Primero verifica disponibilidad con `check_availability`.
   - Si está libre, resume los detalles y solicita confirmación verbal del paciente.
   - Llama a `book_appointment` SOLO DESPUÉS de recibir confirmación.
5. Si falta información, di exactamente: "I don't have that information."
6. Si no hay datos en el sistema, di: "No clinic data configured. Please contact support."
"""
}

GREETING_TEXT = {
    "en": "Hello! Thank you for calling MediConnect Clinic. How can I assist you with your appointment today?",
    "hi": "नमस्ते! मेडिकनेक्ट क्लिनिक में कॉल करने के लिए धन्यवाद। आज मैं अपॉइंटमेंट के लिए आपकी क्या सहायता कर सकता हूँ?",
    "ta": "வணக்கம்! மெடிகனெக்ட் கிளினிக்கிற்கு அழைத்தமைக்கு நன்றி. இன்று உங்கள் மருத்துவ முன்பதிவுக்கு நான் எவ்வாறு உதவட்டும்?",
    "es": "¡Hola! Gracias por llamar a la Clínica MediConnect. ¿En qué puedo ayudarle hoy?"
}

# --- Tool Handlers ---
async def get_doctors_info_handler(function_name, tool_call_id, args, llm, context, result_callback):
    logger.info("Executing tool: get_doctors_info")
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{CRM_URL}/doctors")
            if r.status_code == 200:
                docs = r.json()
                if not docs:
                    await result_callback({"message": "No clinic data configured. Please contact support."})
                    return
                formatted_docs = []
                for d in docs:
                    formatted_docs.append({
                        "name": d["name"],
                        "specialty": d["specialty"],
                        "available_days": d["available_days"],
                        "hours": f"{d['start_time']} to {d['end_time']}"
                    })
                await result_callback(formatted_docs)
            else:
                await result_callback({"error": "No clinic data configured. Please contact support."})
        except Exception as e:
            logger.error(f"Error fetching doctors: {e}")
            await result_callback({"error": "No clinic data configured. Please contact support."})

async def get_clinic_info_handler(function_name, tool_call_id, args, llm, context, result_callback):
    logger.info("Executing tool: get_clinic_info")
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{CRM_URL}/clinic-info")
            if r.status_code == 200:
                await result_callback(r.json())
            else:
                await result_callback({"error": "No clinic data configured. Please contact support."})
        except Exception as e:
            logger.error(f"Error fetching clinic info: {e}")
            await result_callback({"error": "No clinic data configured. Please contact support."})

async def check_availability_handler(function_name, tool_call_id, args, llm, context, result_callback):
    doctor_name = args.get("doctor_name")
    date = args.get("date")
    time = args.get("time")
    logger.info(f"Executing tool: check_availability for {doctor_name} on {date} at {time}")
    
    async with httpx.AsyncClient() as client:
        try:
            payload = {"doctor_name": doctor_name, "date": date, "time": time}
            r = await client.post(f"{CRM_URL}/check-availability", json=payload)
            await result_callback(r.json())
        except Exception as e:
            logger.error(f"Error checking availability: {e}")
            await result_callback({"available": False, "reason": "No clinic data configured. Please contact support."})

async def book_appointment_handler(function_name, tool_call_id, args, llm, context, result_callback):
    patient_name = args.get("patient_name")
    patient_phone = args.get("patient_phone")
    doctor_name = args.get("doctor_name")
    date = args.get("date")
    time = args.get("time")
    logger.info(f"Executing tool: book_appointment for {patient_name} with {doctor_name} on {date} at {time}")
    
    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "patient_name": patient_name,
                "patient_phone": patient_phone,
                "doctor_name": doctor_name,
                "date": date,
                "time": time
            }
            r = await client.post(f"{CRM_URL}/appointments", json=payload)
            await result_callback(r.json())
        except Exception as e:
            logger.error(f"Error booking appointment: {e}")
            await result_callback({"success": False, "error": "No clinic data configured. Please contact support."})

async def reschedule_appointment_handler(function_name, tool_call_id, args, llm, context, result_callback):
    patient_phone = args.get("patient_phone")
    doctor_name = args.get("doctor_name")
    old_date = args.get("old_date")
    new_date = args.get("new_date")
    new_time = args.get("new_time")
    logger.info(f"Executing tool: reschedule_appointment for {patient_phone} to {new_date} at {new_time}")
    
    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "patient_phone": patient_phone,
                "doctor_name": doctor_name,
                "old_date": old_date,
                "new_date": new_date,
                "new_time": new_time
            }
            r = await client.post(f"{CRM_URL}/appointments/reschedule", json=payload)
            await result_callback(r.json())
        except Exception as e:
            logger.error(f"Error rescheduling: {e}")
            await result_callback({"success": False, "error": "No clinic data configured. Please contact support."})

async def cancel_appointment_handler(function_name, tool_call_id, args, llm, context, result_callback):
    patient_phone = args.get("patient_phone")
    doctor_name = args.get("doctor_name")
    date = args.get("date")
    logger.info(f"Executing tool: cancel_appointment for {patient_phone} with {doctor_name} on {date}")
    
    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "patient_phone": patient_phone,
                "doctor_name": doctor_name,
                "date": date
            }
            r = await client.post(f"{CRM_URL}/appointments/cancel", json=payload)
            await result_callback(r.json())
        except Exception as e:
            logger.error(f"Error cancelling: {e}")
            await result_callback({"success": False, "error": "No clinic data configured. Please contact support."})

async def sync_external_calendar_handler(function_name, tool_call_id, args, llm, context, result_callback):
    patient_name = args.get("patient_name")
    patient_phone = args.get("patient_phone")
    doctor_name = args.get("doctor_name")
    date = args.get("date")
    time = args.get("time")
    logger.info(f"Executing external API tool: sync_external_calendar for {patient_name}")
    
    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "patient_name": patient_name,
                "patient_phone": patient_phone,
                "doctor_name": doctor_name,
                "date": date,
                "time": time
            }
            r = await client.post(f"{CRM_URL}/sync-calendar", json=payload)
            await result_callback(r.json())
        except Exception as e:
            logger.error(f"Error syncing external calendar: {e}")
            await result_callback({"synced": False, "error": "External calendar service offline."})

# --- Tool Schemas ---
from pipecat.adapters.schemas.function_schema import FunctionSchema

tools = [
    FunctionSchema(
        name="get_doctors_info",
        description="Retrieve the list of doctors at the clinic, including their specialties, available days, and working hours.",
        properties={},
        required=[]
    ),
    FunctionSchema(
        name="get_clinic_info",
        description="Retrieve general clinic information including clinic address, contact phone number, and operating hours.",
        properties={},
        required=[]
    ),
    FunctionSchema(
        name="check_availability",
        description="Check if a doctor is available on a specific date and time slot. ALWAYS call this before booking.",
        properties={
            "doctor_name": {"type": "string", "description": "The name of the doctor (e.g. Dr. Rohan Sharma)"},
            "date": {"type": "string", "description": "The date in YYYY-MM-DD format"},
            "time": {"type": "string", "description": "The time in HH:MM 24-hour format (e.g. 16:00)"}
        },
        required=["doctor_name", "date", "time"]
    ),
    FunctionSchema(
        name="book_appointment",
        description="Book a doctor appointment. Call this ONLY after checking availability and receiving verbal confirmation from the user.",
        properties={
            "patient_name": {"type": "string", "description": "Patient's full name"},
            "patient_phone": {"type": "string", "description": "Patient's 10-digit phone number"},
            "doctor_name": {"type": "string", "description": "Doctor's name"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "time": {"type": "string", "description": "Time in HH:MM format"}
        },
        required=["patient_name", "patient_phone", "doctor_name", "date", "time"]
    ),
    FunctionSchema(
        name="reschedule_appointment",
        description="Reschedule an existing booked appointment to a new date and time.",
        properties={
            "patient_phone": {"type": "string", "description": "Patient's phone number"},
            "doctor_name": {"type": "string", "description": "Doctor's name"},
            "old_date": {"type": "string", "description": "Current date of booking in YYYY-MM-DD format"},
            "new_date": {"type": "string", "description": "New date in YYYY-MM-DD format"},
            "new_time": {"type": "string", "description": "New time in HH:MM format"}
        },
        required=["patient_phone", "doctor_name", "old_date", "new_date", "new_time"]
    ),
    FunctionSchema(
        name="cancel_appointment",
        description="Cancel an active appointment booking.",
        properties={
            "patient_phone": {"type": "string", "description": "Patient's phone number"},
            "doctor_name": {"type": "string", "description": "Doctor's name"},
            "date": {"type": "string", "description": "Date of appointment in YYYY-MM-DD format"}
        },
        required=["patient_phone", "doctor_name", "date"]
    ),
    FunctionSchema(
        name="sync_external_calendar",
        description="Sync confirmed appointment details to an external Google Calendar or External Scheduling API.",
        properties={
            "patient_name": {"type": "string", "description": "Patient name"},
            "patient_phone": {"type": "string", "description": "Patient phone"},
            "doctor_name": {"type": "string", "description": "Doctor name"},
            "date": {"type": "string", "description": "Appointment date in YYYY-MM-DD format"},
            "time": {"type": "string", "description": "Appointment time in HH:MM format"}
        },
        required=["patient_name", "patient_phone", "doctor_name", "date", "time"]
    )
]

async def run_voice_bot(websocket, lang, stt_provider, tts_provider, api_keys):
    logger.info(f"Starting Pipecat Voice Agent session (Language: {lang}, STT: {stt_provider}, TTS: {tts_provider})")
    
    gemini_key = api_keys.get("gemini")
    deepgram_key = api_keys.get("deepgram")
    elevenlabs_key = api_keys.get("elevenlabs")
    sarvam_key = api_keys.get("sarvam")

    # Configure FastAPI Websocket Transport with VAD and Protobuf Serializer
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=True,
            vad_enabled=True,  # Voice Activity Detection enabled
            serializer=ProtobufFrameSerializer()
        )
    )

    async with aiohttp.ClientSession() as aiohttp_session:
        # Configure STT Service
        if stt_provider == "sarvam" and SarvamSTTService and sarvam_key:
            logger.info("Initializing Sarvam AI STT Service")
            stt = SarvamSTTService(
                api_key=sarvam_key,
                settings=SarvamSTTService.Settings(
                    language="hi-IN" if lang == "hi" else "en-IN",
                    model="saaras:v3"
                )
            )
        elif (stt_provider == "elevenlabs" or not deepgram_key) and ElevenLabsSTTService and elevenlabs_key:
            logger.info("Initializing ElevenLabs STT Service")
            stt = ElevenLabsSTTService(
                api_key=elevenlabs_key,
                aiohttp_session=aiohttp_session
            )
        elif deepgram_key:
            logger.info("Initializing Deepgram STT Service")
            dg_lang = "en"
            if lang == "hi":
                dg_lang = "hi"
            elif lang == "es":
                dg_lang = "es"
            elif lang == "ta":
                dg_lang = "ta"

            stt = DeepgramSTTService(
                api_key=deepgram_key,
                settings=DeepgramSTTService.Settings(
                    language=dg_lang,
                    model="nova-2"
                )
            )
        elif ElevenLabsSTTService and elevenlabs_key:
            logger.info("Initializing ElevenLabs STT Fallback Service")
            stt = ElevenLabsSTTService(
                api_key=elevenlabs_key,
                aiohttp_session=aiohttp_session
            )
        else:
            stt = DeepgramSTTService(api_key=deepgram_key or "placeholder")

        # Configure TTS Service
        if (tts_provider == "elevenlabs" or (not deepgram_key and elevenlabs_key)) and ElevenLabsTTSService and elevenlabs_key:
            logger.info("Initializing ElevenLabs TTS Service")
            voice_id = os.getenv("ELEVENLABS_VOICE_ID", "dmEkARJxJEqd5ADSYy8D")
            tts = ElevenLabsTTSService(
                api_key=elevenlabs_key,
                voice_id=voice_id,
                aiohttp_session=aiohttp_session
            )
        elif tts_provider == "sarvam" and SarvamTTSService and sarvam_key:
            logger.info("Initializing Sarvam AI TTS Service")
            tts = SarvamTTSService(
                api_key=sarvam_key,
                settings=SarvamTTSService.Settings(
                    model="bulbul:v3",
                    voice="aditya"
                )
            )
        else:
            logger.info("Initializing Deepgram TTS Service")
            voice_aura = "aura-asteria-en"
            if lang == "es":
                voice_aura = "aura-luna-es"
            tts = DeepgramTTSService(
                api_key=deepgram_key or "placeholder",
                voice=voice_aura
            )

    # Configure LLM (Google Gemini or OpenAI depending on key format)
    system_prompt = SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS["en"])
    if gemini_key and gemini_key.startswith("sk-") and OpenAILLMService:
        logger.info("Initializing OpenAI LLM Service (from sk- key)")
        llm = OpenAILLMService(
            api_key=gemini_key,
            model="gpt-4o-mini"
        )
    else:
        logger.info("Initializing Google Gemini LLM Service")
        llm = GoogleLLMService(
            api_key=gemini_key,
            settings=GoogleLLMService.Settings(
                model="gemini-1.5-flash",
                system_instruction=system_prompt
            )
        )

    # Register Tool Handlers
    llm.register_function("get_doctors_info", get_doctors_info_handler)
    llm.register_function("get_clinic_info", get_clinic_info_handler)
    llm.register_function("check_availability", check_availability_handler)
    llm.register_function("book_appointment", book_appointment_handler)
    llm.register_function("reschedule_appointment", reschedule_appointment_handler)
    llm.register_function("cancel_appointment", cancel_appointment_handler)
    llm.register_function("sync_external_calendar", sync_external_calendar_handler)

    initial_greeting = GREETING_TEXT.get(lang, GREETING_TEXT["en"])
    context = LLMContext(
        messages=[
            {"role": "assistant", "content": initial_greeting}
        ],
        tools=tools
    )

    context_aggregator = LLMContextAggregator(context)

    # Pipecat Audio Pipeline
    pipeline = Pipeline([
        transport.input(),
        stt,
        context_aggregator.user(),
        llm,
        tts,
        transport.output(),
        context_aggregator.assistant()
    ])

    runner = PipelineRunner()

    task = PipelineTask(
        pipeline,
        PipelineParams(
            allow_interruptions=True,  # Barge-in / Interruption handling enabled
            enable_metrics=False
        )
    )

    # Queue initial audio greeting
    logger.info("Queueing voice greeting frame...")
    await task.queue_frames([
        TTSSpeakFrame(initial_greeting)
    ])

    logger.info("Starting Pipecat real-time voice pipeline...")
    await runner.run(task)
    logger.info("Pipecat session ended cleanly.")
