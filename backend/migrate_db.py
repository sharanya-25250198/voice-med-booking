import os
from database import engine, Doctor, ClinicInfo, Appointment, SessionLocal
from sqlalchemy import text

def migrate():
    with engine.connect() as conn:
        print("Migrating schema on database:", engine.url)
        # Drop not null constraints on old columns if they exist
        try:
            conn.execute(text("ALTER TABLE doctors ALTER COLUMN clinic_id DROP NOT NULL;"))
        except Exception as e:
            print("Note on clinic_id:", e)

        try:
            conn.execute(text("ALTER TABLE appointments ALTER COLUMN patient_id DROP NOT NULL;"))
            conn.execute(text("ALTER TABLE appointments ALTER COLUMN starts_at DROP NOT NULL;"))
            conn.execute(text("ALTER TABLE appointments ALTER COLUMN ends_at DROP NOT NULL;"))
        except Exception as e:
            print("Note on appointments old cols:", e)

        # Add all needed columns
        conn.execute(text("ALTER TABLE doctors ADD COLUMN IF NOT EXISTS available_days VARCHAR DEFAULT 'Monday,Tuesday,Wednesday,Thursday,Friday';"))
        conn.execute(text("ALTER TABLE doctors ADD COLUMN IF NOT EXISTS start_time VARCHAR DEFAULT '09:00';"))
        conn.execute(text("ALTER TABLE doctors ADD COLUMN IF NOT EXISTS end_time VARCHAR DEFAULT '17:00';"))

        conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS patient_name VARCHAR;"))
        conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS patient_phone VARCHAR;"))
        conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS doctor_id INTEGER;"))
        conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS appointment_date VARCHAR;"))
        conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS appointment_time VARCHAR;"))
        conn.execute(text("ALTER TABLE appointments ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'Booked';"))
        conn.commit()

        # Update doctor fields
        conn.execute(text("UPDATE doctors SET available_days = 'Monday,Tuesday,Wednesday,Thursday,Friday' WHERE available_days IS NULL;"))
        conn.execute(text("UPDATE doctors SET start_time = '09:00' WHERE start_time IS NULL;"))
        conn.execute(text("UPDATE doctors SET end_time = '17:00' WHERE end_time IS NULL;"))
        conn.commit()

    db = SessionLocal()
    # Check if doctors are present
    doctors_list = [
        ("Dr. Rohan Sharma", "Cardiology", "Monday,Tuesday,Wednesday,Thursday,Friday", "09:00", "17:00"),
        ("Dr. Sarah Patel", "Pediatrics", "Monday,Tuesday,Wednesday,Thursday,Friday", "10:00", "18:00"),
        ("Dr. Amit Verma", "General Medicine", "Monday,Tuesday,Wednesday,Thursday,Friday,Saturday", "08:00", "16:00"),
        ("Dr. Priya Nair", "Gynecology", "Tuesday,Thursday,Saturday", "09:00", "15:00")
    ]
    for name, spec, days, st, et in doctors_list:
        existing = db.query(Doctor).filter(Doctor.name.ilike(f"%{name}%")).first()
        if not existing:
            doc = Doctor(name=name, specialty=spec, available_days=days, start_time=st, end_time=et)
            db.add(doc)
        else:
            existing.available_days = days
            existing.start_time = st
            existing.end_time = et
    db.commit()

    # Clinic info
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

    print("\n--- ALL DOCTORS ---")
    for d in db.query(Doctor).all():
        print(f"Doc #{d.id}: {d.name} ({d.specialty}) | {d.available_days} | {d.start_time}-{d.end_time}")

    print("\n--- ALL APPOINTMENTS ---")
    for a in db.query(Appointment).all():
        print(f"Appt #{a.id}: {a.patient_name} with doctor_id {a.doctor_id} on {a.appointment_date} {a.appointment_time} ({a.status})")

    db.close()
    print("\nDATABASE MIGRATION SUCCESSFUL!")

if __name__ == "__main__":
    migrate()
