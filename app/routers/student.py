import json

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import SessionLocal, get_db
from app.models import LabProblem, LabSession, LabSubmission, User
from app.services.grade_pipeline import dumps, full_marks_ai, grade_ai_partial, is_engine_ac
from app.services.lightweight_judge import run_judge
from app.services.session_time import ends_at_iso, ensure_timer, expire_if_needed
from app.templating import render

router = APIRouter(tags=["student"])


async def _finish_ai_grading(submission_id: int) -> None:
    """Background: run Gemma partial marking after a failed/partial engine run."""
    db = SessionLocal()
    try:
        sub = db.query(LabSubmission).filter(LabSubmission.id == submission_id).first()
        if not sub:
            return
        problem = sub.problem
        if not problem:
            return
        raw = {}
        try:
            raw = json.loads(sub.agent_raw_json or "{}")
        except Exception:
            raw = {}
        if raw.get("path") != "ai_pending":
            return

        judge_result = raw.get("judge") or {
            "verdict": sub.verdict,
            "test_cases_passed": sub.test_cases_passed,
            "total_test_cases": sub.total_test_cases,
            "execution_time": sub.execution_time,
            "compilation_error": sub.compilation_error,
            "runtime_error": sub.runtime_error,
        }
        pack = await grade_ai_partial(
            code=sub.code,
            language=sub.language,
            problem_data={"title": problem.title, "description": problem.description},
            rubric=json.loads(problem.rubric_json or "[]"),
            total_marks=problem.total_marks,
            judge_result=judge_result,
        )
        ai = pack["ai"] or {}
        engine_verdict = str(judge_result.get("verdict") or "RE").upper()
        path = (pack.get("agent_raw") or {}).get("path") or "judge_then_ai"
        if path == "judge_then_ai" and engine_verdict in ("SKIPPED", "AI"):
            stored_verdict = "AI"
        else:
            stored_verdict = engine_verdict

        sub.verdict = stored_verdict
        sub.ai_feedback_json = dumps(ai.get("criteria_feedback") or [])
        sub.ai_total_marks = ai.get("total_marks_awarded")
        sub.ai_summary = ai.get("summary")
        sub.verification_notes_json = dumps(ai.get("verification_notes") or [])
        sub.agent_raw_json = dumps(pack.get("agent_raw") or {})
        db.commit()
    except Exception as exc:
        try:
            sub = db.query(LabSubmission).filter(LabSubmission.id == submission_id).first()
            if sub:
                raw = {}
                try:
                    raw = json.loads(sub.agent_raw_json or "{}")
                except Exception:
                    raw = {}
                raw["path"] = "ai_failed"
                raw["error"] = str(exc)[:500]
                sub.agent_raw_json = dumps(raw)
                sub.ai_summary = "AI grading failed. Ask your teacher to recheck."
                sub.ai_total_marks = sub.ai_total_marks if sub.ai_total_marks is not None else 0.0
                sub.ai_feedback_json = sub.ai_feedback_json or "[]"
                sub.verification_notes_json = dumps([f"AI grading error: {exc}"])
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def _student_or_redirect(request: Request, db: Session) -> User | RedirectResponse:
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role != "student":
        return RedirectResponse("/teacher/", status_code=303)
    return user


def _has_student_id(user: User) -> bool:
    return bool((user.student_id or "").strip())


def _require_student_id(user: User) -> RedirectResponse | None:
    """Block lab join until Student ID is set on profile."""
    if _has_student_id(user):
        return None
    return RedirectResponse("/profile?need_id=1", status_code=303)


def _sample_test_cases(problem: LabProblem) -> list[dict]:
    """Build cases for the Sample Test button (sample I/O first, else stored suite)."""
    sample_in = (problem.sample_input or "").strip("\n")
    sample_out = (problem.sample_output or "").strip("\n")
    if sample_out or sample_in:
        return [{"input": sample_in, "output": sample_out}]
    return json.loads(problem.test_cases_json or "[]")


@router.get("/lab/")
def student_lab_list(request: Request, db: Session = Depends(get_db)):
    user = _student_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user

    # Auto-end expired live labs
    for s in db.query(LabSession).filter(LabSession.status == "active").all():
        expire_if_needed(s, db)

    def pack(sessions):
        items = []
        for s in sessions:
            problem_count = (
                db.query(LabProblem)
                .filter(LabProblem.session_id == s.id, LabProblem.rubric_approved.is_(True))
                .count()
            )
            items.append(
                {
                    "session": s,
                    "problem_count": problem_count,
                    "ends_at_iso": ends_at_iso(s),
                    "duration_minutes": s.duration_minutes,
                }
            )
        return items

    upcoming = pack(
        db.query(LabSession).filter(LabSession.status == "draft").order_by(LabSession.created_at.desc()).all()
    )
    live = pack(
        db.query(LabSession).filter(LabSession.status == "active").order_by(LabSession.created_at.desc()).all()
    )
    past = pack(
        db.query(LabSession).filter(LabSession.status == "closed").order_by(LabSession.created_at.desc()).all()
    )
    return render(
        request,
        "student/lab_list.html",
        {
            "user": user,
            "upcoming": upcoming,
            "live": live,
            "past": past,
            "has_student_id": _has_student_id(user),
        },
    )


@router.get("/lab/{session_id}/")
def session_detail(session_id: int, request: Request, db: Session = Depends(get_db)):
    user = _student_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = (
        db.query(LabSession)
        .filter(LabSession.id == session_id, LabSession.status.in_(("draft", "active", "closed")))
        .first()
    )
    if not session:
        return RedirectResponse("/lab/", status_code=303)
    # Joining a live lab requires Student ID; upcoming/past view still allowed to browse
    if session.status == "active":
        blocked = _require_student_id(user)
        if blocked:
            return blocked
    if expire_if_needed(session, db):
        db.refresh(session)
    problems = (
        db.query(LabProblem)
        .filter(LabProblem.session_id == session.id, LabProblem.rubric_approved.is_(True))
        .order_by(LabProblem.order)
        .all()
    )
    finals = {
        s.problem_id: s
        for s in db.query(LabSubmission)
        .filter(
            LabSubmission.student_id == user.id,
            LabSubmission.session_id == session.id,
            LabSubmission.is_final.is_(True),
        )
        .all()
    }
    return render(
        request,
        "student/session_detail.html",
        {
            "user": user,
            "session": session,
            "problems": problems,
            "finals": finals,
            "can_solve": session.status == "active",
            "ends_at_iso": ends_at_iso(session),
        },
    )


@router.get("/lab/{session_id}/problem/{problem_id}/")
def solve_problem(session_id: int, problem_id: int, request: Request, db: Session = Depends(get_db)):
    user = _student_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    session = (
        db.query(LabSession)
        .filter(LabSession.id == session_id, LabSession.status.in_(("active", "closed", "draft")))
        .first()
    )
    if session and session.status == "active":
        ensure_timer(session)
        db.commit()
        if expire_if_needed(session, db):
            db.refresh(session)
    problem = (
        db.query(LabProblem)
        .filter(
            LabProblem.id == problem_id,
            LabProblem.session_id == session_id,
            LabProblem.rubric_approved.is_(True),
        )
        .first()
    )
    if not session or not problem:
        return RedirectResponse("/lab/", status_code=303)
    if session.status == "active":
        blocked = _require_student_id(user)
        if blocked:
            return blocked
    # Upcoming: view statement only; Live: solve; Past: review statement + result
    if session.status == "draft":
        # allow peek at statement
        pass
    elif session.status == "closed":
        pass
    elif session.status != "active":
        return RedirectResponse("/lab/", status_code=303)

    final = (
        db.query(LabSubmission)
        .filter(
            LabSubmission.student_id == user.id,
            LabSubmission.problem_id == problem.id,
            LabSubmission.is_final.is_(True),
        )
        .first()
    )
    can_edit = session.status == "active" and final is None
    return render(
        request,
        "student/solve.html",
        {
            "user": user,
            "session": session,
            "problem": problem,
            "final_submission": final,
            "existing_code_json": json.dumps(final.code) if final else "null",
            "ends_at_iso": ends_at_iso(session) if session.status == "active" else None,
            "can_edit": can_edit,
        },
    )


@router.post("/lab/{session_id}/problem/{problem_id}/test")
async def test_code(session_id: int, problem_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "student":
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if not _has_student_id(user):
        return JSONResponse(
            {"error": "Enter Your Student ID"},
            status_code=403,
        )
    problem = (
        db.query(LabProblem)
        .filter(
            LabProblem.id == problem_id,
            LabProblem.session_id == session_id,
            LabProblem.rubric_approved.is_(True),
        )
        .first()
    )
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.status == "active").first()
    if not problem or not session:
        return JSONResponse({"error": "Not found"}, status_code=404)
    body = await request.json()
    code = (body.get("code") or "").strip()
    language = body.get("language") or problem.language
    if not code:
        return JSONResponse(
            {
                "verdict": "CE",
                "error_message": "No code provided",
                "test_cases_passed": 0,
                "total_test_cases": 0,
            }
        )
    # Sample Test: prefer problem sample I/O; else fall back to stored suite
    sample_cases = _sample_test_cases(problem)
    j = run_judge(code, language, sample_cases)
    return JSONResponse(
        {
            "verdict": j["verdict"],
            "test_cases_passed": j["test_cases_passed"],
            "total_test_cases": j["total_test_cases"],
            "execution_time": j.get("execution_time") or 0,
            "error_message": j.get("compilation_error") or j.get("runtime_error"),
        }
    )


@router.post("/lab/{session_id}/problem/{problem_id}/submit")
async def submit_final(
    session_id: int,
    problem_id: int,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or user.role != "student":
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    if not _has_student_id(user):
        return JSONResponse(
            {"error": "Enter Your Student ID"},
            status_code=403,
        )
    problem = (
        db.query(LabProblem)
        .filter(
            LabProblem.id == problem_id,
            LabProblem.session_id == session_id,
            LabProblem.rubric_approved.is_(True),
        )
        .first()
    )
    session = db.query(LabSession).filter(LabSession.id == session_id, LabSession.status == "active").first()
    if not problem or not session:
        return JSONResponse({"error": "Not found"}, status_code=404)
    if expire_if_needed(session, db):
        return JSONResponse({"error": "Lab time is over"}, status_code=400)

    existing = (
        db.query(LabSubmission)
        .filter(
            LabSubmission.student_id == user.id,
            LabSubmission.problem_id == problem.id,
            LabSubmission.is_final.is_(True),
        )
        .first()
    )
    if existing:
        return JSONResponse({"error": "Already submitted", "submission_id": existing.id}, status_code=400)

    body = await request.json()
    code = (body.get("code") or "").strip()
    language = body.get("language") or problem.language
    if not code:
        return JSONResponse({"error": "No code provided"}, status_code=400)

    cases = json.loads(problem.test_cases_json or "[]")
    rubric = json.loads(problem.rubric_json or "[]")

    # Fast path: engine only first
    j = run_judge(code, language, cases)
    if is_engine_ac(j):
        ai = full_marks_ai(rubric, problem.total_marks)
        sub = LabSubmission(
            session_id=session.id,
            problem_id=problem.id,
            student_id=user.id,
            code=code,
            language=language,
            verdict="AC",
            test_cases_passed=j.get("test_cases_passed") or 0,
            total_test_cases=j.get("total_test_cases") or 0,
            execution_time=j.get("execution_time"),
            compilation_error=j.get("compilation_error"),
            runtime_error=j.get("runtime_error"),
            is_final=True,
            ai_feedback_json=dumps(ai.get("criteria_feedback") or []),
            ai_total_marks=ai.get("total_marks_awarded"),
            ai_summary=ai.get("summary"),
            verification_notes_json=dumps(ai.get("verification_notes") or []),
            agent_raw_json=dumps({"path": "engine_ac", "judge": j}),
        )
        db.add(sub)
        db.commit()
        return JSONResponse(
            {
                "verdict": "AC",
                "status": "done",
                "submission_id": sub.id,
                "ai_total_marks": sub.ai_total_marks,
                "test_cases_passed": sub.test_cases_passed,
                "total_test_cases": sub.total_test_cases,
                "execution_time": sub.execution_time or 0,
                "error_message": None,
                "path": "engine_ac",
                "ai_graded": False,
                "ai_pending": False,
                "redirect_url": None,
                "problems_url": f"/lab/{session.id}/",
            }
        )

    # Wrong / partial / skipped → save now, jump to AI page immediately, grade in background
    engine_verdict = str(j.get("verdict") or "RE").upper()
    stored_verdict = "AI" if engine_verdict == "SKIPPED" else engine_verdict
    sub = LabSubmission(
        session_id=session.id,
        problem_id=problem.id,
        student_id=user.id,
        code=code,
        language=language,
        verdict=stored_verdict,
        test_cases_passed=j.get("test_cases_passed") or 0,
        total_test_cases=j.get("total_test_cases") or 0,
        execution_time=j.get("execution_time"),
        compilation_error=j.get("compilation_error"),
        runtime_error=j.get("runtime_error"),
        is_final=True,
        ai_feedback_json="[]",
        ai_total_marks=None,
        ai_summary=None,
        verification_notes_json="[]",
        agent_raw_json=dumps({"path": "ai_pending", "judge": j}),
    )
    db.add(sub)
    db.commit()
    background_tasks.add_task(_finish_ai_grading, sub.id)

    return JSONResponse(
        {
            "verdict": sub.verdict,
            "status": "ai_pending",
            "submission_id": sub.id,
            "ai_total_marks": None,
            "test_cases_passed": sub.test_cases_passed,
            "total_test_cases": sub.total_test_cases,
            "execution_time": sub.execution_time or 0,
            "error_message": sub.compilation_error or sub.runtime_error,
            "path": "ai_pending",
            "ai_graded": True,
            "ai_pending": True,
            "redirect_url": f"/lab/result/{sub.id}/",
            "problems_url": f"/lab/{session.id}/",
        }
    )


@router.get("/lab/result/{submission_id}/status")
def lab_result_status(submission_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "student":
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    sub = (
        db.query(LabSubmission)
        .filter(LabSubmission.id == submission_id, LabSubmission.student_id == user.id)
        .first()
    )
    if not sub:
        return JSONResponse({"error": "Not found"}, status_code=404)
    raw = {}
    try:
        raw = json.loads(sub.agent_raw_json or "{}")
    except Exception:
        raw = {}
    path = raw.get("path")
    pending = path == "ai_pending"
    failed = path == "ai_failed"
    return JSONResponse(
        {
            "status": "pending" if pending else ("failed" if failed else "done"),
            "verdict": sub.verdict,
            "ai_total_marks": sub.ai_total_marks,
            "path": path,
        }
    )


@router.get("/lab/result/{submission_id}/")
def lab_result(submission_id: int, request: Request, db: Session = Depends(get_db)):
    user = _student_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    sub = (
        db.query(LabSubmission)
        .filter(LabSubmission.id == submission_id, LabSubmission.student_id == user.id)
        .first()
    )
    if not sub:
        return RedirectResponse("/lab/", status_code=303)
    raw = {}
    try:
        raw = json.loads(sub.agent_raw_json or "{}")
    except Exception:
        raw = {}
    if sub.verdict == "AC" and (raw.get("path") == "engine_ac" or (
        sub.total_test_cases > 0 and sub.test_cases_passed >= sub.total_test_cases
    )):
        return RedirectResponse(f"/lab/{sub.session_id}/", status_code=303)

    pending = raw.get("path") == "ai_pending"
    feedback = json.loads(sub.ai_feedback_json or "[]")
    notes = json.loads(sub.verification_notes_json or "[]")
    return render(
        request,
        "student/result.html",
        {
            "user": user,
            "submission": sub,
            "problem": sub.problem,
            "session": sub.session,
            "feedback": feedback,
            "verification_notes": notes,
            "ai_pending": pending,
        },
    )
