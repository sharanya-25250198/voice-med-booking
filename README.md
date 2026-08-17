# AI-Powered Voice Medical Appointment Booking Assistant

A production-like, public-facing, voice-first AI receptionist for hospitals and clinics that enables patients to book, reschedule, cancel, and query medical appointments using natural speech over a phone-call-style audio stream.

Built with **Pipecat**, **FastAPI**, **Neon PostgreSQL**, **Google Gemini**, and **React (Vite)**. Ready for deployment on **Vercel** (frontend) and cloud hosting (backend).

---

## 🌟 Key Features

- **Voice-First Experience**: High quality real-time conversational audio without manual user triggers.
- **Pipecat Voice Stack**:
  - **Voice Activity Detection (VAD)**: Detects when the user begins speaking.
  - **Turn Detection**: Handles fluid conversational flow.
  - **Barge-in / Interruption Handling**: Instantly stops assistant audio when the user speaks over it (`allow_interruptions=True`).
  - **Low-Latency Streaming**: Streaming WebSocket pipeline with audio frame serialization.
- **STT Provider Choices**:
  - Deepgram (Nova-2)
  - Sarvam AI (Saaras v3)
  - ElevenLabs STT
- **TTS Provider Choices**:
  - Deepgram Aura
  - ElevenLabs Multilingual
  - Sarvam Bulbul
- **Multi-Language Support**:
  - English (`en`)
  - Hindi (`hi`)
  - Tamil (`ta`)
  - Spanish (`es`)
- **Strict AI Rules**:
  - Zero hallucination of doctor schedules.
  - Required verbal user confirmation before calling the booking tool.
  - Standardized fallbacks:
    - Missing info: *"I don't have that information."*
    - No clinic data: *"No clinic data configured. Please contact support."*
- **Extensible Agent Tools**:
  1. `get_doctors_info`: Queries doctor names, specialties, working hours, and available days.
  2. `get_clinic_info`: Queries clinic address, contact phone, and operating hours.
  3. `check_availability`: Verifies doctor schedule, day of week, and active booking slots.
  4. `book_appointment`: Confirms booking and syncs to external calendar.
  5. `reschedule_appointment`: Validates new slot and reschedules existing booking.
  6. `cancel_appointment`: Cancels existing booking.
  7. `sync_external_calendar`: External API tool integrating with Google Calendar API or external scheduling API.

---

## 🏗 System Architecture

```
User Audio (Microphone)
       ↓
WebSocket Transport (Protobuf Serializer & VAD)
       ↓
STT Service (Deepgram / Sarvam AI / ElevenLabs)
       ↓
Context Aggregator (User Turn)
       ↓
LLM Engine (Google Gemini 1.5 Flash + Tool Functions)
       │
       ├── Call Tools ──→ Backend CRM API & Database (Neon Postgres / SQLite)
       │                         │
       │                         └── Sync Event ──→ External API (Google Calendar)
       ↓
TTS Service (Deepgram Aura / ElevenLabs / Sarvam Bulbul)
       ↓
WebSocket Transport (Audio Playback)
```

---

## 📁 Repository Structure

```
voice-med-booking/
├── .gitignore                   # Root gitignore rules
├── .antigravityignore           # Workspace ignore settings
├── vercel.json                  # Vercel deployment configuration
├── README.md                    # Project documentation & walkthrough
├── backend/
│   ├── main.py                  # FastAPI WebSocket & Health check server
│   ├── bot.py                   # Pipecat Voice Agent pipeline & tools
│   ├── crm_service.py           # Hospital CRM & Scheduling API
│   ├── database.py              # SQLAlchemy database (Neon Postgres / SQLite)
│   ├── external_calendar.py     # External API Integration (Google Calendar API)
│   ├── requirements.txt         # Python backend dependencies
│   └── .env.example             # Environment variable template
└── frontend/
    ├── package.json             # Vite React frontend dependencies
    ├── vite.config.js           # Vite build config
    └── src/
        ├── App.jsx              # Audio visualizer, controls, dashboard & settings
        └── index.css            # Styling & design system
```

---

## 🛠 Local Setup & Running

### 1. Backend Setup

```bash
cd backend
python -m venv .venv
# On Windows PowerShell:
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

Set environment variables in `backend/.env`:
```env
GEMINI_API_KEY=your_gemini_api_key
DEEPGRAM_API_KEY=your_deepgram_api_key
DATABASE_URL=postgresql://user:password@ep-host.region.neon.tech/dbname?sslmode=require
```

Start CRM & Voice Assistant services:
```bash
# Terminal 1: Hospital CRM Service (Port 9090)
python -m uvicorn crm_service:app --port 9090 --reload

# Terminal 2: Pipecat Voice Server (Port 7500)
python -m uvicorn main:app --port 7500 --reload
```

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in your browser.

---

## 🚀 Deployment Guide

### Deploying Frontend to Vercel
1. Connect this repository to **Vercel**.
2. Vercel automatically detects `vercel.json`.
3. Set optional Build Environment Variables:
   - `VITE_VOICE_WS_URL`: `wss://your-backend-domain.com/api/voice`
   - `VITE_CRM_URL`: `https://your-backend-domain.com/api`

### Deploying Backend
Deploy the `backend/` directory to any Python host supporting WebSockets (e.g., Render, Railway, Fly.io, or AWS EC2).

---

## 📹 Loom Video Walkthrough Script

In your demo video:
1. **Introduction**: Highlight voice-first appointment booking with Pipecat, Neon PostgreSQL, and multi-language support.
2. **Voice Interaction**:
   - Start voice call.
   - Speak: *"Hi, I want to book an appointment with Dr. Sharma tomorrow at 4 PM."*
   - Show agent calling `check_availability`, summarizing details, asking for confirmation, and executing `book_appointment` + external calendar sync.
3. **Barge-in / Interruption**: Interrupt the agent mid-sentence to demonstrate VAD and turn detection.
4. **Real-time Dashboard**: Show the newly booked appointment appearing instantly in the patient table.
5. **Tool Extensibility Explanation**: Explain how `tools` array and function schemas in `bot.py` allow adding new tools effortlessly.

---

## 📌 Note
Per project guidelines, no `git commit` or deployment commands will be executed until authorized by the user.
