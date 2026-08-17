import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from dotenv import load_dotenv

load_dotenv()

# Fallback to local SQLite if DATABASE_URL is not set or empty
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    DATABASE_URL = "sqlite:///clinic.db"

# Format postgres URL if using Neon PostgreSQL
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Check if PostgreSQL driver is installed, otherwise fallback to SQLite
if DATABASE_URL.startswith("postgresql"):
    try:
        import psycopg2
    except ImportError:
        logging.warning("psycopg2 driver not installed locally. Falling back to SQLite clinic.db.")
        DATABASE_URL = "sqlite:///clinic.db"

# Create Engine with connection pool parameters
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=10,
        max_overflow=20,
        connect_args={
            "connect_timeout": 10,
            "application_name": "mediconnect_crm"
        }
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Doctor(Base):
    __tablename__ = "doctors"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    specialty = Column(String, index=True)
    available_days = Column(String)  # Comma separated e.g. "Monday,Tuesday,Wednesday"
    start_time = Column(String)     # "09:00"
    end_time = Column(String)       # "17:00"
    
    appointments = relationship("Appointment", back_populates="doctor")

class Appointment(Base):
    __tablename__ = "appointments"
    id = Column(Integer, primary_key=True, index=True)
    patient_name = Column(String, index=True)
    patient_phone = Column(String, index=True)
    doctor_id = Column(Integer, ForeignKey("doctors.id"))
    appointment_date = Column(String)  # YYYY-MM-DD
    appointment_time = Column(String)  # HH:MM
    status = Column(String, default="Booked")  # Booked, Cancelled, Rescheduled

    doctor = relationship("Doctor", back_populates="appointments")

class ClinicInfo(Base):
    __tablename__ = "clinic_info"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, default="MediConnect Clinic")
    address = Column(String, default="123 Health Boulevard, Suite 100")
    phone = Column(String, default="555-0199")
    weekday_hours = Column(String, default="08:00 to 18:00")
    saturday_hours = Column(String, default="08:00 to 16:00")
    sunday_hours = Column(String, default="Closed")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True)
    role = Column(String)  # user, assistant, system, tool
    content = Column(Text)
    tool_called = Column(String, nullable=True)
    tool_result = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

def init_db():
    from sqlalchemy import text
    Base.metadata.create_all(bind=engine)
    try:
        with engine.connect() as conn:
            # Handle PostgreSQL or SQLite non-destructive column migrations
            if str(engine.url).startswith("postgresql"):
                try:
                    conn.execute(text("ALTER TABLE doctors ALTER COLUMN clinic_id DROP NOT NULL;"))
                except Exception:
                    pass
                try:
                    conn.execute(text("ALTER TABLE appointments ALTER COLUMN patient_id DROP NOT NULL;"))
                    conn.execute(text("ALTER TABLE appointments ALTER COLUMN starts_at DROP NOT NULL;"))
                    conn.execute(text("ALTER TABLE appointments ALTER COLUMN ends_at DROP NOT NULL;"))
                except Exception:
                    pass

            conn.execute(text("ALTER TABLE doctors ADD COLUMN IF NOT EXISTS available_days VARCHAR DEFAULT 'Monday,Tuesday,Wednesday,Thursday,Friday';"))
            conn.execute(text("ALTER TABLE doctors ADD COLUMN IF NOT EXISTS start_time VARCHAR DEFAULT '09:00';"))
            conn.execute(text("ALTER TABLE doctors ADD COLUMN IF NOT EXISTS end_time VARCHAR DEFAULT '17:00';"))

            conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS patient_name VARCHAR;"))
            conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS patient_phone VARCHAR;"))
            conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS doctor_id INTEGER;"))
            conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS appointment_date VARCHAR;"))
            conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS appointment_time VARCHAR;"))
            conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'Booked';"))
            
            # Chat messages schema update
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS tool_called VARCHAR;"))
            conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS tool_result TEXT;"))
            conn.commit()
    except Exception as e:
        logging.info(f"Schema check info: {e}")

    db = SessionLocal()
    try:
        doctors_data = [
            ("Dr. Rohan Sharma", "Cardiology", "Monday,Tuesday,Wednesday,Thursday,Friday", "09:00", "17:00"),
            ("Dr. Sarah Patel", "Pediatrics", "Monday,Tuesday,Wednesday,Thursday,Friday", "10:00", "18:00"),
            ("Dr. Amit Verma", "General Medicine", "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday", "08:00", "16:00"),
            ("Dr. Priya Nair", "Gynecology", "Tuesday,Thursday,Saturday", "09:00", "15:00")
        ]
        for name, spec, days, st, et in doctors_data:
            existing = db.query(Doctor).filter(Doctor.name.ilike(f"%{name}%")).first()
            if not existing:
                doc = Doctor(name=name, specialty=spec, available_days=days, start_time=st, end_time=et)
                db.add(doc)
            else:
                existing.available_days = days
                existing.start_time = st
                existing.end_time = et
        db.commit()

        if db.query(ClinicInfo).count() == 0:
            clinic = ClinicInfo(
                name="MediConnect Clinic",
                address="123 Health Boulevard, Suite 100",
                phone="555-0199",
                weekday_hours="08:00 to 18:00",
                saturday_hours="08:00 to 16:00",
                sunday_hours="Closed"
            )
            db.add(clinic)
            db.commit()
            print("Clinic info initialized.")
    except Exception as e:
        print(f"Error seeding database: {e}")
    finally:
        db.close()
