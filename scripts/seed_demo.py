"""Seed demo teacher + students."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.auth import hash_password
from app.database import Base, SessionLocal, engine
from app.models import User


def main() -> None:
    Base.metadata.create_all(bind=engine)
    # Match app.main: ensure student_id column exists on older SQLite DBs
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "users" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("users")}
        if "student_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN student_id VARCHAR(64)"))

    db = SessionLocal()
    demos = [
        {
            "name": "MD Shahriyar Al Mustakim Mitul",
            "email": "teacher@demo.com",
            "password": "teacher123",
            "role": "teacher",
            "student_id": None,
            "aliases": [],
        },
        {
            "name": "Abdullah Al Noman",
            "email": "abdnoman093@gmail.com",
            "password": "student123",
            "role": "student",
            "student_id": "202114001",
            "aliases": ["student1@demo.com"],
        },
        {
            "name": "Student Two",
            "email": "student2@demo.com",
            "password": "student123",
            "role": "student",
            "student_id": "202114002",
            "aliases": [],
        },
    ]
    for demo in demos:
        user = db.query(User).filter(User.email == demo["email"]).first()
        if not user:
            for alias in demo["aliases"]:
                user = db.query(User).filter(User.email == alias).first()
                if user:
                    user.email = demo["email"]
                    print(f"renamed email: {alias} → {demo['email']}")
                    break
        if user:
            changed = False
            if user.name != demo["name"]:
                user.name = demo["name"]
                changed = True
            if demo["role"] == "student" and (user.student_id or "") != (demo["student_id"] or ""):
                user.student_id = demo["student_id"]
                changed = True
            if changed:
                print(f"updated: {demo['email']}")
            else:
                print(f"exists: {demo['email']}")
            continue
        db.add(
            User(
                name=demo["name"],
                email=demo["email"],
                password_hash=hash_password(demo["password"]),
                role=demo["role"],
                student_id=demo["student_id"],
            )
        )
        print(f"created: {demo['email']} / {demo['password']} ({demo['role']})")
    db.commit()
    db.close()
    print("Done.")


if __name__ == "__main__":
    main()
