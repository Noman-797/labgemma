"""Port of Semicolons rubric / AI evaluation normalization."""


def _use_integer_marks(total_marks: float) -> bool:
    return abs(float(total_marks) - round(float(total_marks))) < 1e-9


def _quantize_mark(value: float, total_marks: float) -> float:
    v = max(0.0, float(value))
    if _use_integer_marks(total_marks):
        return float(int(round(v)))
    return round(v * 2) / 2.0


def normalize_rubric(rubric, total_marks):
    if not isinstance(rubric, list) or not rubric:
        return rubric
    total_marks = float(total_marks)
    cleaned = []
    for item in rubric:
        if not isinstance(item, dict):
            continue
        marks = max(0.0, float(item.get("marks") or 0))
        cleaned.append(
            {
                "criterion": str(item.get("criterion") or "Criterion").strip() or "Criterion",
                "marks": marks,
                "description": str(item.get("description") or "").strip(),
            }
        )
    if not cleaned:
        return rubric

    raw = sum(c["marks"] for c in cleaned)
    if raw <= 0:
        if _use_integer_marks(total_marks):
            base = int(total_marks) // len(cleaned)
            rem = int(total_marks) - base * len(cleaned)
            for i, c in enumerate(cleaned):
                c["marks"] = float(base + (1 if i < rem else 0))
        else:
            share = round(total_marks / len(cleaned), 2)
            for c in cleaned:
                c["marks"] = share
            cleaned[-1]["marks"] = round(total_marks - share * (len(cleaned) - 1), 2)
    elif abs(raw - total_marks) > 0.001:
        scale = total_marks / raw
        for c in cleaned:
            c["marks"] = c["marks"] * scale

    if _use_integer_marks(total_marks):
        ints = [int(round(c["marks"])) for c in cleaned]
        drift = int(round(total_marks)) - sum(ints)
        i = 0
        while drift != 0 and cleaned:
            idx = i % len(ints)
            if drift > 0:
                ints[idx] += 1
                drift -= 1
            elif ints[idx] > 0:
                ints[idx] -= 1
                drift += 1
            i += 1
            if i > len(ints) * 20:
                break
        for c, m in zip(cleaned, ints):
            c["marks"] = float(m)
    else:
        running = 0.0
        for c in cleaned[:-1]:
            c["marks"] = _quantize_mark(c["marks"], total_marks)
            running += c["marks"]
        cleaned[-1]["marks"] = _quantize_mark(total_marks - running, total_marks)
    return cleaned


def normalize_ai_evaluation(result, rubric, total_marks, judge_result=None):
    if not isinstance(result, dict):
        return result

    total_marks = float(total_marks)
    rubric = rubric or []
    rubric_max = {}
    for r in rubric:
        if isinstance(r, dict):
            key = str(r.get("criterion") or "").strip().lower()
            if key:
                rubric_max[key] = float(r.get("marks") or 0)

    judge_result = judge_result or {}
    verdict = str(judge_result.get("verdict") or "").upper()
    passed = int(judge_result.get("test_cases_passed") or 0)
    total_tc = int(judge_result.get("total_test_cases") or 0)
    zero_tests = total_tc > 0 and passed == 0
    # Only punish output marks after a real failed engine run — never for SKIPPED
    failed_run = verdict in ("WA", "TLE", "RE", "MLE", "CE") and zero_tests

    output_keywords = (
        "output",
        "correct",
        "correctness",
        "result",
        "testing",
        "test",
        "i/o",
        "io ",
        "print",
        "display",
    )

    criteria = result.get("criteria_feedback") or []
    normalized = []
    for item in criteria:
        if not isinstance(item, dict):
            continue
        name = str(item.get("criterion") or "").strip()
        key = name.lower()
        max_marks = rubric_max.get(key)
        if max_marks is None:
            max_marks = float(item.get("max_marks") or 0)
        awarded = max(0.0, float(item.get("marks_awarded") or 0))
        awarded = min(awarded, max_marks)

        if failed_run and any(k in key for k in output_keywords):
            awarded = 0.0

        awarded = _quantize_mark(awarded, total_marks)
        entry = {
            "criterion": name,
            "marks_awarded": awarded,
            "max_marks": max_marks,
            "explanation": str(item.get("explanation") or "").strip(),
        }
        if "evidence" in item:
            entry["evidence"] = item.get("evidence") or []
        normalized.append(entry)

    # Ensure all rubric criteria present
    seen = {c["criterion"].lower() for c in normalized}
    for r in rubric:
        key = str(r.get("criterion") or "").strip()
        if key and key.lower() not in seen:
            normalized.append(
                {
                    "criterion": key,
                    "marks_awarded": 0.0,
                    "max_marks": float(r.get("marks") or 0),
                    "explanation": "No score returned by model; set to 0.",
                    "evidence": [],
                }
            )

    total = sum(c["marks_awarded"] for c in normalized)
    if total > total_marks:
        scale = total_marks / total if total else 0
        for c in normalized:
            c["marks_awarded"] = _quantize_mark(c["marks_awarded"] * scale, total_marks)
        total = sum(c["marks_awarded"] for c in normalized)
        if total != total_marks and normalized:
            drift = total_marks - total
            normalized[-1]["marks_awarded"] = _quantize_mark(
                max(0, normalized[-1]["marks_awarded"] + drift), total_marks
            )
            total = sum(c["marks_awarded"] for c in normalized)

    result["criteria_feedback"] = normalized
    result["total_marks_awarded"] = _quantize_mark(sum(c["marks_awarded"] for c in normalized), total_marks)
    if "summary" not in result:
        result["summary"] = ""
    return result


def sanitize_generated_problem(data: dict) -> dict:
    if not isinstance(data, dict):
        return data
    none_like = {"none", "n/a", "na", "null", "no input", "noinput", "-"}

    def clean_input(val):
        s = "" if val is None else str(val).strip()
        if s.lower() in none_like:
            return ""
        return s

    data["sample_input"] = clean_input(data.get("sample_input", ""))
    data["sample_output"] = str(data.get("sample_output") or "").strip("\n")
    cases = data.get("test_cases") or []
    cleaned = []
    for tc in cases:
        if not isinstance(tc, dict):
            continue
        cleaned.append(
            {
                "input": clean_input(tc.get("input", "")),
                "output": str(tc.get("output") or "").strip("\n"),
            }
        )
    if cleaned and all(c["input"] == "" for c in cleaned):
        canonical = data["sample_output"] or cleaned[0]["output"]
        data["sample_input"] = ""
        data["sample_output"] = canonical
        cleaned = [{"input": "", "output": canonical}]
    if cleaned:
        data["test_cases"] = cleaned
    return data
