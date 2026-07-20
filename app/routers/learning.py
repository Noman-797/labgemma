"""Student personalized learning + practice."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import PracticeProblem, PracticeSubmission, User
from app.services.grade_pipeline import full_marks_ai, is_engine_ac
from app.services.learning import (
    analyze_student_learning,
    build_lab_history,
    create_practice_from_pack,
    generate_practice_problem,
    list_practice_problems,
    load_learning_profile,
    materialize_practice_suggestions,
    save_learning_profile,
)
from app.services.lightweight_judge import run_judge
from app.templating import render

router = APIRouter(tags=["learning"])


def _student_or_redirect(request: Request, db: Session) -> User | RedirectResponse:
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user.role != "student":
        return RedirectResponse("/teacher/", status_code=303)
    return user


@router.get("/learning/")
def learning_home(request: Request, db: Session = Depends(get_db)):
    user = _student_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user

    history = build_lab_history(db, user)
    analysis = load_learning_profile(db, user)
    practices = list_practice_problems(db, user)

    return render(
        request,
        "student/learning.html",
        {
            "user": user,
            "history": history,
            "analysis": analysis,
            "practices": practices,
            "history_count": len(history),
            "err": request.query_params.get("err"),
        },
    )


@router.post("/learning/analyze")
async def learning_analyze(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "student":
        return RedirectResponse("/login", status_code=303)
    history = build_lab_history(db, user)
    if not history:
        return RedirectResponse("/learning/?err=Submit+at+least+one+lab+first", status_code=303)
    try:
        analysis = await analyze_student_learning(history)
        save_learning_profile(db, user, analysis)
        await materialize_practice_suggestions(
            db,
            user,
            suggestions=analysis.get("suggested_problems") or [],
            history=history,
            limit=4,
        )
    except Exception as exc:
        return RedirectResponse(f"/learning/?err={str(exc)[:120]}", status_code=303)
    return RedirectResponse("/learning/", status_code=303)


@router.post("/learning/generate-practice")
async def learning_generate_practice(
    request: Request,
    db: Session = Depends(get_db),
    focus_topic: str = Form(""),
    based_on: str = Form(""),
    language: str = Form("python"),
    difficulty: str = Form("easy"),
):
    user = get_current_user(request, db)
    if not user or user.role != "student":
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    history = build_lab_history(db, user)
    if not history:
        return RedirectResponse("/learning/?err=need_history", status_code=303)

    analysis = load_learning_profile(db, user) or {}
    topic = (focus_topic or "").strip()
    based = (based_on or "").strip()
    if not topic:
        weak = analysis.get("weak_topics") or []
        topic = weak[0] if weak else (history[0].get("problem") or "Practice")
    if not based:
        needs = next((h for h in history if h.get("needs_practice")), history[0])
        based = str(needs.get("problem") or "Your recent labs")

    lang = (language or "python").lower().strip()
    if lang not in ("python", "cpp", "c", "java"):
        lang = "python"

    try:
        problem, rubric = await generate_practice_problem(
            focus_topic=topic,
            based_on=based,
            history=history,
            language=lang,
            difficulty=difficulty or "easy",
            total_marks=10,
        )
        row = create_practice_from_pack(
            db,
            user,
            problem=problem,
            rubric=rubric,
            language=lang,
            difficulty=difficulty or "easy",
            focus_topic=topic,
            based_on=based,
            total_marks=10,
        )
    except Exception as exc:
        return RedirectResponse(f"/learning/?err={str(exc)[:80]}", status_code=303)

    return RedirectResponse(f"/learning/practice/{row.id}/", status_code=303)


@router.get("/learning/practice/{practice_id}/")
def practice_solve(practice_id: int, request: Request, db: Session = Depends(get_db)):
    user = _student_or_redirect(request, db)
    if isinstance(user, RedirectResponse):
        return user
    problem = (
        db.query(PracticeProblem)
        .filter(PracticeProblem.id == practice_id, PracticeProblem.student_id == user.id)
        .first()
    )
    if not problem:
        return RedirectResponse("/learning/", status_code=303)
    latest = (
        db.query(PracticeSubmission)
        .filter(PracticeSubmission.practice_id == problem.id, PracticeSubmission.student_id == user.id)
        .order_by(PracticeSubmission.created_at.desc())
        .first()
    )
    return render(
        request,
        "student/practice_solve.html",
        {
            "user": user,
            "problem": problem,
            "latest": latest,
            "existing_code_json": json.dumps(latest.code) if latest else "null",
        },
    )


@router.post("/learning/practice/{practice_id}/test")
async def practice_test(practice_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "student":
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    problem = (
        db.query(PracticeProblem)
        .filter(PracticeProblem.id == practice_id, PracticeProblem.student_id == user.id)
        .first()
    )
    if not problem:
        return JSONResponse({"error": "Not found"}, status_code=404)
    body = await request.json()
    code = (body.get("code") or "").strip()
    language = body.get("language") or problem.language
    if not code:
        return JSONResponse({"verdict": "CE", "error_message": "No code", "test_cases_passed": 0, "total_test_cases": 0})
    sample = [{"input": problem.sample_input or "", "output": problem.sample_output or ""}]
    j = run_judge(code, language, sample)
    return JSONResponse(
        {
            "verdict": j["verdict"],
            "test_cases_passed": j["test_cases_passed"],
            "total_test_cases": j["total_test_cases"],
            "execution_time": j.get("execution_time") or 0,
            "error_message": j.get("compilation_error") or j.get("runtime_error"),
        }
    )


@router.post("/learning/practice/{practice_id}/submit")
async def practice_submit(practice_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or user.role != "student":
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    problem = (
        db.query(PracticeProblem)
        .filter(PracticeProblem.id == practice_id, PracticeProblem.student_id == user.id)
        .first()
    )
    if not problem:
        return JSONResponse({"error": "Not found"}, status_code=404)
    body = await request.json()
    code = (body.get("code") or "").strip()
    language = body.get("language") or problem.language
    if not code:
        return JSONResponse({"error": "No code provided"}, status_code=400)

    cases = json.loads(problem.test_cases_json or "[]")
    rubric = json.loads(problem.rubric_json or "[]")
    j = run_judge(code, language, cases)

    if is_engine_ac(j):
        ai = full_marks_ai(rubric, problem.total_marks)
        summary = "All practice tests passed."
        marks = ai.get("total_marks_awarded")
        verdict = "AC"
    else:
        # Lightweight: score from tests passed ratio against total marks (fast, no long AI wait)
        total_tc = int(j.get("total_test_cases") or 0)
        passed = int(j.get("test_cases_passed") or 0)
        ratio = (passed / total_tc) if total_tc else 0.0
        marks = round(ratio * float(problem.total_marks), 1)
        summary = (
            f"Engine {j.get('verdict')}: {passed}/{total_tc} tests passed. "
            "Open Learning again after more labs for richer Gemma feedback."
        )
        verdict = str(j.get("verdict") or "WA")

    sub = PracticeSubmission(
        practice_id=problem.id,
        student_id=user.id,
        code=code,
        language=language,
        verdict=verdict,
        test_cases_passed=j.get("test_cases_passed") or 0,
        total_test_cases=j.get("total_test_cases") or 0,
        ai_total_marks=marks,
        ai_summary=summary,
    )
    db.add(sub)
    db.commit()
    return JSONResponse(
        {
            "verdict": verdict,
            "status": "done",
            "ai_total_marks": marks,
            "test_cases_passed": sub.test_cases_passed,
            "total_test_cases": sub.total_test_cases,
            "error_message": j.get("compilation_error") or j.get("runtime_error"),
            "summary": summary,
        }
    )
