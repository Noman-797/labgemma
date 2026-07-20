"""Centralized Gemma prompts — Semicolons lab agent roles."""

import json


def session_description_prompt(title: str) -> str:
    return f"""You write very short blurbs for university programming lab session cards.

Session title: {title}

Write ONE short sentence (max 18 words) describing what students practice in this lab.
Rules: plain text only, no markdown, no quotes, do not repeat the title, no "In this lab you will learn".
Example style: "Practice array creation, indexing, and simple loop-based processing."

Return ONLY that one sentence."""


def problem_generation_prompt(ai_prompt: str, language: str, difficulty: str) -> str:
    return f"""You are a programming problem setter for a university lab.

Teacher's instruction: {ai_prompt}
Language: {language}
Difficulty: {difficulty}

Generate a complete programming problem based on the teacher's instruction.
Follow the teacher's instruction closely, especially about whether input is required.

Return ONLY a valid JSON object with this exact structure:
{{
  "title": "Problem title",
  "description": "Full problem description",
  "input_format": "Input format description",
  "output_format": "Output format description",
  "constraints": "Constraints like 1 <= n <= 1000",
  "sample_input": "Sample input",
  "sample_output": "Sample output",
  "test_cases": [
    {{"input": "test input 1", "output": "expected output 1"}},
    {{"input": "test input 2", "output": "expected output 2"}},
    {{"input": "test input 3", "output": "expected output 3"}}
  ]
}}

Include exactly 3 test cases. Make sure test cases are correct and cover edge cases.
If the problem truly needs no input, use "" (not "None") and keep outputs identical to sample_output.
Never use the text "None" as input."""


def lab_pack_prompt(
    ai_prompt: str,
    language: str,
    difficulty: str,
    rubric_prompt: str,
    total_marks: int,
) -> str:
    """Single-call problem + rubric (cuts NVIDIA round-trips in half)."""
    teacher_instruction = (
        f"\nAdditional rubric instruction from teacher: {rubric_prompt.strip()}"
        if rubric_prompt and rubric_prompt.strip()
        else ""
    )
    return f"""You are a programming problem setter AND assessment designer for a university lab.

Teacher's instruction: {ai_prompt}
Language: {language}
Difficulty: {difficulty}
Total marks for rubric: {total_marks}{teacher_instruction}

Create BOTH a complete problem and a marking rubric in ONE response.
Keep descriptions concise (lab-exam length, not a textbook).
Exactly 3 test cases. Never use "None" as input — use "".

Return ONLY a valid JSON object:
{{
  "problem": {{
    "title": "Problem title",
    "description": "Full problem description (concise)",
    "input_format": "Input format",
    "output_format": "Output format",
    "constraints": "Constraints",
    "sample_input": "Sample input",
    "sample_output": "Sample output",
    "test_cases": [
      {{"input": "...", "output": "..."}},
      {{"input": "...", "output": "..."}},
      {{"input": "...", "output": "..."}}
    ]
  }},
  "rubric": [
    {{"criterion": "Step name", "marks": 2, "description": "What to check"}}
  ]
}}

Rules:
- Rubric marks must sum EXACTLY to {total_marks}
- Prefer fewer criteria (3–5) with more weight on core logic
- Match the teacher's problem (e.g. even numbers ≠ array sum)"""


def rubric_generation_prompt(problem_data: dict, rubric_prompt: str, total_marks: int, language: str) -> str:
    teacher_instruction = (
        f"\n\nAdditional instruction from teacher: {rubric_prompt.strip()}"
        if rubric_prompt and rubric_prompt.strip()
        else ""
    )
    return f"""You are an expert programming instructor and assessment designer.

When given a programming problem and total marks, generate a question-specific evaluation rubric.

Instructions:
- Carefully analyze the programming problem before creating the rubric.
- The sum of all rubric marks must be exactly equal to {total_marks}.
- Distribute marks based on complexity and importance of each implementation step.
- Create a step-by-step marking scheme that allows partial marking.

Include only steps actually required for solving the problem, such as:
- Input handling
- Variable/array initialization (if required)
- Loop implementation
- Conditional statements (if required)
- Core algorithm or logic
- Function implementation (if required)
- Output formatting
- Edge case handling (if required)

Guidelines:
- Do NOT use a fixed rubric template.
- Do NOT assign marks to unnecessary criteria.
- Allocate MORE marks to core algorithm/logic than simple tasks like input or output.
- The rubric must be practical for evaluating students in programming lab exams.
- Verify that the total of all marks equals {total_marks}.

Problem Title: {problem_data.get('title')}
Problem Description: {problem_data.get('description')}
Language: {language or 'unspecified'}
Total Marks: {total_marks}{teacher_instruction}

Return ONLY a valid JSON array:
[
  {{
    "criterion": "Step name",
    "marks": 20,
    "description": "What to check when evaluating this step"
  }}
]

Ensure marks sum to exactly {total_marks}."""


def evaluate_code_prompt(
    student_code: str,
    problem_data: dict,
    rubric: list,
    language: str,
    judge_result: dict,
    total_marks: float,
) -> str:
    rubric_text = "\n".join(
        [f"- {r['criterion']} ({r['marks']} marks): {r.get('description', '')}" for r in (rubric or [])]
    )
    return f"""You are an expert programming educator grading a student's lab submission.

PROBLEM:
Title: {problem_data.get('title')}
Description: {problem_data.get('description')}

JUDGE RESULT:
Verdict: {judge_result.get('verdict')}
Test Cases Passed: {judge_result.get('test_cases_passed', 0)} / {judge_result.get('total_test_cases', 0)}
Compilation Error: {judge_result.get('compilation_error') or 'None'}
Runtime Error: {judge_result.get('runtime_error') or 'None'}

STUDENT CODE ({language}):
```
{student_code}
```

RUBRIC (grade ONLY these criteria — do not invent extra ones):
{rubric_text}

HARD RULES:
- Use exactly the rubric criteria above. max_marks for each MUST match the rubric marks.
- marks_awarded must be between 0 and that criterion's max_marks.
- Prefer WHOLE NUMBER marks only (0, 1, 2, …) — do not use decimals like 0.67 or 2.87.
- total_marks_awarded MUST equal the sum of marks_awarded and MUST NOT exceed {total_marks}.
- If judge verdict is SKIPPED: the engine did NOT run the code (unsupported language or no tests). Grade from SOURCE CODE only. Do NOT treat SKIPPED as a failed run. Do NOT zero output/correctness marks only because tests were not executed.
- If judge verdict is WA/RE/TLE/CE/MLE and 0 tests passed after a real run: give 0 on output/correctness-like criteria; other criteria may still get partial marks from visible code.
- If some tests passed but not all: award partial credit fairly from the code and judge context.
- Be fair but strict. Do not invent features that are not in the code.

Return ONLY a valid JSON object:
{{
  "criteria_feedback": [
    {{
      "criterion": "Criterion name from rubric",
      "marks_awarded": 1,
      "max_marks": 1,
      "explanation": "Specific explanation referencing the student's code"
    }}
  ],
  "total_marks_awarded": 0,
  "summary": "Overall 2-3 sentence feedback for the student"
}}"""


def evidence_prompt(student_code: str, scorer_result: dict) -> str:
    return f"""You are an Evidence Agent verifying grading claims against source code.
Attach 1-3 short code quotes for each criterion.

STUDENT CODE:
```
{student_code}
```

SCORER OUTPUT:
{scorer_result}

For each criterion, attach 1-3 short code quotes (substrings that actually appear in the code) as evidence.
If a high score has no supporting evidence, note that in explanation and keep marks_awarded unchanged (Judge will adjust).

Return ONLY valid JSON:
{{
  "criteria_feedback": [
    {{
      "criterion": "...",
      "marks_awarded": 0,
      "max_marks": 0,
      "explanation": "...",
      "evidence": ["exact quote from code"]
    }}
  ]
}}"""


def judge_final_prompt(rubric: list, evidence_result: dict, judge_result: dict, total_marks: float) -> str:
    return f"""You are the final Consistency Judge reducing hallucination in AI lab marks.
Always include verification_notes in your JSON.

RUBRIC: {rubric}
EVIDENCE+SCORER: {evidence_result}
PROGRAM JUDGE: {judge_result}
TOTAL MARKS CAP: {total_marks}

Checks:
1) each marks_awarded in [0, max_marks]
2) total_marks_awarded == sum(marks_awarded)
3) if evidence is empty for a criterion with marks > 0, reduce that score
4) do not invent features not present in evidence/code
5) program judge rules:
   - If verdict is SKIPPED: engine did not run. Do NOT zero output/correctness marks for "0 tests passed". Grade from evidence/code only.
   - If verdict is WA/RE/TLE/CE/MLE and 0 tests passed after a real run: set output/correctness-like criteria to 0.
   - If some tests passed: do not auto-zero all output marks; use evidence.

Return ONLY valid JSON:
{{
  "criteria_feedback": [
    {{
      "criterion": "...",
      "marks_awarded": 0,
      "max_marks": 0,
      "explanation": "...",
      "evidence": ["..."]
    }}
  ],
  "total_marks_awarded": 0,
  "summary": "...",
  "verification_notes": ["Adjusted X because ..."],
  "confidence": "low|medium|high"
}}"""


def learning_analysis_prompt(history: list) -> str:
    return f"""You are an expert programming educator analyzing a student's lab performance.

Write ALL narrative text in SECOND PERSON ("You …"). Never use the student's name.

Lab history (newest first):
{json.dumps(history, indent=2)}

Rules:
- strong_topics: skills they did well (AC or high score ratio).
- weak_topics: gaps from WA/CE/RE/TLE or low criterion marks, plus closely RELATED sibling topics in the same family.
  Example: palindrome reverse logic weak → also suggest digit extraction, string reverse variants.
- Do NOT jump to unrelated areas (graphs/DP) unless their labs already touched that.
- study_recommendations: at least 4 actionable "You should …" items (study tips only).
- suggested_problems: at least 4 practice problem ideas to create INSIDE LabGemma (not external contest links).
  Each idea needs: title, focus_topic, based_on (past lab title), difficulty (easy/medium/hard),
  language (python/cpp/c/java from their history), and reason.
  Do NOT include url or platform fields.
- overall_summary: short "You …" paragraph.

Return ONLY valid JSON:
{{
  "strong_topics": ["Input handling"],
  "weak_topics": ["Integer reversal", "Palindrome edge cases"],
  "study_recommendations": ["You should revise digit extraction with modulo before retrying palindrome problems."],
  "suggested_problems": [
    {{
      "title": "Reverse Digits Practice",
      "focus_topic": "Integer reversal",
      "based_on": "Palindrome Number Check",
      "difficulty": "easy",
      "language": "python",
      "reason": "Builds the reverse logic used in your palindrome lab"
    }}
  ],
  "overall_summary": "You handle input well. Next, practice reverse logic in LabGemma."
}}"""


def practice_pack_prompt(
    *,
    focus_topic: str,
    based_on: str,
    history: list,
    language: str,
    difficulty: str,
    total_marks: int,
) -> str:
    return f"""You create ONE personalized practice problem for a university student.

Focus topic: {focus_topic}
Based on past work: {based_on}
Language: {language}
Difficulty: {difficulty}
Total marks for rubric: {total_marks}

Recent lab context:
{json.dumps(history, indent=2)}

Make a practice problem that targets the focus topic. It may be a related sibling skill, not only a clone.
Keep it solvable in a short practice session.

Return ONLY valid JSON:
{{
  "problem": {{
    "title": "Practice title",
    "description": "Full statement",
    "input_format": "Input format",
    "output_format": "Output format",
    "constraints": "Constraints",
    "sample_input": "Sample input",
    "sample_output": "Sample output",
    "test_cases": [
      {{"input": "t1", "output": "o1"}},
      {{"input": "t2", "output": "o2"}},
      {{"input": "t3", "output": "o3"}}
    ]
  }},
  "rubric": [
    {{"criterion": "Criterion", "marks": 4, "description": "What to check"}}
  ]
}}

Rubric marks must sum to exactly {total_marks}. Write the problem for {language} only."""

