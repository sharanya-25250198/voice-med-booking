# 🩺 MediConnect AI - Voice-Based Medical Appointment Assistant
> **AI-Powered Voice Assistant for Hospitals & Clinics**  
> *Conversational appointment booking, scheduling, doctor availability checks, external calendar syncing, and real-time receptionist desk.*

---

## 📌 About The Project

**MediConnect AI** is a public-facing, voice-first medical assistant designed for hospitals and clinics. It allows patients to interact naturally using speech to inquire about doctors, check open schedule slots, book appointments, reschedule existing visits, or cancel appointments.

### 🌟 Core Capabilities
- **🎙 100% Speech-Driven Interaction**: Real-time bidirectional streaming over WebSockets powered by Pipecat AI.
- **⚡ Voice Activity Detection (VAD) & Barge-in Interruption**: Patients can speak anytime and barge in while the AI is responding (`allow_interruptions=True`).
- **🌐 Multi-lingual Speech & TTS Engine**: Supports English (`en`), Hindi (`hi`), Tamil (`ta`), and Spanish (`es`) with dynamic STT/TTS provider selection (Deepgram, Sarvam AI, ElevenLabs).
- **🛡 Anti-Hallucination Scheduling Rules**: Strictly relies on real-time database queries to verify doctor working hours, working days, and existing bookings before confirming any slot.
- **📅 External Calendar Tool Integration**: Automatically synchronizes patient bookings to Google Calendar / external scheduling APIs.
- **🏥 Receptionist Desk & History Registry**: Dedicated reception view featuring real-time booking statistics, instant patient search, status filtering, and one-click cancellation/calendar sync.
- **💾 Dual Database Engine**: Neon PostgreSQL (`postgresql://...`) with connection pooling and safe fallback to local SQLite (`clinic.db`).
- **📱 Fully Mobile Responsive**: Glassmorphism UI layout tailored for mobile phones, tablets, and desktop workstations.

---

## 🏗 System Architecture

```mermaid
graph TD
    A[Patient / User] -->|Speech Audio Stream (WebSocket)| B[Frontend React Dashboard]
    B -->|WebSocket Protobuf Frames| C[Pipecat Voice Server (main.py:7500)]
    C -->|STT Transcribe| D[Speech-to-Text: Deepgram / Sarvam / ElevenLabs]
    C -->|LLM Reasoning & Function Calling| E[Google Gemini LLM]
    E -->|Call Tools| F[Hospital CRM Service (crm_service.py:9090)]
    F -->|Query / Update| G[Neon PostgreSQL / SQLite DB]
    F -->|Webhook Sync| H[Google Calendar API / External Tool]
    C -->|TTS Audio Stream| B
    B -->|Reception Control & Monitoring| I[Receptionist Desk View]
```

---

## 🚀 Setup & Local Execution Guide

### Prerequisites
- **Python**: Version 3.10 to 3.14
- **Node.js**: Version 18+ and `npm`
- **API Keys**:
  - `GEMINI_API_KEY`: Required for AI conversational reasoning.
  - `DEEPGRAM_API_KEY`: Required for Deepgram STT/TTS.
  - `ELEVENLABS_API_KEY`: Optional for ElevenLabs voice generation.
  - `SARVAM_API_KEY`: Optional for Sarvam AI Indian language voice model.

---

### Step 1: Install Dependencies

#### 1. Backend Python Dependencies
```bash
cd backend
python -m pip install -r requirements.txt
```

#### 2. Frontend React Dependencies
```bash
cd ../frontend
npm install
```

---

### Step 2: Environment Variables Configuration

Create a `.env` file in `backend/.env`:
```env
# AI & Voice API Keys
GEMINI_API_KEY=your_gemini_api_key_here
DEEPGRAM_API_KEY=your_deepgram_api_key_here
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here

# Database Configuration (Neon PostgreSQL or SQLite)
DATABASE_URL=postgresql://neondb_owner:password@ep-host.neon.tech/neondb?sslmode=require

# External Calendar API Configuration
GOOGLE_SERVICE_ACCOUNT_EMAIL=your_service_account@iam.gserviceaccount.com

# Server Ports
PORT=7500
CRM_PORT=9090
```

Create a `.env` file in `frontend/.env`:
```env
VITE_GEMINI_API_KEY=your_gemini_api_key_here
VITE_ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
VITE_CRM_URL=http://127.0.0.1:9090/api
```

---

### Step 3: Run the Local Development Environment

Open **3 separate terminal windows**:

#### Terminal 1: Hospital CRM Service (Port 9090)
```bash
cd backend
python -m uvicorn crm_service:app --port 9090 --reload
```

#### Terminal 2: Pipecat Voice Assistant Server (Port 7500)
```bash
cd backend
python -m uvicorn main:app --port 7500 --reload
```

#### Terminal 3: Frontend Vite Dashboard (Port 5173)
```bash
cd frontend
npm run dev
```

Open your browser at `http://localhost:5173`.

---

## 📖 How to Use the Application

### 1. Starting a Voice Session
1. Open the app on your browser or mobile phone.
2. Ensure your API keys are set (click **Configure** in the top right to verify).
3. Select your language (**English**, **Hindi**, **Tamil**, or **Spanish**).
4. Click **Start Voice Call**.
5. Speak naturally into your microphone!

### 2. Example Voice Commands
- **Check Doctors**: *"What doctors are available in cardiology?"*
- **Check Hours**: *"What are the clinic hours?"*
- **Check Availability**: *"Is Dr. Rohan Sharma available tomorrow at 11 AM?"*
- **Book Appointment**: *"Book an appointment for John with Dr. Rohan Sharma on 2026-08-18 at 11 AM. My phone number is 9876543210."*
- **Reschedule**: *"Reschedule my appointment #1 to 2 PM."*
- **Cancel**: *"Cancel my appointment #1."*

### 3. Using the Receptionist View
1. Click the **Receptionist View** button in the top header.
2. View real-time metric cards: **Total Bookings**, **Active Confirmed**, **Cancelled History**, and **Specialists On Duty**.
3. Use the **Search Bar** to instantly search patient names, contact numbers, or doctors.
4. Filter by **All**, **Confirmed**, or **Cancelled**.
5. Use quick action buttons to **Cancel** an appointment or **Sync** with Google Calendar.

---

## ☁️ Vercel Deployment Instructions

1. Log in to Vercel CLI:
   ```bash
   npx vercel login
   ```
2. Navigate to the `frontend` folder and deploy to production:
   ```bash
   cd frontend
   npx vercel --prod --yes
   ```
3. Your app will be deployed instantly with a live production URL!

---

## 🧪 Testing Backend Connections & APIs

Run the included automated test suite to verify all backend REST endpoints and WebSocket health:
```bash
python scratch/test_apis.py
```

---

## 📄 License & Contact
Built for hospitals and healthcare clinics. Designed for high reliability, low-latency voice interaction, and multi-language support.
