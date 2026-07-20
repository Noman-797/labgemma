from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.auth import get_current_user
from app.config import get_settings
from app.database import Base, engine, get_db
from app.routers import auth_routes, learning, student, teacher
from app.templating import render

settings = get_settings()
Base.metadata.create_all(bind=engine)


def _ensure_sqlite_columns() -> None:
    """Add new columns on existing SQLite DBs (no Alembic yet)."""
    if not settings.database_url.startswith("sqlite"):
        return
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    alters: list[str] = []
    if "lab_sessions" in tables:
        cols = {c["name"] for c in insp.get_columns("lab_sessions")}
        if "starts_at" not in cols:
            alters.append("ALTER TABLE lab_sessions ADD COLUMN starts_at DATETIME")
        if "ends_at" not in cols:
            alters.append("ALTER TABLE lab_sessions ADD COLUMN ends_at DATETIME")
    if "users" in tables:
        cols = {c["name"] for c in insp.get_columns("users")}
        if "student_id" not in cols:
            alters.append("ALTER TABLE users ADD COLUMN student_id VARCHAR(64)")
    if alters:
        with engine.begin() as conn:
            for stmt in alters:
                conn.execute(text(stmt))


_ensure_sqlite_columns()

app = FastAPI(title="LabGemma", description="AI lab evaluation with Gemma agent pipeline")
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(auth_routes.router)
app.include_router(teacher.router)
app.include_router(learning.router)
app.include_router(student.router)


@app.get("/")
def home(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return render(
        request,
        "index.html",
        {"user": user, "mock_gemma": settings.mock_gemma},
    )


@app.get("/motivation")
def motivation(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    return render(request, "motivation.html", {"user": user})


@app.get("/health")
def health():
    return {"ok": True, "mock_gemma": settings.mock_gemma}
