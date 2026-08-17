import os
import json
import re
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
from dotenv import load_dotenv

load_dotenv()

import time
from sqlalchemy.orm import joinedload

from database import SessionLocal, Doctor, Appointment, ClinicInfo, ChatMessage, init_db
from external_calendar import calendar_service

app = FastAPI(title="Hospital CRM & Scheduling Service")

# Allow CORS for frontends and external connections
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# High-Performance In-Memory Cache for Sub-Millisecond Reads
_CRM_CACHE = {
    "dashboard_data": None,
    "dashboard_data_time": 0.0,
    "doctors": None,
    "doctors_time": 0.0,
    "clinic_info": None,
    "clinic_info_time": 0.0
}
CACHE_TTL = 6.0  # 6 second read cache for lightning-fast polling

def invalidate_crm_cache():
    """Immediately invalidates in-memory CRM cache on any DB mutation."""
    _CRM_CACHE["dashboard_data"] = None
    _CRM_CACHE["dashboard_data_time"] = 0.0
    _CRM_CACHE["doctors"] = None
    _CRM_CACHE["doctors_time"] = 0.0
    _CRM_CACHE["clinic_info"] = None
    _CRM_CACHE["clinic_info_time"] = 0.0

@app.on_event("startup")
def startup_event():
    init_db()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Request Models
class AvailabilityCheck(BaseModel):
    doctor_name: str
    date: str  # YYYY-MM-DD or relative like 'tomorrow'
    time: str  # HH:MM or 12h like '4 PM'

class BookingRequest(BaseModel):
    patient_name: str
    patient_phone: str
    doctor_name: str
    date: str  # YYYY-MM-DD
    time: str  # HH:MM

class RescheduleRequest(BaseModel):
    patient_phone: str
    doctor_name: str
    old_date: Optional[str] = None
    new_date: str  # YYYY-MM-DD
    new_time: str  # HH:MM

class CancelRequest(BaseModel):
    patient_phone: str
    doctor_name: Optional[str] = None
    date: Optional[str] = None

class CalendarSyncRequest(BaseModel):
    patient_name: str
    patient_phone: str
    doctor_name: str
    date: str
    time: str

class VoiceSimulationRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default_session"
    lang: Optional[str] = "en"
    gemini_key: Optional[str] = None
    conversation_history: Optional[List[Dict[str, Any]]] = []

# --- Date and Time Normalization Helpers ---

ALL_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAY_ABBR = {
    "mon": "Monday",
    "tue": "Tuesday",
    "tues": "Tuesday",
    "wed": "Wednesday",
    "thu": "Thursday",
    "thur": "Thursday",
    "thurs": "Thursday",
    "fri": "Friday",
    "sat": "Saturday",
    "sun": "Sunday"
}

def normalize_time(time_str: str) -> Optional[str]:
    """
    Normalizes any user or LLM time representation to standard 24h HH:MM format.
    Supports:
      - '4 PM', '4:00 PM', '4pm', '4:30 pm' -> '16:00', '16:30'
      - '10 AM', '10:00 AM', '10am', '10:15 am' -> '10:00', '10:15'
      - '16:00', '16:30', '10:00' -> '16:00', '16:30', '10:00'
      - Bare numbers: '4', '4:00' -> '16:00' (daytime clinic hours 1-7 mapped to PM)
      - '9', '9:00', '10', '11' -> '09:00', '09:00', '10:00', '11:00' (mapped to AM)
      - '12', '12:00', '12:30' -> '12:00', '12:30'
    """
    if not time_str:
        return None
    s = str(time_str).strip().lower()

    # 1. Matches with explicit am/pm (e.g. '4:30 pm', '4pm', '10 am', '11:15am')
    m_ampm = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", s)
    if m_ampm:
        hr = int(m_ampm.group(1))
        mn = int(m_ampm.group(2) or "0")
        mer = m_ampm.group(3)
        if mer == "pm" and hr < 12:
            hr += 12
        elif mer == "am" and hr == 12:
            hr = 0
        return f"{hr:02d}:{mn:02d}"

    # 2. Matches standard HH:MM (e.g. '16:00', '09:30', '4:00')
    m_colon = re.search(r"\b(\d{1,2}):(\d{2})\b", s)
    if m_colon:
        hr = int(m_colon.group(1))
        mn = int(m_colon.group(2))
        # Heuristic for medical clinic: hours 1 to 7 without AM/PM are afternoon slots (13:00 to 19:00)
        if 1 <= hr <= 7:
            hr += 12
        return f"{hr:02d}:{mn:02d}"

    # 3. Bare single/double digit hours (e.g. '4', '10', '16', '5')
    m_bare = re.search(r"\b(\d{1,2})\b", s)
    if m_bare:
        hr = int(m_bare.group(1))
        if 1 <= hr <= 7:
            hr += 12
        elif 8 <= hr <= 23:
            pass
        return f"{hr:02d}:00"

    return None

def normalize_date(date_str: str) -> Optional[str]:
    """
    Normalizes date strings to ISO YYYY-MM-DD format.
    Supports relative dates ('today', 'tomorrow', 'day after tomorrow', 'next monday')
    and common formats ('YYYY-MM-DD', 'DD-MM-YYYY', 'MM/DD/YYYY', 'YYYY/MM/DD').
    Returns None if no date is found.
    """
    if not date_str:
        return None
    s = str(date_str).strip().lower()
    now = datetime.now()

    # Check for relative keywords
    if "today" in s:
        return now.strftime("%Y-%m-%d")
    if "day after tomorrow" in s:
        return (now + timedelta(days=2)).strftime("%Y-%m-%d")
    if "tomorrow" in s:
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # Check for day names (e.g. 'next monday', 'this friday', 'tuesday')
    for d_name in ALL_DAYS:
        if d_name.lower() in s:
            target_weekday = ALL_DAYS.index(d_name)
            current_weekday = now.weekday()
            days_ahead = (target_weekday - current_weekday) % 7
            if days_ahead == 0:
                days_ahead = 7  # Next week if today is the same day
            return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    # Check for YYYY-MM-DD
    m_iso = re.search(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b", s)
    if m_iso:
        y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        return f"{y:04d}-{m:02d}-{d:02d}"

    # Check for DD-MM-YYYY or DD/MM/YYYY
    m_eu = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b", s)
    if m_eu:
        d, m, y = int(m_eu.group(1)), int(m_eu.group(2)), int(m_eu.group(3))
        return f"{y:04d}-{m:02d}-{d:02d}"

    # Try direct strptime parses
    for fmt in ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"]:
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass

    return None

def is_doctor_available_on_day(available_days_str: str, target_day_name: str) -> bool:
    """
    Checks if a target day (e.g. 'Tuesday') is included in doctor's available days
    e.g. 'Monday,Tuesday,Wednesday,Thursday,Friday', 'Monday - Friday', 'Mon-Fri', 'Daily'
    """
    if not available_days_str:
        return True
    s = available_days_str.strip().lower()
    t = target_day_name.strip().lower()

    if any(k in s for k in ["daily", "everyday", "all days", "every day", "mon-sun", "monday-sunday"]):
        return True

    # Handle ranges like 'Monday - Friday' or 'Monday to Friday' or 'Mon - Fri'
    for sep in ["-", " to ", " thru ", " through "]:
        if sep in s and "," not in s:
            parts = [p.strip() for p in s.split(sep)]
            if len(parts) == 2:
                start_idx = next((i for i, d in enumerate(ALL_DAYS) if parts[0].lower() in d.lower() or d.lower() in parts[0].lower() or DAY_ABBR.get(parts[0].lower()) == d), -1)
                end_idx = next((i for i, d in enumerate(ALL_DAYS) if parts[1].lower() in d.lower() or d.lower() in parts[1].lower() or DAY_ABBR.get(parts[1].lower()) == d), -1)
                target_idx = next((i for i, d in enumerate(ALL_DAYS) if t in d.lower()), -1)
                if start_idx != -1 and end_idx != -1 and target_idx != -1:
                    if start_idx <= end_idx:
                        return start_idx <= target_idx <= end_idx
                    else:
                        return target_idx >= start_idx or target_idx <= end_idx

    # Handle comma-separated days
    for token in s.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        full_d = DAY_ABBR.get(token) or next((d for d in ALL_DAYS if token in d.lower() or d.lower() in token), None)
        if full_d and full_d.lower() == t:
            return True

    return t in s

def find_doctor(doctor_query: str, db) -> Optional[Doctor]:
    """
    Finds doctor by full name, first name, last name, or specialty with priority scoring.
    Returns None if no doctor or specialty matches the query.
    """
    all_docs = db.query(Doctor).all()
    if not all_docs:
        return None
    if not doctor_query:
        return None

    # Strip user name introductions to prevent patient name from falsely matching doctor name
    query_no_name = re.sub(r"(?:my name is|patient name is|this is|i am|i'm|name is)\s+[A-Za-z]+(?:\s+[A-Za-z]+)?", "", doctor_query, flags=re.IGNORECASE)
    clean = query_no_name.lower().replace("dr.", "").replace("dr", "").replace("doctor", "").strip()
    if not clean:
        return None

    # 1. Exact match on full name
    for d in all_docs:
        d_clean = d.name.lower().replace("dr.", "").replace("dr", "").strip()
        if clean == d_clean or clean == d.name.lower():
            return d

    # 2. Score candidates by token overlap and specificity
    candidates = []
    query_words = set(w for w in clean.split() if len(w) > 2)

    for d in all_docs:
        d_clean = d.name.lower().replace("dr.", "").replace("dr", "").strip()
        d_words = set(w for w in d_clean.split() if len(w) > 2)
        score = 0
        
        # Exact full name equality
        if clean == d_clean:
            score += 100
        # Query matches complete doctor name substring
        elif clean in d_clean:
            score += 50
        elif d_clean in clean:
            score += 30

        # Word overlap (e.g. 'rohan' matches 'dr. rohan sharma')
        overlap = query_words.intersection(d_words)
        score += len(overlap) * 20

        # Specialty match
        if d.specialty and (d.specialty.lower() in clean or clean in d.specialty.lower()):
            score += 40
        if "cardio" in clean and "cardio" in (d.specialty or "").lower():
            score += 35
        if "pedia" in clean and "pedia" in (d.specialty or "").lower():
            score += 35
        if "gynec" in clean and "gynec" in (d.specialty or "").lower():
            score += 35
        if "derma" in clean and "derma" in (d.specialty or "").lower():
            score += 35
        if "general" in clean and "general" in (d.specialty or "").lower():
            score += 25

        if score > 0:
            candidates.append((score, d))

    if candidates:
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    return None

# --- CRM Endpoints ---

@app.get("/api/clinic-info")
def get_clinic_info(db=Depends(get_db)):
    info = db.query(ClinicInfo).first()
    if not info:
        return {
            "name": "MediConnect Clinic",
            "address": "123 Health Boulevard, Suite 100",
            "phone": "555-0199",
            "hours": "Monday-Friday (08:00 to 18:00), Saturday (08:00 to 16:00), Sunday (Closed)"
        }
    return {
        "name": info.name,
        "address": info.address,
        "phone": info.phone,
        "hours": f"Monday-Friday ({info.weekday_hours}), Saturday ({info.saturday_hours}), Sunday ({info.sunday_hours})"
    }

@app.get("/api/doctors")
def get_doctors(db=Depends(get_db)):
    return db.query(Doctor).order_by(Doctor.id.asc()).all()

@app.get("/api/doctors/specialty/{specialty}")
def get_doctors_by_specialty(specialty: str, db=Depends(get_db)):
    return db.query(Doctor).filter(Doctor.specialty.ilike(f"%{specialty}%")).all()

@app.get("/api/doctors/{name}")
def get_doctor_by_name(name: str, db=Depends(get_db)):
    doc = find_doctor(name, db)
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found")
    return doc

@app.post("/api/check-availability")
def check_availability(req: AvailabilityCheck, db=Depends(get_db)):
    doc = find_doctor(req.doctor_name, db)
    if not doc:
        return {"available": False, "reason": f"Doctor '{req.doctor_name}' was not found in clinic records."}

    # Normalize Date
    norm_date = normalize_date(req.date)
    if not norm_date:
        return {"available": False, "reason": f"Invalid date '{req.date}'. Please specify a date like YYYY-MM-DD or 'tomorrow'."}

    try:
        date_obj = datetime.strptime(norm_date, "%Y-%m-%d")
    except ValueError:
        return {"available": False, "reason": f"Invalid date format '{norm_date}'."}

    day_name = date_obj.strftime("%A")
    if not is_doctor_available_on_day(doc.available_days, day_name):
        return {
            "available": False,
            "doctor_name": doc.name,
            "specialty": doc.specialty,
            "date": norm_date,
            "day": day_name,
            "reason": f"{doc.name} ({doc.specialty}) is not on duty on {day_name}s. Available days: {doc.available_days}."
        }

    # Normalize Time
    norm_time = normalize_time(req.time)
    if not norm_time:
        return {"available": False, "reason": f"Invalid time '{req.time}'. Please provide a valid time like '10:00 AM' or '16:00'."}

    try:
        time_obj = datetime.strptime(norm_time, "%H:%M").time()
        start_time_obj = datetime.strptime(doc.start_time, "%H:%M").time()
        end_time_obj = datetime.strptime(doc.end_time, "%H:%M").time()
    except ValueError:
        return {"available": False, "reason": "Time comparison parsing error."}

    if not (start_time_obj <= time_obj <= end_time_obj):
        return {
            "available": False,
            "doctor_name": doc.name,
            "date": norm_date,
            "time": norm_time,
            "reason": f"Selected time {norm_time} is outside {doc.name}'s working hours ({doc.start_time} to {doc.end_time})."
        }

    # Check Active Booking Slot Conflict in NeonDB
    existing = db.query(Appointment).filter(
        Appointment.doctor_id == doc.id,
        Appointment.appointment_date == norm_date,
        Appointment.appointment_time == norm_time,
        Appointment.status == "Booked"
    ).first()

    if existing:
        return {
            "available": False,
            "doctor_name": doc.name,
            "date": norm_date,
            "time": norm_time,
            "reason": f"The slot {norm_time} on {norm_date} with {doc.name} is already booked by another patient."
        }

    return {
        "available": True,
        "doctor_name": doc.name,
        "specialty": doc.specialty,
        "date": norm_date,
        "day": day_name,
        "time": norm_time,
        "message": f"{doc.name} ({doc.specialty}) is available on {norm_date} ({day_name}) at {norm_time}."
    }

@app.post("/api/appointments")
async def book_appointment(req: BookingRequest, db=Depends(get_db)):
    doc = find_doctor(req.doctor_name, db)
    if not doc:
        raise HTTPException(status_code=404, detail="Doctor not found in clinic records")

    norm_date = normalize_date(req.date)
    norm_time = normalize_time(req.time)

    avail_check = check_availability(
        AvailabilityCheck(doctor_name=doc.name, date=norm_date, time=norm_time),
        db
    )
    if not avail_check.get("available"):
        raise HTTPException(status_code=400, detail=avail_check.get("reason"))

    patient_name = req.patient_name.strip() if req.patient_name else "Alex Mercer"
    patient_phone = req.patient_phone.strip() if req.patient_phone else "555-0199"

    appt = Appointment(
        patient_name=patient_name,
        patient_phone=patient_phone,
        doctor_id=doc.id,
        appointment_date=norm_date,
        appointment_time=norm_time,
        status="Booked"
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)
    invalidate_crm_cache()

    # Sync to external calendar API
    calendar_sync_res = await calendar_service.sync_appointment_to_calendar(
        patient_name, patient_phone, doc.name, norm_date, norm_time
    )

    return {
        "success": True,
        "appointment_id": appt.id,
        "patient_name": patient_name,
        "patient_phone": patient_phone,
        "doctor_name": doc.name,
        "specialty": doc.specialty,
        "date": norm_date,
        "time": norm_time,
        "status": "Booked",
        "message": f"Appointment #{appt.id} successfully booked with {doc.name} on {norm_date} at {norm_time}.",
        "external_calendar_sync": calendar_sync_res
    }

@app.post("/api/appointments/reschedule")
def reschedule_appointment(req: RescheduleRequest, db=Depends(get_db)):
    doc = find_doctor(req.doctor_name, db) if req.doctor_name else None
    
    query = db.query(Appointment).filter(Appointment.status == "Booked")
    if req.patient_phone:
        query = query.filter((Appointment.patient_phone == req.patient_phone) | (Appointment.patient_name.ilike(f"%{req.patient_phone}%")))
    if doc:
        query = query.filter(Appointment.doctor_id == doc.id)
    if req.old_date:
        norm_old_date = normalize_date(req.old_date)
        query = query.filter(Appointment.appointment_date == norm_old_date)

    appt = query.order_by(Appointment.id.desc()).first()
    if not appt:
        raise HTTPException(
            status_code=404,
            detail=f"No active booking found to reschedule for {req.patient_phone}."
        )

    target_doc = appt.doctor or doc or db.query(Doctor).first()
    norm_new_date = normalize_date(req.new_date)
    norm_new_time = normalize_time(req.new_time)

    avail_check = check_availability(
        AvailabilityCheck(doctor_name=target_doc.name, date=norm_new_date, time=norm_new_time),
        db
    )
    if not avail_check.get("available"):
        raise HTTPException(status_code=400, detail=avail_check.get("reason"))

    appt.appointment_date = norm_new_date
    appt.appointment_time = norm_new_time
    appt.status = "Booked"
    db.commit()
    invalidate_crm_cache()

    return {
        "success": True,
        "appointment_id": appt.id,
        "doctor_name": target_doc.name,
        "new_date": norm_new_date,
        "new_time": norm_new_time,
        "message": f"Appointment #{appt.id} rescheduled to {norm_new_date} at {norm_new_time} with {target_doc.name}."
    }

@app.post("/api/appointments/cancel")
def cancel_appointment(req: CancelRequest, db=Depends(get_db)):
    query = db.query(Appointment).filter(Appointment.status == "Booked")
    if req.patient_phone:
        query = query.filter((Appointment.patient_phone == req.patient_phone) | (Appointment.patient_name.ilike(f"%{req.patient_phone}%")))
    if req.doctor_name:
        doc = find_doctor(req.doctor_name, db)
        if doc:
            query = query.filter(Appointment.doctor_id == doc.id)
    if req.date:
        norm_date = normalize_date(req.date)
        query = query.filter(Appointment.appointment_date == norm_date)

    appt = query.order_by(Appointment.id.desc()).first()
    if not appt:
        raise HTTPException(
            status_code=404,
            detail=f"No active booked appointment found for {req.patient_phone}."
        )

    appt.status = "Cancelled"
    db.commit()
    invalidate_crm_cache()
    return {
        "success": True,
        "appointment_id": appt.id,
        "message": f"Appointment #{appt.id} for {appt.patient_name} on {appt.appointment_date} at {appt.appointment_time} has been successfully cancelled."
    }

@app.post("/api/sync-calendar")
async def sync_calendar(req: CalendarSyncRequest):
    return await calendar_service.sync_appointment_to_calendar(
        req.patient_name, req.patient_phone, req.doctor_name, req.date, req.time
    )

@app.get("/api/clinic-data")
def get_consolidated_clinic_data(db=Depends(get_db)):
    """
    Blazing-fast consolidated endpoint that retrieves doctors, appointments,
    clinic info, and database status in a SINGLE roundtrip with eager joined loading
    and sub-second memory caching.
    """
    now = time.time()
    if _CRM_CACHE["dashboard_data"] and (now - _CRM_CACHE["dashboard_data_time"] < CACHE_TTL):
        return _CRM_CACHE["dashboard_data"]

    # Eager joined loading for appointments with doctors (Single SQL JOIN, no N+1!)
    appts = db.query(Appointment).options(joinedload(Appointment.doctor)).order_by(Appointment.id.desc()).all()
    docs = db.query(Doctor).order_by(Doctor.id.asc()).all()
    clinic = db.query(ClinicInfo).first()
    msg_count = db.query(ChatMessage).count()

    db_url = os.getenv("DATABASE_URL", "sqlite:///clinic.db")
    engine_type = "Neon PostgreSQL (Live)" if ("postgresql" in db_url or "neon.tech" in db_url) else "SQLite (clinic.db)"

    formatted_docs = [
        {
            "id": d.id,
            "name": d.name,
            "specialty": d.specialty,
            "available_days": d.available_days,
            "start_time": d.start_time,
            "end_time": d.end_time
        } for d in docs
    ]

    formatted_appts = [
        {
            "id": a.id,
            "patient_name": a.patient_name,
            "patient_phone": a.patient_phone,
            "doctor_name": a.doctor.name if a.doctor else "Specialist",
            "specialty": a.doctor.specialty if a.doctor else "General",
            "date": a.appointment_date,
            "time": a.appointment_time,
            "status": a.status
        } for a in appts
    ]

    formatted_clinic = {
        "id": clinic.id if clinic else 1,
        "name": clinic.name if clinic else "MediConnect Clinic",
        "address": clinic.address if clinic else "123 Health Boulevard, Suite 100",
        "phone": clinic.phone if clinic else "555-0199",
        "hours": f"Monday-Friday ({clinic.weekday_hours}), Saturday ({clinic.saturday_hours}), Sunday ({clinic.sunday_hours})" if clinic else "Monday-Friday (08:00 to 18:00), Saturday (08:00 to 16:00), Sunday (Closed)"
    }

    dump_data = {
        "engine": engine_type,
        "database_url": db_url.split("@")[-1] if "@" in db_url else "clinic.db",
        "chat_messages_count": msg_count,
        "tables": {
            "doctors": formatted_docs,
            "appointments": formatted_appts,
            "clinic_info": formatted_clinic
        }
    }

    result = {
        "doctors": formatted_docs,
        "appointments": formatted_appts,
        "clinic_info": formatted_clinic,
        "database_dump": dump_data,
        "cached_at": now
    }

    _CRM_CACHE["dashboard_data"] = result
    _CRM_CACHE["dashboard_data_time"] = now
    return result

@app.get("/api/appointments")
def get_all_appointments(db=Depends(get_db)):
    data = get_consolidated_clinic_data(db)
    return data["appointments"]

@app.get("/api/database-dump")
def get_database_dump(db=Depends(get_db)):
    data = get_consolidated_clinic_data(db)
    return data["database_dump"]

@app.get("/api/conversations/{session_id}")
def get_conversation_history(session_id: str, db=Depends(get_db)):
    msgs = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.id.asc()).all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "tool_called": m.tool_called,
            "tool_result": json.loads(m.tool_result) if m.tool_result else None,
            "time": m.created_at.strftime("%I:%M %p") if m.created_at else ""
        } for m in msgs
    ]

@app.delete("/api/conversations/{session_id}")
def clear_conversation(session_id: str, db=Depends(get_db)):
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete()
    db.commit()
    invalidate_crm_cache()
    return {"success": True, "message": f"Session {session_id} conversation cleared from NeonDB."}

# --- LLM Tool Definitions for OpenAI / Groq / Gemini ---

LLM_TOOLS_SPEC = [
    {
        "type": "function",
        "function": {
            "name": "check_availability",
            "description": "Check if a doctor is available for an appointment on a specific date and time. Use this whenever the user specifies or asks about a doctor, date, or time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "doctor_name": {"type": "string", "description": "Exact doctor's name discussed in the conversation (e.g. 'Dr. Sarah Patel', 'Dr. Rohan Sharma')"},
                    "date": {"type": "string", "description": "Target appointment date (e.g. 'tomorrow', '2026-08-18')"},
                    "time": {"type": "string", "description": "Target appointment time (e.g. '11:00', '16:00', '10:00 AM')"}
                },
                "required": ["doctor_name", "date", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "book_appointment",
            "description": "Book and confirm a doctor appointment. CRITICAL RULE: DO NOT CALL THIS TOOL unless the patient has explicitly provided ALL 5 pieces of information: 1) doctor name, 2) date, 3) time, 4) patient full name, and 5) patient 10-digit phone number. If ANY of these 5 details are missing, DO NOT call book_appointment; instead, call check_availability or ask the user directly for the missing details in your conversational reply.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_name": {"type": "string", "description": "Patient's real full name explicitly stated by user in the conversation"},
                    "patient_phone": {"type": "string", "description": "Patient's real 10-digit contact phone number explicitly stated by user in the conversation"},
                    "doctor_name": {"type": "string", "description": "Doctor's name being booked"},
                    "date": {"type": "string", "description": "Appointment date YYYY-MM-DD or relative like 'tomorrow'"},
                    "time": {"type": "string", "description": "Appointment time e.g. '11:00' or '4 PM'"}
                },
                "required": ["patient_name", "patient_phone", "doctor_name", "date", "time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_appointment",
            "description": "Reschedule an existing booked appointment to a new date and time.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_phone": {"type": "string", "description": "Patient's phone number or name"},
                    "doctor_name": {"type": "string", "description": "Doctor's name"},
                    "old_date": {"type": "string", "description": "Original date if known"},
                    "new_date": {"type": "string", "description": "New requested date"},
                    "new_time": {"type": "string", "description": "New requested time"}
                },
                "required": ["patient_phone", "new_date", "new_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_appointment",
            "description": "Cancel an active doctor appointment.",
            "parameters": {
                "type": "object",
                "properties": {
                    "patient_phone": {"type": "string", "description": "Patient's phone number or name"},
                    "doctor_name": {"type": "string", "description": "Doctor's name"},
                    "date": {"type": "string", "description": "Date of appointment"}
                },
                "required": ["patient_phone"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_doctors_info",
            "description": "Get all available doctors, specialties, and schedules at MediConnect Clinic.",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_clinic_info",
            "description": "Get clinic address, phone number, and operating hours.",
            "parameters": {"type": "object", "properties": {}}
        }
    }
]

# --- Conversational Voice Simulation with Context Memory & Tool Execution ---

@app.post("/api/simulate-voice")
async def simulate_voice(req: VoiceSimulationRequest, db=Depends(get_db)):
    text = req.message.strip()
    session_id = req.session_id or "default_session"
    lang = req.lang or "en"
    
    # Save user message to NeonDB
    user_chat = ChatMessage(session_id=session_id, role="user", content=text)
    db.add(user_chat)
    db.commit()

    # Load current Clinic & Doctor context
    docs = db.query(Doctor).order_by(Doctor.id.asc()).all()
    clinic = db.query(ClinicInfo).first()
    now = datetime.now()
    today_str = now.strftime("%A, %Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%A, %Y-%m-%d")

    docs_summary = "\n".join([
        f"- {d.name} | Specialty: {d.specialty} | Available: {d.available_days} | Hours: {d.start_time} to {d.end_time}"
        for d in docs
    ])

    system_prompt = f"""You are the friendly, professional voice receptionist for "MediConnect Clinic".
Current date: Today is {today_str}. Tomorrow is {tomorrow_str}.
Clinic address: {clinic.address if clinic else '123 Health Boulevard, Suite 100'}. Phone: {clinic.phone if clinic else '555-0199'}.

Available Doctors & Schedules:
{docs_summary}

MANDATORY INFORMATION GATHERING & BOOKING PROTOCOL:
1. Short & Warm Voice: Speak in a concise, natural, friendly receptionist tone suitable for voice audio (1-2 sentences per turn).
2. Context Memory: Remember patient name, phone, doctor, requested date and time across all previous turns in the conversation.
3. MANDATORY 5 DETAILS BEFORE BOOKING:
   You must NEVER call `book_appointment` until you have collected ALL 5 of the following details:
   - 1. Doctor Name (or specialty)
   - 2. Appointment Date (e.g. tomorrow, 2026-08-18)
   - 3. Appointment Time (e.g. 10:00 AM, 4 PM)
   - 4. Patient Full Name
   - 5. Patient Contact Phone Number
4. If the patient requests a doctor, date, and time:
   - First call `check_availability` to confirm the slot is open.
   - If available and patient name/phone are missing, ask for them: "Dr. [Doctor] is available on [Date] at [Time]! To confirm your booking, could you please provide your full name and phone number?"
   - If patient provides name but no phone: ask for their phone number.
   - If patient provides phone but no name: ask for their full name.
   - ONLY call `book_appointment` once doctor, date, time, patient name, and phone number are all provided.
5. Rescheduling / Cancelling: Call `reschedule_appointment` or `cancel_appointment` with the patient's phone/name.
6. Language: Reply in { 'Hindi' if lang == 'hi' else 'Tamil' if lang == 'ta' else 'Spanish' if lang == 'es' else 'English' }.
"""

    # Build multi-turn messages list
    messages = [{"role": "system", "content": system_prompt}]
    
    # Include conversation history (either passed in request or fetched from NeonDB)
    if req.conversation_history and len(req.conversation_history) > 0:
        for turn in req.conversation_history[-10:]:
            r = turn.get("role")
            c = turn.get("text") or turn.get("content") or ""
            if r in ["user", "assistant"] and c:
                messages.append({"role": r, "content": c})
    else:
        past_msgs = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.id.asc()).all()[-10:]
        for pm in past_msgs[:-1]:  # Exclude current message already added
            if pm.role in ["user", "assistant"]:
                messages.append({"role": pm.role, "content": pm.content})

    # Add current user message if not already trailing
    if not (messages and messages[-1].get("role") == "user" and messages[-1].get("content") == text):
        messages.append({"role": "user", "content": text})

    # API Keys resolution
    openai_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPEN_API_KEY") or req.gemini_key
    groq_key = os.getenv("GROQ_API_KEY")
    
    tool_called_name = None
    tool_result_data = None
    action_type = "query"
    assistant_reply = None

    # Try LLM tool calling via OpenAI or Groq
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Try OpenAI
        if openai_key and openai_key.startswith("sk-"):
            try:
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": messages,
                    "tools": LLM_TOOLS_SPEC,
                    "tool_choice": "auto",
                    "temperature": 0.3
                }
                r = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                    json=payload
                )
                if r.status_code == 200:
                    resp_json = r.json()
                    choice = resp_json["choices"][0]["message"]
                    
                    # Handle tool calls
                    if choice.get("tool_calls"):
                        t_call = choice["tool_calls"][0]
                        tool_called_name = t_call["function"]["name"]
                        args = json.loads(t_call["function"].get("arguments", "{}"))
                        
                        # Execute Tool
                        tool_result_data, action_type = await execute_tool(tool_called_name, args, db)
                        
                        # Second turn to LLM with tool output
                        messages.append(choice)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": t_call["id"],
                            "content": json.dumps(tool_result_data)
                        })
                        
                        r2 = await client.post(
                            "https://api.openai.com/v1/chat/completions",
                            headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                            json={"model": "gpt-4o-mini", "messages": messages, "temperature": 0.3}
                        )
                        if r2.status_code == 200:
                            assistant_reply = r2.json()["choices"][0]["message"]["content"]
                    else:
                        assistant_reply = choice.get("content")
            except Exception as e:
                logging.warning(f"OpenAI LLM call error: {e}")

        # 2. Try Groq if OpenAI was unavailable
        if not assistant_reply and groq_key:
            try:
                payload = {
                    "model": "llama-3.3-70b-versatile",
                    "messages": messages,
                    "tools": LLM_TOOLS_SPEC,
                    "tool_choice": "auto",
                    "temperature": 0.3
                }
                r = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                    json=payload
                )
                if r.status_code == 200:
                    resp_json = r.json()
                    choice = resp_json["choices"][0]["message"]
                    if choice.get("tool_calls"):
                        t_call = choice["tool_calls"][0]
                        tool_called_name = t_call["function"]["name"]
                        args = json.loads(t_call["function"].get("arguments", "{}"))
                        tool_result_data, action_type = await execute_tool(tool_called_name, args, db)
                        
                        messages.append(choice)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": t_call["id"],
                            "content": json.dumps(tool_result_data)
                        })
                        r2 = await client.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                            json={"model": "llama-3.3-70b-versatile", "messages": messages, "temperature": 0.3}
                        )
                        if r2.status_code == 200:
                            assistant_reply = r2.json()["choices"][0]["message"]["content"]
                    else:
                        assistant_reply = choice.get("content")
            except Exception as e:
                logging.warning(f"Groq LLM call error: {e}")

    # 3. Contextual Multi-Turn Fallback Engine (Runs if LLM APIs offline or rate-limited)
    if not assistant_reply:
        assistant_reply, tool_called_name, tool_result_data, action_type = await execute_contextual_fallback(
            messages, text, docs, clinic, db
        )

    # Save Assistant response to NeonDB
    bot_chat = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=assistant_reply,
        tool_called=tool_called_name,
        tool_result=json.dumps(tool_result_data) if tool_result_data else None
    )
    db.add(bot_chat)
    db.commit()

    all_appts = get_all_appointments(db)

    return {
        "success": True,
        "assistant_response": assistant_reply,
        "tool_called": tool_called_name,
        "tool_result": tool_result_data,
        "action": action_type,
        "database_updated": action_type in ["booked", "cancelled", "rescheduled"],
        "appointments": all_appts
    }

async def execute_tool(tool_name: str, args: dict, db) -> tuple[dict, str]:
    """Executes a specific tool against the Neon PostgreSQL database"""
    if tool_name == "check_availability":
        doc_name = args.get("doctor_name", "")
        date = args.get("date", "tomorrow")
        time = args.get("time", "10:00")
        res = check_availability(AvailabilityCheck(doctor_name=doc_name, date=date, time=time), db)
        return res, "check_availability"

    elif tool_name == "book_appointment":
        doc_name = (args.get("doctor_name") or "").strip()
        p_name = (args.get("patient_name") or "").strip()
        p_phone = (args.get("patient_phone") or "").strip()
        date = (args.get("date") or "").strip()
        time = (args.get("time") or "").strip()

        # Enforce strict 5-point verification
        missing_fields = []
        if not doc_name or doc_name.lower() in ["doctor", "specialist"]:
            missing_fields.append("the doctor's name")
        if not date:
            missing_fields.append("the appointment date")
        if not time:
            missing_fields.append("the appointment time")
        if not p_name or p_name.lower() in ["alex mercer", "patient", "user", "voice audio", "none", "unknown", ""]:
            missing_fields.append("your full name")
        if not p_phone or p_phone in ["555-0199", "1234567890", "none", "unknown", ""]:
            missing_fields.append("your contact phone number")

        if missing_fields:
            missing_str = " and ".join(missing_fields)
            return {
                "success": False,
                "needs_info": True,
                "missing_fields": missing_fields,
                "message": f"To confirm your appointment, could you please provide {missing_str}?"
            }, "needs_info"

        try:
            res = await book_appointment(BookingRequest(
                patient_name=p_name,
                patient_phone=p_phone,
                doctor_name=doc_name,
                date=date,
                time=time
            ), db)
            return res, "booked"
        except HTTPException as he:
            return {"success": False, "error": he.detail}, "booking_error"

    elif tool_name == "reschedule_appointment":
        try:
            res = reschedule_appointment(RescheduleRequest(
                patient_phone=args.get("patient_phone", "555-0199"),
                doctor_name=args.get("doctor_name", ""),
                old_date=args.get("old_date"),
                new_date=args.get("new_date", "tomorrow"),
                new_time=args.get("new_time", "11:00")
            ), db)
            return res, "rescheduled"
        except HTTPException as he:
            return {"success": False, "error": he.detail}, "reschedule_error"

    elif tool_name == "cancel_appointment":
        try:
            res = cancel_appointment(CancelRequest(
                patient_phone=args.get("patient_phone", "555-0199"),
                doctor_name=args.get("doctor_name"),
                date=args.get("date")
            ), db)
            return res, "cancelled"
        except HTTPException as he:
            return {"success": False, "error": he.detail}, "cancel_error"

    elif tool_name == "get_doctors_info":
        docs = db.query(Doctor).all()
        return [{"name": d.name, "specialty": d.specialty, "available_days": d.available_days, "hours": f"{d.start_time}-{d.end_time}"} for d in docs], "doctors_info"

    elif tool_name == "get_clinic_info":
        info = get_clinic_info(db)
        return info, "clinic_info"

    return {"status": "ok"}, "query"

async def execute_contextual_fallback(messages: list, current_text: str, docs: list, clinic, db) -> tuple[str, Optional[str], Optional[dict], str]:
    """
    Intelligent multi-turn fallback engine that inspects full conversation history
    to extract state (doctor, date, time, patient name, phone) and prompts for any
    missing information before confirming an appointment.
    """
    user_turns = [m.get("content", "") for m in messages if isinstance(m, dict) and m.get("role") == "user"]
    if current_text and (not user_turns or user_turns[-1] != current_text):
        user_turns.append(current_text)
    user_conversation_text = " ".join(user_turns)
    
    lower_cur = current_text.lower()
    lower_full = user_conversation_text.lower()
    
    # 1. Extract Doctor across history using scored matching
    matched_doc = find_doctor(current_text, db) or find_doctor(user_conversation_text, db)
    doctor_explicit = matched_doc is not None
    if not matched_doc and docs:
        matched_doc = docs[0]

    # 2. Extract Date across history
    target_date = normalize_date(current_text) or normalize_date(user_conversation_text)
    date_explicit = target_date is not None
    if not target_date:
        target_date = normalize_date("tomorrow")

    # 3. Extract Time across history
    target_time = normalize_time(current_text) or normalize_time(user_conversation_text)
    time_explicit = target_time is not None
    if not target_time:
        target_time = "10:00"

    # 4. Extract Patient Phone
    phone_match = re.search(r"\b(\d{10}|\d{3}[-\s]\d{3}[-\s]\d{4}|555-\d{4})\b", user_conversation_text)
    patient_phone = phone_match.group(1).replace(" ", "").replace("-", "") if phone_match else None
    phone_explicit = patient_phone is not None

    # 5. Extract Patient Name
    name_match = re.search(r"(?:my name is|patient name is|this is|i am|i'm|name is|for patient|for)\s+([A-Za-z]+(?:\s+[A-Za-z]+)?)", user_conversation_text, re.IGNORECASE)
    raw_name = name_match.group(1).strip() if name_match else ""
    invalid_name_words = {
        "an", "appointment", "tomorrow", "today", "doctor", "dr", "booking", "next", "cardiology",
        "pediatrics", "medicine", "gynecology", "schedule", "please", "yes", "confirm", "available", "time",
        "wednesday", "thursday", "friday", "saturday", "sunday", "monday", "tuesday", "dr.", "rohan", "sarah"
    }
    if raw_name.lower() in invalid_name_words or len(raw_name) < 2:
        patient_name = None
        name_explicit = False
    else:
        patient_name = raw_name.title()
        name_explicit = True

    # CANCEL
    if any(k in lower_cur for k in ["cancel", "delete appointment", "remove booking"]):
        if not phone_explicit:
            return f"To cancel your appointment with {matched_doc.name if matched_doc else 'the clinic'}, could you please provide your phone number?", "cancel_appointment", None, "query"
        try:
            res = cancel_appointment(CancelRequest(patient_phone=patient_phone, doctor_name=matched_doc.name if doctor_explicit else None, date=target_date if date_explicit else None), db)
            return res.get("message", "Appointment cancelled."), "cancel_appointment", res, "cancelled"
        except HTTPException as he:
            return f"I could not find an active booked appointment for phone {patient_phone}. ({he.detail})", "cancel_appointment", None, "query"

    # RESCHEDULE
    elif any(k in lower_cur for k in ["reschedule", "change time", "move appointment", "postpone"]):
        if not phone_explicit:
            return f"To reschedule your appointment, could you please share your phone number and the new date/time you prefer?", "reschedule_appointment", None, "query"
        if not (date_explicit and time_explicit):
            return f"What new date and time would you like to reschedule your appointment to?", "reschedule_appointment", None, "query"
        try:
            res = reschedule_appointment(RescheduleRequest(
                patient_phone=patient_phone,
                doctor_name=matched_doc.name if doctor_explicit else None,
                new_date=target_date,
                new_time=target_time
            ), db)
            return res.get("message", f"Appointment rescheduled to {target_date} at {target_time}."), "reschedule_appointment", res, "rescheduled"
        except HTTPException as he:
            return f"Could not reschedule: {he.detail}", "reschedule_appointment", None, "query"

    # BOOK / CONFIRM / AVAILABILITY FLOW
    elif any(k in lower_full for k in ["book", "schedule", "reserve", "confirm", "yes", "please confirm", "go ahead", "see dr", "appointment", "available", "free", "slot", "dr", "doctor"]) or date_explicit or time_explicit or name_explicit or phone_explicit:
        # 1. Missing Doctor
        if not doctor_explicit:
            return f"Welcome to MediConnect Clinic! We have specialists in General Medicine, Pediatrics, Cardiology, Dermatology, and Gynecology. Which doctor or specialty would you like to see?", "get_doctors_info", None, "query"

        # 2. Missing Date or Time
        if not (date_explicit and time_explicit):
            return f"{matched_doc.name} ({matched_doc.specialty}) is available on {matched_doc.available_days} from {matched_doc.start_time} to {matched_doc.end_time}. What date and time would you prefer?", "get_doctors_info", {"doctor": matched_doc.name}, "query"

        # Check availability
        avail = check_availability(AvailabilityCheck(doctor_name=matched_doc.name, date=target_date, time=target_time), db)
        if not avail.get("available"):
            return f"I checked {matched_doc.name}'s schedule for {target_date} at {target_time}, but that slot is unavailable ({avail.get('reason')}). Would you like to select another time?", "check_availability", avail, "query"

        # Slot is available -> Check if Name and Phone are provided
        if not name_explicit and not phone_explicit:
            return f"Great news! {matched_doc.name} ({matched_doc.specialty}) is available on {target_date} at {target_time}. To confirm your booking, could you please provide your full name and 10-digit phone number?", "check_availability", avail, "query"
        elif not name_explicit:
            return f"Thank you for the phone number ({patient_phone})! Could you please tell me your full name so I can confirm the booking with {matched_doc.name} on {target_date} at {target_time}?", "check_availability", avail, "query"
        elif not phone_explicit:
            return f"Thank you, {patient_name}! Could you please provide your 10-digit phone number to finalize your booking with {matched_doc.name} on {target_date} at {target_time}?", "check_availability", avail, "query"

        # ALL 5 DETAILS ARE PRESENT -> BOOK AND CONFIRM!
        try:
            res = await book_appointment(BookingRequest(
                patient_name=patient_name,
                patient_phone=patient_phone,
                doctor_name=matched_doc.name,
                date=target_date,
                time=target_time
            ), db)
            msg = f"Your appointment has been confirmed with {matched_doc.name} ({matched_doc.specialty}) on {target_date} at {target_time} for {patient_name}. We look forward to seeing you!"
            return msg, "book_appointment", res, "booked"
        except Exception as e:
            return f"Error booking: {e}", "book_appointment", None, "booking_error"

    # DOCTOR LIST OR CLINIC INFO
    elif any(k in lower_cur for k in ["doctor", "specialist", "who", "cardiologist", "pediatrician", "hours", "clinic", "address", "phone"]):
        if any(k in lower_cur for k in ["hours", "address", "phone", "location"]):
            info = get_clinic_info(db)
            return f"MediConnect Clinic is located at {info['address']}. We are open {info['hours']}. Phone: {info['phone']}.", "get_clinic_info", info, "query"
        return f"Our doctors include: " + ", ".join([f"{d.name} ({d.specialty})" for d in docs]) + ". Who would you like to see?", "get_doctors_info", None, "query"

    return f"How can I help you today? You can ask about doctor schedules, check slot availability, or book an appointment.", "query", None, "query"
