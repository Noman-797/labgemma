# LabGemma

**A Concern of Semicolons** · AI-assisted programming lab with personalized learning

[![Live Demo](https://img.shields.io/badge/Live_Demo-labgemma.onrender.com-0f766e?style=for-the-badge)](https://labgemma.onrender.com/)
[![Gemma 4](https://img.shields.io/badge/LLM-Gemma_4_only-4285F4?style=for-the-badge)](https://ollama.com/library/gemma4)
[![License](https://img.shields.io/badge/License-MIT-gray?style=for-the-badge)](LICENSE)

Teachers build labs with **Gemma 4**. Students code in a real editor. A rule-based judge runs first. When tests fail, Gemma awards **fair partial credit** against a **teacher-approved, question-specific rubric**. After labs, Gemma generates **personalized practice** from each student’s weak areas.

> Live: [https://labgemma.onrender.com](https://labgemma.onrender.com/)  
> Inspired by [Rubric Is All You Need](https://arxiv.org/abs/2503.23989) (ICER 2025)

---

## The problem

University programming labs still depend on heavy manual work and strict pass/fail judging:

- Teachers spend hours writing problems, test cases, and grading by hand
- Online judges often give **CE / WA / RE → zero**, even when the code shows partial understanding
- Blind AI grading without execution or an approved rubric is inconsistent
- After marks, students rarely get practice targeted at their mistakes

## What LabGemma does

| Step | What happens |
|------|----------------|
| 1. Generate | Teacher prompt → Gemma builds problem, hidden tests, and rubric |
| 2. Approve | Teacher reviews and publishes |
| 3. Solve | Students code in **C, C++, Python, or Java** |
| 4. Judge first | Engine runs hidden tests — **AC → full marks instantly** |
| 5. Rubric AI | CE / WA / RE / partial → Gemma scores with consistency check |
| 6. Teacher control | Override any AI mark — instructor always decides |
| 7. Personalized learning | Gemma analyzes history and creates in-app practice problems |

**Gemma 4 is the only LLM.** Traditional tools (SQLite, compilers, HTTP) support the app; they do not replace Gemma.

### Where Gemma is used

1. Lab problem + test case generation  
2. Question-specific rubric generation  
3. Rubric-based partial scoring (scorer)  
4. Consistency / verification pass  
5. Learning analysis + personalized practice generation  

---

## Architecture

```text
Teacher prompt
    → Gemma (problem + rubric pack)
    → Teacher approve
    → Student submit
    → Lightweight judge (Python / C / C++ / Java)
         ├─ AC  → full marks
         └─ else → Gemma scorer → Gemma consistency → teacher override
    → Personalized learning (Gemma)
```

**Stack:** FastAPI · Jinja2 · SQLite · SQLAlchemy 2 · httpx (Ollama Cloud / OpenAI-compatible Gemma API) · Docker

---

## Live demo accounts

| Role | Email | Password |
|------|-------|----------|
| Teacher | `teacher@demo.com` | `teacher123` |
| Student | `abdnoman093@gmail.com` | `student123` |
| Student | `student2@demo.com` | `student123` |

**5-minute walkthrough**

1. Teacher → New session → Add problem (AI) → Approve → Activate  
2. Student (correct code) → Final submit → expect **AC / full marks**  
3. Student (weak code) → Final submit → **AI partial marks** + notes  
4. Learning → Analyze → practice problems in LabGemma  

> Free hosting may cold-start (~30–60s on first hit). Uptime monitoring keeps the demo warm.

---

## Quick start (Docker — recommended)

```bash
git clone https://github.com/Noman-797/labgemma.git
cd labgemma
cp .env.example .env
# set GEMMA_API_KEY, or MOCK_GEMMA=1 for offline demo

docker compose up --build -d
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000)

- Image includes `python3`, `gcc`, `g++`, and JDK for judging  
- SQLite persists in volume `labgemma_data`  
- `SEED_DEMO=1` creates the demo accounts on start  

```bash
docker compose logs -f
docker compose down
```

### Environment

```env
SECRET_KEY=change-me
DATABASE_URL=sqlite:////data/labgemma.db
GEMMA_API_KEY=your_ollama_or_provider_key
GEMMA_API_BASE_URL=https://ollama.com/v1
GEMMA_MODEL=gemma4:31b-cloud
MOCK_GEMMA=0
SEED_DEMO=1
```

See `.env.example` for all options. Client: `app/services/gemma_client.py`.

---

## Local setup (without Docker)

Needs Python 3.11+ and, for non-Python labs, `gcc` / `g++` / `javac`.

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python scripts/seed_demo.py
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

---

## Deploy

This repo is Docker-ready. Deployed example: **[labgemma.onrender.com](https://labgemma.onrender.com/)**.

Any Docker host works (Render, Railway, Fly.io, AWS EC2, VPS):

```bash
docker build -t labgemma .
docker run -d --name labgemma -p 8000:8000 --env-file .env \
  -e DATABASE_URL=sqlite:////data/labgemma.db -e SEED_DEMO=1 \
  -v labgemma_data:/data labgemma
```

---

## Project layout

```text
app/
  main.py              # FastAPI entry
  routers/             # auth, teacher, student, learning
  services/
    gemma_client.py    # Gemma-only LLM client
    grade_pipeline.py  # judge + AI partial credit
    learning.py        # personalized practice
    lightweight_judge.py
  templates/           # UI
scripts/seed_demo.py
Dockerfile
docker-compose.yml
```

---

## Limitations

- Prototype for education / hackathon demos — not a full proctoring platform  
- Student code runs in temporary dirs inside the app container (not a hardened per-submission sandbox)  
- Free PaaS disks can reset on redeploy; re-seed with `SEED_DEMO=1`  

---

## License

MIT · Built by [Abdullah Al Noman](https://abdnoman.com) · A Concern of Semicolons
