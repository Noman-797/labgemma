"""Final submit grading: lightweight engine judge + Gemma rubric agents."""

from __future__ import annotations

import json

from app.services import gemma_client
from app.services.lightweight_judge import run_judge
from app.services.normalize import normalize_ai_evaluation
from app.services.prompts import evaluate_code_prompt, judge_final_prompt


def is_engine_ac(judge_result: dict) -> bool:
    total_tc = int(judge_result.get("total_test_cases") or 0)
    passed = int(judge_result.get("test_cases_passed") or 0)
    verdict = str(judge_result.get("verdict") or "").upper()
    return total_tc > 0 and passed >= total_tc and verdict == "AC"


async def grade_submission(
    *,
    code: str,
    language: str,
    problem_data: dict,
    rubric: list,
    test_cases: list,
    total_marks: float,
    sample_only: bool = False,
) -> dict:
    """
    1) Always run the lightweight engine.
    2) Sample Test: judge only.
    3) Final: AC → full marks; else AI partial (prefer async path from the router).
    """
    judge_result = run_judge(code, language, test_cases or [])

    if sample_only:
        return {"judge": judge_result, "ai": None}

    if is_engine_ac(judge_result):
        return {
            "judge": judge_result,
            "ai": full_marks_ai(rubric, total_marks),
            "agent_raw": {"path": "engine_ac", "judge": judge_result},
        }

    ai_pack = await grade_ai_partial(
        code=code,
        language=language,
        problem_data=problem_data,
        rubric=rubric,
        total_marks=total_marks,
        judge_result=judge_result,
    )
    return {
        "judge": judge_result,
        "ai": ai_pack["ai"],
        "agent_raw": ai_pack["agent_raw"],
    }


async def grade_ai_partial(
    *,
    code: str,
    language: str,
    problem_data: dict,
    rubric: list,
    total_marks: float,
    judge_result: dict,
) -> dict:
    """Fast AI path: scorer → consistency (skip separate evidence call for latency)."""
    verdict = str(judge_result.get("verdict") or "").upper()
    passed = int(judge_result.get("test_cases_passed") or 0)
    total_tc = int(judge_result.get("total_test_cases") or 0)

    scorer_prompt = evaluate_code_prompt(code, problem_data, rubric, language, judge_result, total_marks)
    scorer_text = await gemma_client.chat(
        [{"role": "user", "content": scorer_prompt}],
        temperature=0.1,
        max_tokens=1400,
    )
    scorer = gemma_client.parse_json(scorer_text)
    scorer = normalize_ai_evaluation(scorer, rubric, total_marks, judge_result)

    # Ask consistency to also keep short code quotes when possible (avoids a 3rd round-trip)
    final_text = await gemma_client.chat(
        [{"role": "user", "content": judge_final_prompt(rubric, scorer, judge_result, total_marks)}],
        temperature=0.1,
        max_tokens=1400,
    )
    try:
        final = gemma_client.parse_json(final_text)
        if not isinstance(final, dict):
            raise ValueError("Judge returned non-object JSON")
    except Exception:
        final = dict(scorer) if isinstance(scorer, dict) else {"criteria_feedback": []}
        final["verification_notes"] = ["Consistency parse failed — used scorer output."]
        final["confidence"] = "low"

    final = normalize_ai_evaluation(final, rubric, total_marks, judge_result)
    if not isinstance(final, dict):
        final = {"criteria_feedback": [], "total_marks_awarded": 0, "summary": ""}
    if not final.get("verification_notes"):
        notes = [
            f"Engine verdict {verdict}: {passed}/{total_tc} tests passed.",
            "AI rubric scoring applied for partial credit; scores clamped to rubric.",
        ]
        if verdict == "SKIPPED" or total_tc == 0:
            notes = [
                "No runnable test suite for this submission — AI rubric grading only.",
                "Scores clamped to rubric; sum verified.",
            ]
        final["verification_notes"] = notes
    if not final.get("summary"):
        final["summary"] = (scorer.get("summary") if isinstance(scorer, dict) else "") or ""

    return {
        "ai": final,
        "agent_raw": {"scorer": scorer, "judge_final": final, "path": "judge_then_ai", "judge": judge_result},
    }


def full_marks_ai(rubric: list, total_marks: float) -> dict:
    criteria = []
    for item in rubric or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("criterion") or "").strip()
        if not name:
            continue
        max_m = float(item.get("marks") or 0)
        criteria.append(
            {
                "criterion": name,
                "marks_awarded": max_m,
                "max_marks": max_m,
                "explanation": "All engine test cases passed.",
                "evidence": [],
            }
        )
    awarded = sum(c["marks_awarded"] for c in criteria) if criteria else float(total_marks)
    return {
        "criteria_feedback": criteria,
        "total_marks_awarded": float(total_marks) if not criteria else awarded,
        "summary": "All test cases passed.",
        "verification_notes": [
            "Engine AC: every test case passed — full marks awarded without AI scoring.",
        ],
        "confidence": "high",
    }


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
