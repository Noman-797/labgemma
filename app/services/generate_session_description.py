from app.services.gemma_client import chat
from app.services.prompts import session_description_prompt


async def generate_session_description(title: str) -> str:
    text = await chat(
        [{"role": "user", "content": session_description_prompt(title.strip())}],
        temperature=0.4,
        max_tokens=60,
    )
    # Keep card blurbs tight even if the model runs long
    cleaned = " ".join(text.strip().strip('"').split())
    words = cleaned.split()
    if len(words) > 22:
        cleaned = " ".join(words[:22]).rstrip(".,;") + "."
    return cleaned
