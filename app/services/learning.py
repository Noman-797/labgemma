"""Personalized learning: analyze past labs + generate practice with Gemma."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import LabSubmission, LearningProfile, PracticeProblem, PracticeSubmission, User
from app.services import gemma_client
from app.services.normalize import normalize_rubric, sanitize_generated_problem
from app.services.prompts import learning_analysis_prompt, practice_pack_prompt


def build_lab_history(db: Session, student: User) -> list[dict]:
    """Compact history of final lab submissions for Gemma analysis."""
    subs = (
        db.query(LabSubmission)
        .filter(LabSubmission.student_id == student.id, LabSubmission.is_final.is_(True))
        .order_by(LabSubmission.created_at.desc())
        .limit(30)
        .all()
    )
    history = []
    for sub in subs:
        problem = sub.problem
        if not problem:
            continue
        feedback = []
        try:
            feedback = json.loads(sub.ai_feedback_json or "[]")
        except Exception:
            feedback = []
        weak = [
            {
                "criterion": c.get("criterion"),
                "marks": c.get("marks_awarded"),
                "max": c.get("max_marks"),
            }
            for c in feedback
            if isinstance(c, dict)
            and float(c.get("max_marks") or 0) > 0
            and float(c.get("marks_awarded") or 0) < float(c.get("max_marks") or 0) * 0.7
        ]
        total = float(problem.total_marks or 10)
        awarded = float(sub.ai_total_marks) if sub.ai_total_marks is not None else None
        ratio = (awarded / total) if awarded is not None and total else None
        history.append(
            {
                "session": problem.session.title if problem.session else "",
                "problem": problem.title,
                "language": sub.language,
                "verdict": sub.verdict,
                "score": awarded,
                "total_marks": total,
                "score_ratio": round(ratio, 2) if ratio is not None else None,
                "tests_passed": f"{sub.test_cases_passed}/{sub.total_test_cases}",
                "summary": (sub.ai_summary or "")[:240],
                "weak_criteria": weak[:5],
                "needs_practice": bool(
                    sub.verdict != "AC" or (ratio is not None and ratio < 0.8)
                ),
            }
        )
    return history


ALLOWED_RESOURCE_HOSTS = (
    "www.geeksforgeeks.org",
    "geeksforgeeks.org",
    "www.w3schools.com",
    "w3schools.com",
    "www.tutorialspoint.com",
    "tutorialspoint.com",
)

# Curated, known-good links only from GFG / W3Schools / TutorialsPoint.
CURATED_RESOURCES: list[dict] = [
    {
        "title": "Reverse digits of a number",
        "type": "Article",
        "site": "GeeksforGeeks",
        "url": "https://www.geeksforgeeks.org/dsa/write-a-program-to-reverse-digits-of-a-number/",
        "keywords": ("reverse", "digit", "palindrome", "modulo"),
        "why": "Digit reverse with modulo — core for palindrome labs",
    },
    {
        "title": "Python program to reverse a number",
        "type": "Article",
        "site": "GeeksforGeeks",
        "url": "https://www.geeksforgeeks.org/python/python-program-to-reverse-a-number/",
        "keywords": ("reverse", "digit", "python"),
        "why": "Python reverse-number walkthrough",
    },
    {
        "title": "Check if a number is palindrome",
        "type": "Article",
        "site": "GeeksforGeeks",
        "url": "https://www.geeksforgeeks.org/dsa/palindrome-number/",
        "keywords": ("palindrome", "reverse", "digit"),
        "why": "Palindrome number approach used in many labs",
    },
    {
        "title": "Prime numbers",
        "type": "Article",
        "site": "GeeksforGeeks",
        "url": "https://www.geeksforgeeks.org/dsa/prime-numbers/",
        "keywords": ("prime", "primality", "math"),
        "why": "Primality checks and loop boundaries",
    },
    {
        "title": "Python if…else",
        "type": "Tutorial",
        "site": "GeeksforGeeks",
        "url": "https://www.geeksforgeeks.org/python/python-if-else/",
        "keywords": ("condition", "if", "even", "odd", "branch"),
        "why": "Conditionals for even/odd and decision labs",
    },
    {
        "title": "Python while loops",
        "type": "Tutorial",
        "site": "W3Schools",
        "url": "https://www.w3schools.com/python/python_while_loops.asp",
        "keywords": ("loop", "while", "digit", "boundary"),
        "why": "While-loop boundaries for digit and math labs",
    },
    {
        "title": "Python for loops",
        "type": "Tutorial",
        "site": "W3Schools",
        "url": "https://www.w3schools.com/python/python_for_loops.asp",
        "keywords": ("loop", "for", "range", "iteration"),
        "why": "For-loop practice for repeated checks",
    },
    {
        "title": "Python operators",
        "type": "Tutorial",
        "site": "W3Schools",
        "url": "https://www.w3schools.com/python/python_operators.asp",
        "keywords": ("modulo", "operator", "division", "digit", "arithmetic"),
        "why": "Modulo and integer division for digit extraction",
    },
    {
        "title": "Python conditions",
        "type": "Tutorial",
        "site": "W3Schools",
        "url": "https://www.w3schools.com/python/python_conditions.asp",
        "keywords": ("condition", "if", "even", "odd"),
        "why": "If/else for branching problems",
    },
    {
        "title": "C++ while loop",
        "type": "Tutorial",
        "site": "W3Schools",
        "url": "https://www.w3schools.com/cpp/cpp_while_loop.asp",
        "keywords": ("loop", "while", "cpp", "c++"),
        "why": "C++ while loops for digit/math practice",
    },
    {
        "title": "Python loops",
        "type": "Tutorial",
        "site": "TutorialsPoint",
        "url": "https://www.tutorialspoint.com/python/python_loops.htm",
        "keywords": ("loop", "while", "for", "iteration"),
        "why": "Loop types overview on TutorialsPoint",
    },
    {
        "title": "Python if…else statement",
        "type": "Tutorial",
        "site": "TutorialsPoint",
        "url": "https://www.tutorialspoint.com/python/python_if_else.htm",
        "keywords": ("condition", "if", "else", "even", "odd"),
        "why": "Decision statements for checker labs",
    },
    {
        "title": "Python basic operators",
        "type": "Tutorial",
        "site": "TutorialsPoint",
        "url": "https://www.tutorialspoint.com/python/python_basic_operators.htm",
        "keywords": ("operator", "modulo", "arithmetic", "digit"),
        "why": "Operators used in reverse and math labs",
    },
    {
        "title": "C++ loop types",
        "type": "Tutorial",
        "site": "TutorialsPoint",
        "url": "https://www.tutorialspoint.com/cplusplus/cpp_loop_types.htm",
        "keywords": ("loop", "cpp", "c++", "for", "while"),
        "why": "C++ loop patterns for practice problems",
    },
    {
        "title": "Java loop control",
        "type": "Tutorial",
        "site": "TutorialsPoint",
        "url": "https://www.tutorialspoint.com/java/java_loop_control.htm",
        "keywords": ("loop", "java", "for", "while"),
        "why": "Java loops for digit and primality practice",
    },
]


def _valid_resource_url(url: str) -> bool:
    try:
        parsed = urlparse((url or "").strip())
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host_key = host
        else:
            host_key = host
        allowed = host_key in ALLOWED_RESOURCE_HOSTS or host in ALLOWED_RESOURCE_HOSTS
        return (
            parsed.scheme in ("http", "https")
            and allowed
            and bool(parsed.path)
            and " " not in (url or "")
        )
    except Exception:
        return False


def _topic_blob(weak_topics: list, history: list[dict]) -> str:
    parts = [str(t).lower() for t in (weak_topics or [])]
    for h in history or []:
        parts.append(str(h.get("problem") or "").lower())
        parts.append(str(h.get("summary") or "").lower())
        parts.append(str(h.get("language") or "").lower())
    return " ".join(parts)


def _score_resource(item: dict, blob: str) -> int:
    score = 0
    for kw in item.get("keywords") or ():
        if kw in blob:
            score += 2
    return score


def resolve_learning_resources(
    *,
    raw: list,
    weak_topics: list,
    history: list[dict],
    min_count: int = 4,
) -> list[dict]:
    """Keep only GFG / W3Schools / TutorialsPoint URLs; pad from curated catalog."""
    chosen: list[dict] = []
    seen_urls: set[str] = set()

    def _add(item: dict) -> None:
        url = item["url"]
        if url in seen_urls:
            return
        chosen.append(
            {
                "title": item["title"][:200],
                "type": str(item.get("type") or "Tutorial")[:40],
                "url": url,
                "why": str(item.get("why") or "").strip()[:400],
            }
        )
        seen_urls.add(url)

    for item in raw or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        if not title or not _valid_resource_url(url):
            continue
        _add(
            {
                "title": title,
                "type": item.get("type") or "Tutorial",
                "url": url,
                "why": item.get("why") or "",
            }
        )

    blob = _topic_blob(weak_topics, history)
    ranked = sorted(
        CURATED_RESOURCES,
        key=lambda r: _score_resource(r, blob),
        reverse=True,
    )

    # Prefer a mix: at least one from each allowed site when possible
    site_hosts = {
        "GeeksforGeeks": "geeksforgeeks.org",
        "W3Schools": "w3schools.com",
        "TutorialsPoint": "tutorialspoint.com",
    }

    def _has_site(site: str) -> bool:
        host_frag = site_hosts[site]
        return any(host_frag in (urlparse(c["url"]).netloc or "") for c in chosen)

    for site in ("GeeksforGeeks", "W3Schools", "TutorialsPoint"):
        if _has_site(site):
            continue
        for item in ranked:
            if item.get("site") == site and item["url"] not in seen_urls:
                _add(item)
                break

    for item in ranked:
        if len(chosen) >= max(min_count, 4):
            break
        _add(item)

    if len(chosen) < min_count:
        for item in CURATED_RESOURCES:
            if len(chosen) >= min_count:
                break
            _add(item)

    return chosen[:6]


def _normalize_suggestions(raw: list, history: list[dict]) -> list[dict]:
    default_lang = "python"
    if history:
        lang = str(history[0].get("language") or "python").lower()
        if lang in ("python", "cpp", "c", "java"):
            default_lang = lang

    out: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        focus = str(item.get("focus_topic") or item.get("title") or "").strip() or title
        based = str(item.get("based_on") or "").strip()
        if not based and history:
            based = str(history[0].get("problem") or "Your recent labs")
        diff = str(item.get("difficulty") or "easy").lower().strip()
        if diff not in ("easy", "medium", "hard"):
            diff = "easy"
        lang = str(item.get("language") or default_lang).lower().strip()
        if lang not in ("python", "cpp", "c", "java"):
            lang = default_lang
        out.append(
            {
                "title": title[:200],
                "focus_topic": focus[:200],
                "based_on": based[:300],
                "difficulty": diff,
                "language": lang,
                "reason": str(item.get("reason") or "").strip()[:400],
            }
        )
    return out


async def analyze_student_learning(history: list[dict]) -> dict:
    if not history:
        return {
            "strong_topics": [],
            "weak_topics": [],
            "study_recommendations": [
                "Solve at least one lab first. Personalized suggestions will appear from your results."
            ],
            "suggested_problems": [],
            "learning_resources": [],
            "overall_summary": "No lab history yet. Enter a live lab and submit to unlock personalized learning.",
        }

    prompt = learning_analysis_prompt(history)
    text = await gemma_client.chat([{"role": "user", "content": prompt}], temperature=0.3, max_tokens=2400)
    data = gemma_client.parse_json(text)
    if not isinstance(data, dict):
        raise ValueError("Learning analysis was not a JSON object")
    data.setdefault("strong_topics", [])
    data.setdefault("weak_topics", [])
    data.setdefault("study_recommendations", [])
    data.setdefault("suggested_problems", [])
    data.setdefault("learning_resources", [])
    data.setdefault("overall_summary", "")

    data["suggested_problems"] = _normalize_suggestions(data.get("suggested_problems") or [], history)
    data["learning_resources"] = []
    return data


def save_learning_profile(db: Session, student: User, analysis: dict) -> LearningProfile:
    profile = db.query(LearningProfile).filter(LearningProfile.student_id == student.id).first()
    payload = json.dumps(analysis, ensure_ascii=False)
    if not profile:
        profile = LearningProfile(student_id=student.id, analysis_json=payload, updated_at=datetime.utcnow())
        db.add(profile)
    else:
        profile.analysis_json = payload
        profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    return profile


def load_learning_profile(db: Session, student: User) -> dict | None:
    profile = db.query(LearningProfile).filter(LearningProfile.student_id == student.id).first()
    if not profile:
        return None
    try:
        data = json.loads(profile.analysis_json or "{}")
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def list_practice_problems(db: Session, student: User) -> list[PracticeProblem]:
    return (
        db.query(PracticeProblem)
        .filter(PracticeProblem.student_id == student.id)
        .order_by(PracticeProblem.created_at.desc())
        .limit(12)
        .all()
    )


async def generate_practice_problem(
    *,
    focus_topic: str,
    based_on: str,
    history: list[dict],
    language: str,
    difficulty: str = "easy",
    total_marks: int = 10,
) -> tuple[dict, list]:
    prompt = practice_pack_prompt(
        focus_topic=focus_topic,
        based_on=based_on,
        history=history[:8],
        language=language,
        difficulty=difficulty,
        total_marks=total_marks,
    )
    text = await gemma_client.chat([{"role": "user", "content": prompt}], temperature=0.4, max_tokens=2000)
    data = gemma_client.parse_json(text)
    if not isinstance(data, dict):
        raise ValueError("Practice pack was not a JSON object")
    problem = data.get("problem") or data
    rubric = data.get("rubric")
    if not isinstance(problem, dict):
        raise ValueError("Missing practice problem object")
    if not isinstance(rubric, list):
        raise ValueError("Missing practice rubric")
    problem = sanitize_generated_problem(problem)
    rubric = normalize_rubric(rubric, total_marks)
    return problem, rubric


def create_practice_from_pack(
    db: Session,
    student: User,
    *,
    problem: dict,
    rubric: list,
    language: str,
    difficulty: str,
    focus_topic: str,
    based_on: str,
    total_marks: int = 10,
    preferred_title: str | None = None,
) -> PracticeProblem:
    title = preferred_title or str(problem.get("title") or focus_topic or "Practice")
    row = PracticeProblem(
        student_id=student.id,
        title=title[:200],
        description=str(problem.get("description") or ""),
        input_format=str(problem.get("input_format") or ""),
        output_format=str(problem.get("output_format") or ""),
        constraints=str(problem.get("constraints") or ""),
        sample_input=str(problem.get("sample_input") or ""),
        sample_output=str(problem.get("sample_output") or ""),
        language=language,
        difficulty=difficulty,
        test_cases_json=json.dumps(problem.get("test_cases") or []),
        rubric_json=json.dumps(rubric),
        total_marks=total_marks,
        focus_topic=focus_topic,
        based_on=based_on,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _clear_unattempted_practice(db: Session, student: User) -> None:
    """Drop practice problems the student never submitted, so refresh can replace them."""
    rows = db.query(PracticeProblem).filter(PracticeProblem.student_id == student.id).all()
    for row in rows:
        has_sub = (
            db.query(PracticeSubmission.id)
            .filter(PracticeSubmission.practice_id == row.id)
            .first()
        )
        if not has_sub:
            db.delete(row)
    db.commit()


async def materialize_practice_suggestions(
    db: Session,
    student: User,
    *,
    suggestions: list[dict],
    history: list[dict],
    limit: int = 4,
) -> list[PracticeProblem]:
    """Turn Gemma suggestion ideas into real LabGemma practice problems."""
    ideas = (suggestions or [])[: max(limit, 4)]
    if not ideas:
        return []

    _clear_unattempted_practice(db, student)

    async def _one(idea: dict) -> tuple[dict, list, dict]:
        problem, rubric = await generate_practice_problem(
            focus_topic=idea["focus_topic"],
            based_on=idea["based_on"],
            history=history,
            language=idea["language"],
            difficulty=idea["difficulty"],
            total_marks=10,
        )
        return problem, rubric, idea

    packs = await asyncio.gather(*[_one(idea) for idea in ideas], return_exceptions=True)
    created: list[PracticeProblem] = []
    for pack in packs:
        if isinstance(pack, Exception):
            continue
        problem, rubric, idea = pack
        created.append(
            create_practice_from_pack(
                db,
                student,
                problem=problem,
                rubric=rubric,
                language=idea["language"],
                difficulty=idea["difficulty"],
                focus_topic=idea["focus_topic"],
                based_on=idea["based_on"],
                total_marks=10,
                preferred_title=idea.get("title"),
            )
        )
    return created
