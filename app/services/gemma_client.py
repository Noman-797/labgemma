"""Gemma-only LLM client. Supports MOCK_GEMMA for offline demos."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import get_settings


class GemmaError(RuntimeError):
    pass


async def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 4096,
) -> str:
    settings = get_settings()
    if settings.mock_gemma:
        return _mock_reply(messages)

    if not settings.gemma_api_key:
        raise GemmaError("GEMMA_API_KEY is not set. Add it to .env or enable MOCK_GEMMA=1.")

    url = settings.gemma_api_base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.gemma_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.gemma_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # NVIDIA NIM / large Gemma can be slow on cold start
    timeout = httpx.Timeout(connect=30.0, read=300.0, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise GemmaError(f"Gemma API {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        try:
            msg = data["choices"][0]["message"]
            content = msg.get("content")
            if content is None or str(content).strip() == "":
                # Some models put text in reasoning/refusal fields
                content = msg.get("reasoning_content") or msg.get("refusal") or ""
            text = str(content).strip()
            # Gemma 4 thinking channel noise (if present)
            if "<channel|>" in text:
                text = text.split("<channel|>")[-1].strip()
            if "<|channel|>" in text:
                text = text.split("<|channel|>")[-1].strip()
            return text
        except (KeyError, IndexError, TypeError) as exc:
            # Fallback: native Ollama /api/chat shape
            if isinstance(data, dict) and isinstance(data.get("message"), dict):
                return str(data["message"].get("content") or "").strip()
            raise GemmaError(f"Unexpected Gemma response shape: {data}") from exc


def parse_json(text: str) -> Any:
    raw = text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.lstrip().startswith("json"):
            raw = raw.lstrip()[4:]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", raw)
        if not match:
            raise
        return json.loads(match.group(1))


def _mock_reply(messages: list[dict[str, str]]) -> str:
    joined = "\n".join(m.get("content", "") for m in messages).lower()

    if "very short blurbs" in joined or "max 18 words" in joined or "short classroom notes" in joined:
        return "Practice array creation, indexing, and simple loop-based processing."

    if "both a complete problem and a marking rubric" in joined or '"problem"' in joined and '"rubric"' in joined and "total marks for rubric" in joined:
        return json.dumps(
            {
                "problem": {
                    "title": "Even Numbers",
                    "description": "Read an integer n. Print whether it is even or odd.",
                    "input_format": "A single integer n",
                    "output_format": "even or odd",
                    "constraints": "1 <= n <= 1000",
                    "sample_input": "4",
                    "sample_output": "even",
                    "test_cases": [
                        {"input": "4", "output": "even"},
                        {"input": "3", "output": "odd"},
                        {"input": "10", "output": "even"},
                    ],
                },
                "rubric": [
                    {"criterion": "Input handling", "marks": 2, "description": "Reads n"},
                    {"criterion": "Even/odd logic", "marks": 6, "description": "Correct modulo check"},
                    {"criterion": "Output", "marks": 2, "description": "Prints even/odd"},
                ],
            }
        )

    # Order matters: most specific agent roles first.
    if "consistency judge" in joined or "verification_notes" in joined:
        return json.dumps(
            {
                "criteria_feedback": [
                    {
                        "criterion": "Input handling",
                        "marks_awarded": 0,
                        "max_marks": 2,
                        "explanation": "No reliable input handling in failed run.",
                        "evidence": [],
                    },
                    {
                        "criterion": "Core logic",
                        "marks_awarded": 1,
                        "max_marks": 5,
                        "explanation": "Minimal logic; tests failed.",
                        "evidence": ["print(1)"],
                    },
                    {
                        "criterion": "Output formatting",
                        "marks_awarded": 0,
                        "max_marks": 2,
                        "explanation": "Output incorrect vs tests.",
                        "evidence": [],
                    },
                    {
                        "criterion": "Edge cases",
                        "marks_awarded": 0,
                        "max_marks": 1,
                        "explanation": "Not addressed.",
                        "evidence": [],
                    },
                ],
                "total_marks_awarded": 1,
                "summary": "Weak attempt; partial credit for showing some output code.",
                "verification_notes": [
                    "Reduced output marks because judge passed 0 tests.",
                    "Scores clamped to rubric; sum verified.",
                ],
                "confidence": "medium",
            }
        )

    if "evidence agent" in joined or ("for each criterion" in joined and "attach 1-3" in joined):
        return json.dumps(
            {
                "criteria_feedback": [
                    {
                        "criterion": "Input handling",
                        "marks_awarded": 0,
                        "max_marks": 2,
                        "explanation": "No input() found",
                        "evidence": [],
                    },
                    {
                        "criterion": "Core logic",
                        "marks_awarded": 1,
                        "max_marks": 5,
                        "explanation": "Only a print",
                        "evidence": ["print(1)"],
                    },
                    {
                        "criterion": "Output formatting",
                        "marks_awarded": 0,
                        "max_marks": 2,
                        "explanation": "Wrong output",
                        "evidence": ["print(1)"],
                    },
                    {
                        "criterion": "Edge cases",
                        "marks_awarded": 0,
                        "max_marks": 1,
                        "explanation": "No evidence",
                        "evidence": [],
                    },
                ]
            }
        )

    if "expert programming educator grading" in joined:
        return json.dumps(
            {
                "criteria_feedback": [
                    {
                        "criterion": "Input handling",
                        "marks_awarded": 0,
                        "max_marks": 2,
                        "explanation": "Does not read input.",
                    },
                    {
                        "criterion": "Core logic",
                        "marks_awarded": 1,
                        "max_marks": 5,
                        "explanation": "Hardcoded print only.",
                    },
                    {
                        "criterion": "Output formatting",
                        "marks_awarded": 0,
                        "max_marks": 2,
                        "explanation": "Wrong answer on tests.",
                    },
                    {
                        "criterion": "Edge cases",
                        "marks_awarded": 0,
                        "max_marks": 1,
                        "explanation": "Edge cases not handled.",
                    },
                ],
                "total_marks_awarded": 1,
                "summary": "Needs input handling and correct sum logic.",
            }
        )

    if "analyzing a student's lab performance" in joined or "personalized learning" in joined and "strong_topics" in joined:
        return json.dumps(
            {
                "strong_topics": ["Input handling", "Basic loops"],
                "weak_topics": ["Integer reversal", "Palindrome edge cases", "Output formatting"],
                "study_recommendations": [
                    "You should practice reversing digits using modulo and integer division.",
                    "You should try palindrome checks with leading zeros and single-digit numbers.",
                    "You should print exact Yes/No strings without extra spaces.",
                    "You should dry-run loop boundaries on paper before coding.",
                ],
                "suggested_problems": [
                    {
                        "title": "Reverse Digits Practice",
                        "focus_topic": "Integer reversal",
                        "based_on": "Palindrome Number",
                        "difficulty": "easy",
                        "language": "python",
                        "reason": "Builds the reverse logic used in palindrome checks",
                    },
                    {
                        "title": "Palindrome Edge Cases",
                        "focus_topic": "Palindrome edge cases",
                        "based_on": "Palindrome Number",
                        "difficulty": "easy",
                        "language": "python",
                        "reason": "Same core idea as your lab with clearer edge cases",
                    },
                    {
                        "title": "Even Odd Drill",
                        "focus_topic": "Conditionals",
                        "based_on": "Even Odd Checker",
                        "difficulty": "easy",
                        "language": "python",
                        "reason": "Reinforces the conditionals you already got right",
                    },
                    {
                        "title": "Sum of Digits",
                        "focus_topic": "Digit loops",
                        "based_on": "Palindrome Number",
                        "difficulty": "easy",
                        "language": "python",
                        "reason": "Same digit-loop pattern as reverse and palindrome labs",
                    },
                ],
                "learning_resources": [
                    {
                        "title": "Reverse digits of a number",
                        "type": "Article",
                        "url": "https://www.geeksforgeeks.org/dsa/write-a-program-to-reverse-digits-of-a-number/",
                        "why": "Digit reverse with modulo — core for palindrome labs",
                    },
                    {
                        "title": "Python while loops",
                        "type": "Tutorial",
                        "url": "https://www.w3schools.com/python/python_while_loops.asp",
                        "why": "While-loop boundaries for digit and math labs",
                    },
                    {
                        "title": "Python loops",
                        "type": "Tutorial",
                        "url": "https://www.tutorialspoint.com/python/python_loops.htm",
                        "why": "Loop types overview on TutorialsPoint",
                    },
                    {
                        "title": "Python operators",
                        "type": "Tutorial",
                        "url": "https://www.w3schools.com/python/python_operators.asp",
                        "why": "Modulo and integer division for digit extraction",
                    },
                ],
                "overall_summary": (
                    "You handle input well. Next, practice reverse logic in LabGemma and read a short article."
                ),
            }
        )

    if "personalized practice problem" in joined or ("focus topic:" in joined and '"problem"' in joined and '"rubric"' in joined):
        return json.dumps(
            {
                "problem": {
                    "title": "Reverse Digits",
                    "description": "Read an integer n and print its digits reversed. Do not print leading zeros in the result except for 0 itself.",
                    "input_format": "A single integer n",
                    "output_format": "The reversed integer",
                    "constraints": "0 <= n <= 10^9",
                    "sample_input": "1234",
                    "sample_output": "4321",
                    "test_cases": [
                        {"input": "1234", "output": "4321"},
                        {"input": "100", "output": "1"},
                        {"input": "0", "output": "0"},
                    ],
                },
                "rubric": [
                    {"criterion": "Input handling", "marks": 2, "description": "Reads n"},
                    {"criterion": "Reversal logic", "marks": 6, "description": "Correct digit reverse"},
                    {"criterion": "Output", "marks": 2, "description": "Prints reversed value"},
                ],
            }
        )

    if "assessment designer" in joined or "return only a valid json array" in joined:
        return json.dumps(
            [
                {"criterion": "Input handling", "marks": 2, "description": "Reads input correctly"},
                {"criterion": "Core logic", "marks": 5, "description": "Implements the main algorithm"},
                {"criterion": "Output formatting", "marks": 2, "description": "Prints required output"},
                {"criterion": "Edge cases", "marks": 1, "description": "Handles empty/edge inputs"},
            ]
        )

    # Default: problem generation
    return json.dumps(
        {
            "title": "Array Sum",
            "description": (
                "Read an integer n, then n integers. Compute and print their sum.\n\n"
                "This is a basic lab problem to practice input handling and loops/aggregation."
            ),
            "input_format": "First line: n\nSecond line: n space-separated integers",
            "output_format": "A single integer — the sum of the array",
            "constraints": "1 <= n <= 1000\n-1000 <= a_i <= 1000",
            "sample_input": "4\n1 2 3 4",
            "sample_output": "10",
            "test_cases": [
                {"input": "4\n1 2 3 4", "output": "10"},
                {"input": "1\n5", "output": "5"},
                {"input": "3\n-1 0 1", "output": "0"},
            ],
        }
    )
