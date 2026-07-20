from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user, hash_password, verify_password
from app.database import get_db
from app.models import User
from app.templating import render

router = APIRouter(tags=["auth"])


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/" if user.role == "student" else "/teacher/", status_code=303)
    return render(request, "auth/login.html", {"error": None})


@router.post("/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email.strip().lower()).first()
    if not user or not verify_password(password, user.password_hash):
        return render(request, "auth/login.html", {"error": "Invalid email or password"}, status_code=400)
    request.session["user_id"] = user.id
    dest = "/teacher/" if user.role == "teacher" else "/lab/"
    return RedirectResponse(dest, status_code=303)


@router.get("/register")
def register_page(request: Request):
    return render(request, "auth/register.html", {"error": None})


@router.post("/register")
def register(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    db: Session = Depends(get_db),
):
    email = email.strip().lower()
    if role not in ("teacher", "student"):
        return render(
            request,
            "auth/register.html",
            {"error": "Role must be teacher or student"},
            status_code=400,
        )
    if db.query(User).filter(User.email == email).first():
        return render(
            request,
            "auth/register.html",
            {"error": "Email already registered"},
            status_code=400,
        )
    user = User(name=name.strip(), email=email, password_hash=hash_password(password), role=role)
    db.add(user)
    db.commit()
    request.session["user_id"] = user.id
    dest = "/teacher/" if role == "teacher" else "/lab/"
    return RedirectResponse(dest, status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@router.get("/profile")
def profile_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    need_id = request.query_params.get("need_id") == "1" and user.role == "student"
    error = None
    if need_id and not (user.student_id or "").strip():
        error = "Enter Your Student ID"
    return render(
        request,
        "auth/profile.html",
        {"user": user, "message": None, "error": error},
    )


@router.post("/profile")
def profile_update(
    request: Request,
    name: str = Form(...),
    student_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    name = name.strip()
    if not name or len(name) > 120:
        return render(
            request,
            "auth/profile.html",
            {"user": user, "message": None, "error": "Enter a valid name (max 120 characters)."},
            status_code=400,
        )
    user.name = name
    if user.role == "student":
        sid = (student_id or "").strip()
        if not sid:
            return render(
                request,
                "auth/profile.html",
                {"user": user, "message": None, "error": "Enter Your Student ID"},
                status_code=400,
            )
        if len(sid) > 64:
            return render(
                request,
                "auth/profile.html",
                {"user": user, "message": None, "error": "Student ID must be at most 64 characters."},
                status_code=400,
            )
        user.student_id = sid
    db.commit()
    db.refresh(user)
    return render(
        request,
        "auth/profile.html",
        {"user": user, "message": "Profile saved.", "error": None},
    )
