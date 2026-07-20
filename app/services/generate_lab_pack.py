from app.services import gemma_client
from app.services.normalize import normalize_rubric, sanitize_generated_problem
from app.services.prompts import lab_pack_prompt


async def generate_lab_pack(
    ai_prompt: str,
    language: str,
    difficulty: str,
    rubric_prompt: str,
    total_marks: int,
) -> tuple[dict, list]:
    """One Gemma call → problem + rubric (faster than two sequential calls)."""
    prompt = lab_pack_prompt(ai_prompt, language, difficulty, rubric_prompt, total_marks)
    text = await gemma_client.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.4,
        max_tokens=2200,
    )
    try:
        data = gemma_client.parse_json(text)
    except Exception:
        text = await gemma_client.chat(
            [
                {"role": "user", "content": prompt},
                {"role": "user", "content": "Invalid JSON. Return ONLY the JSON object with keys problem and rubric."},
            ],
            temperature=0.1,
            max_tokens=2200,
        )
        data = gemma_client.parse_json(text)

    if not isinstance(data, dict):
        raise ValueError("Lab pack response was not a JSON object")

    problem = data.get("problem") or data
    rubric = data.get("rubric")
    if rubric is None and "criterion" in str(data):
        # accidental flat shape
        rubric = data.get("rubric") or []

    if not isinstance(problem, dict):
        raise ValueError("Missing problem object in lab pack")
    if not isinstance(rubric, list):
        # Fallback: empty rubric then normalize will fail — ask caller to regenerate
        raise ValueError("Missing rubric array in lab pack")

    problem = sanitize_generated_problem(problem)
    rubric = normalize_rubric(rubric, total_marks)
    return problem, rubric
