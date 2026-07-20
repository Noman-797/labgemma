from app.services import gemma_client
from app.services.normalize import normalize_rubric
from app.services.prompts import rubric_generation_prompt


async def generate_rubric(problem_data: dict, rubric_prompt: str, total_marks: int, language: str) -> list:
    prompt = rubric_generation_prompt(problem_data, rubric_prompt, total_marks, language)
    text = await gemma_client.chat([{"role": "user", "content": prompt}], temperature=0.3)
    try:
        rubric = gemma_client.parse_json(text)
    except Exception:
        text = await gemma_client.chat(
            [
                {"role": "user", "content": prompt},
                {"role": "user", "content": "Return ONLY a valid JSON array of rubric criteria."},
            ],
            temperature=0.1,
        )
        rubric = gemma_client.parse_json(text)
    return normalize_rubric(rubric, total_marks)
