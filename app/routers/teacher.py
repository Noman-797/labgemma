import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import LabProblem, LabSession, LabSubmission, User
from app.services.generate_lab_pack import generate_lab_pack
from app.services.generate_rubric import generate_rubric
from app.services.generate_session_description import generate_session_description
from app.services.normalize import normalize_rubric
from app.services.session_time import end_lab, go_live, set_upcoming
from app.templating import render

router = APIRouter(prefix="/teacher", tags=["teacher"])


def _teacher_or_redirect(request: Request, db: Session) -> User | RedirectResponse:
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role != "teacher":
        return RedirectResponse("/lab/", status_code=303)
    return user


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    sessions = (
        db.query(LabSession).filter(LabSession.teacher_id == user.id).order_by(LabSession.created_at.desc()).all()
    )
    return render(request, "teacher/dashboard.html", {"user": user, "sessions": sessions})


@router.get("/sessions/create")
def create_session_page(request: Request, db: Session = Depends(get_db)):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    return render(request, "teacher/create_session.html", {"user": user, "error": None})


@router.post("/sessions/create")
def create_session(
    request: Request,
    title: str = Form(...),
    description: str = Form(""),
    marks_per_lab: int = Form(100),
    duration_minutes: int = Form(60),
    db: Session = Depends(get_db),
):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    duration_minutes = max(1, min(duration_minutes, 24 * 60))
    session = LabSession(
        teacher_id=user.id,
        title=title.strip(),
        description=description.strip(),
        marks_per_lab=marks_per_lab,
        duration_minutes=duration_minutes,
        status="draft",
    )
    db.add(session)
    db.commit()
    return RedirectResponse(f"/teacher/sessions/{session.id}/problems", status_code=303)


@router.post("/sessions/describe")
async def describe_session(
    request: Request,
    title: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    title = title.strip()
    if not title:
        return JSONResponse({"error": "Enter a title first."}, status_code=400)
    try:
        description = await generate_session_description(title)
        return JSONResponse({"description": description})
    except Exception as exc:  # noqa: BLE001 — surface to UI
        return JSONResponse({"error": str(exc)}, status_code=502)


@router.get("/sessions/{session_id}/problems")
def manage_problems(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.teacher_id == user.id).first()
    if not session:
        return RedirectResponse("/teacher/", status_code=303)
    problems = db.query(LabProblem).filter(LabProblem.session_id == session.id).order_by(LabProblem.order).all()
    return render(
        request,
        "teacher/manage_problems.html",
        {"user": user, "session": session, "problems": problems},
    )


@router.post("/sessions/{session_id}/toggle")
def toggle_session(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.teacher_id == user.id).first()
    if session:
        # draft (Upcoming) → active (Live) → closed (Past) → draft
        nxt = {"draft": "active", "active": "closed", "closed": "draft"}
        session.status = nxt.get(session.status, "draft")
        db.commit()
    return RedirectResponse(f"/teacher/sessions/{session_id}/problems", status_code=303)


@router.post("/sessions/{session_id}/status")
def set_session_status(
    session_id: int,
    request: Request,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    if status not in ("draft", "active", "closed"):
        return RedirectResponse(f"/teacher/sessions/{session_id}/problems", status_code=303)
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.teacher_id == user.id).first()
    if session:
        if status == "active":
            go_live(session)
        elif status == "closed":
            end_lab(session)
        else:
            set_upcoming(session)
        db.commit()
    return RedirectResponse(f"/teacher/sessions/{session_id}/problems", status_code=303)


@router.post("/sessions/{session_id}/duration")
def set_session_duration(
    session_id: int,
    request: Request,
    duration_minutes: int = Form(60),
    db: Session = Depends(get_db),
):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.teacher_id == user.id).first()
    if session:
        from datetime import timedelta

        from app.services.session_time import utcnow

        duration_minutes = max(1, min(int(duration_minutes), 24 * 60))
        session.duration_minutes = duration_minutes
        if session.status == "active":
            if not session.starts_at:
                session.starts_at = utcnow()
            session.ends_at = session.starts_at + timedelta(minutes=duration_minutes)
        db.commit()
    return RedirectResponse(f"/teacher/sessions/{session_id}/problems", status_code=303)


@router.post("/sessions/{session_id}/delete")
def delete_session(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.teacher_id == user.id).first()
    if session:
        db.query(LabSubmission).filter(LabSubmission.session_id == session.id).delete()
        db.delete(session)
        db.commit()
    return RedirectResponse("/teacher/", status_code=303)


@router.get("/sessions/{session_id}/problems/add")
def add_problem_page(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.teacher_id == user.id).first()
    if not session:
        return RedirectResponse("/teacher/", status_code=303)
    return render(request, "teacher/add_problem.html", {"user": user, "session": session, "error": None})


@router.post("/sessions/{session_id}/problems/add")
async def add_problem(
    session_id: int,
    request: Request,
    ai_prompt: str = Form(...),
    language: str = Form("python"),
    difficulty: str = Form("easy"),
    rubric_prompt: str = Form(""),
    total_marks: int = Form(10),
    db: Session = Depends(get_db),
):
    wants_json = "application/json" in (request.headers.get("accept") or "")
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.teacher_id == user.id).first()
    if not session:
        if wants_json:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return RedirectResponse("/teacher/", status_code=303)
    try:
        problem_data, rubric_data = await generate_lab_pack(
            ai_prompt, language, difficulty, rubric_prompt, total_marks
        )
        order = db.query(LabProblem).filter(LabProblem.session_id == session.id).count() + 1
        problem = LabProblem(
            session_id=session.id,
            order=order,
            title=problem_data.get("title", "Untitled"),
            description=problem_data.get("description", ""),
            input_format=problem_data.get("input_format", ""),
            output_format=problem_data.get("output_format", ""),
            constraints=problem_data.get("constraints", ""),
            sample_input=problem_data.get("sample_input", ""),
            sample_output=problem_data.get("sample_output", ""),
            language=language,
            difficulty=difficulty,
            test_cases_json=json.dumps(problem_data.get("test_cases") or []),
            rubric_json=json.dumps(rubric_data),
            total_marks=total_marks,
            ai_prompt=ai_prompt,
            rubric_prompt=rubric_prompt,
            rubric_approved=False,
        )
        db.add(problem)
        db.commit()
        redirect_url = f"/teacher/sessions/{session.id}/problems/{problem.id}/review"
        if wants_json:
            return JSONResponse({"ok": True, "redirect_url": redirect_url, "problem_id": problem.id})
        return RedirectResponse(redirect_url, status_code=303)
    except Exception as exc:
        if wants_json:
            return JSONResponse({"error": f"AI generation failed: {exc}"}, status_code=400)
        return render(
            request,
            "teacher/add_problem.html",
            {"user": user, "session": session, "error": f"AI generation failed: {exc}"},
            status_code=400,
        )


@router.get("/sessions/{session_id}/problems/{problem_id}/review")
def review_problem(session_id: int, problem_id: int, request: Request, db: Session = Depends(get_db)):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.teacher_id == user.id).first()
    problem = db.query(LabProblem).filter(LabProblem.id == problem_id, LabProblem.session_id == session_id).first()
    if not session or not problem:
        return RedirectResponse("/teacher/", status_code=303)
    return render(
        request,
        "teacher/review_problem.html",
        {
            "user": user,
            "session": session,
            "problem": problem,
            "rubric": json.loads(problem.rubric_json or "[]"),
            "test_cases": json.loads(problem.test_cases_json or "[]"),
            "message": None,
            "error": None,
        },
    )


@router.post("/sessions/{session_id}/problems/{problem_id}/review")
async def review_problem_post(
    session_id: int,
    problem_id: int,
    request: Request,
    action: str = Form(...),
    title: str = Form(""),
    description: str = Form(""),
    input_format: str = Form(""),
    output_format: str = Form(""),
    constraints: str = Form(""),
    sample_input: str = Form(""),
    sample_output: str = Form(""),
    test_cases_json: str = Form("[]"),
    rubric_json: str = Form("[]"),
    rubric_prompt: str = Form(""),
    db: Session = Depends(get_db),
):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.teacher_id == user.id).first()
    problem = db.query(LabProblem).filter(LabProblem.id == problem_id, LabProblem.session_id == session_id).first()
    if not session or not problem:
        return RedirectResponse("/teacher/", status_code=303)

    message = None
    error = None

    if action == "delete":
        db.delete(problem)
        db.commit()
        return RedirectResponse(f"/teacher/sessions/{session_id}/problems", status_code=303)

    if action == "approve":
        problem.rubric_approved = True
        db.commit()
        return RedirectResponse(f"/teacher/sessions/{session_id}/problems", status_code=303)

    if action == "save_problem":
        problem.title = title.strip() or problem.title
        problem.description = description
        problem.input_format = input_format
        problem.output_format = output_format
        problem.constraints = constraints
        problem.sample_input = sample_input
        problem.sample_output = sample_output
        message = "Problem saved."
        db.commit()

    if action == "save_rubric":
        try:
            rubric = json.loads(rubric_json)
            problem.rubric_json = json.dumps(normalize_rubric(rubric, problem.total_marks))
            problem.rubric_approved = False
            db.commit()
            message = "Rubric saved."
        except Exception:
            error = "Invalid rubric JSON"

    if action == "regenerate_rubric":
        try:
            problem_data = {"title": problem.title, "description": problem.description}
            rubric = await generate_rubric(
                problem_data,
                rubric_prompt or problem.rubric_prompt,
                problem.total_marks,
                problem.language,
            )
            problem.rubric_json = json.dumps(rubric)
            problem.rubric_prompt = rubric_prompt or problem.rubric_prompt
            problem.rubric_approved = False
            db.commit()
            message = "Rubric regenerated."
        except Exception as exc:
            error = f"Regeneration failed: {exc}"

    db.refresh(problem)
    return render(
        request,
        "teacher/review_problem.html",
        {
            "user": user,
            "session": session,
            "problem": problem,
            "rubric": json.loads(problem.rubric_json or "[]"),
            "test_cases": json.loads(problem.test_cases_json or "[]"),
            "message": message,
            "error": error,
        },
    )


@router.get("/sessions/{session_id}/submissions")
def session_submissions(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.teacher_id == user.id).first()
    if not session:
        return RedirectResponse("/teacher/", status_code=303)

    problems = (
        db.query(LabProblem)
        .filter(LabProblem.session_id == session.id)
        .order_by(LabProblem.order.asc(), LabProblem.id.asc())
        .all()
    )
    subs = (
        db.query(LabSubmission)
        .filter(LabSubmission.session_id == session.id, LabSubmission.is_final.is_(True))
        .order_by(LabSubmission.created_at.desc())
        .all()
    )

    by_student: dict[int, dict] = {}
    for sub in subs:
        bucket = by_student.setdefault(
            sub.student_id,
            {"student": sub.student, "by_problem": {}},
        )
        # Keep newest final submission per problem
        if sub.problem_id not in bucket["by_problem"]:
            bucket["by_problem"][sub.problem_id] = sub

    rows = []
    for idx, (_, bucket) in enumerate(
        sorted(by_student.items(), key=lambda item: (item[1]["student"].name or "").lower()),
        start=1,
    ):
        student = bucket["student"]
        cells = []
        awarded_sum = 0.0
        submitted = 0
        for problem in problems:
            sub = bucket["by_problem"].get(problem.id)
            marks = None
            if sub is not None:
                submitted += 1
                if sub.ai_total_marks is not None:
                    marks = float(sub.ai_total_marks)
                elif sub.verdict == "AC":
                    marks = float(problem.total_marks)
                else:
                    marks = 0.0
                awarded_sum += marks
            cells.append({"problem": problem, "sub": sub, "marks": marks})
        avg = round(awarded_sum / len(problems), 1) if problems else 0.0
        rows.append(
            {
                "index": idx,
                "student": student,
                "cells": cells,
                "submitted": submitted,
                "avg": avg,
            }
        )

    return render(
        request,
        "teacher/submissions.html",
        {
            "user": user,
            "session": session,
            "problems": problems,
            "rows": rows,
        },
    )


@router.post("/submissions/{submission_id}/marks")
def override_marks(
    submission_id: int,
    request: Request,
    ai_total_marks: float = Form(...),
    db: Session = Depends(get_db),
):
    user = _teacher_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    sub = db.query(LabSubmission).filter(LabSubmission.id == submission_id).first()
    if not sub:
        return RedirectResponse("/teacher/", status_code=303)
    session = db.query(LabSession).filter(LabSession.id == sub.session_id, LabSession.teacher_id == user.id).first()
    if not session:
        return RedirectResponse("/teacher/", status_code=303)
    sub.ai_total_marks = ai_total_marks
    db.commit()
    return RedirectResponse(f"/teacher/sessions/{session.id}/submissions", status_code=303)
