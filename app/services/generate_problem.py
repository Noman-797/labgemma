from app.services import gemma_client
from app.services.normalize import sanitize_generated_problem
from app.services.prompts import problem_generation_prompt


async def generate_problem(ai_prompt: str, language: str, difficulty: str) -> dict:
    prompt = problem_generation_prompt(ai_prompt, language, difficulty)
    text = await gemma_client.chat([{"role": "user", "content": prompt}], temperature=0.5)
    try:
        data = gemma_client.parse_json(text)
    except Exception:
        text = await gemma_client.chat(
            [
                {"role": "user", "content": prompt},
                {"role": "user", "content": "Your previous reply was invalid. Return ONLY valid JSON."},
            ],
            temperature=0.1,
        )
        data = gemma_client.parse_json(text)
    return sanitize_generated_problem(data)
