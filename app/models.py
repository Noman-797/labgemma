from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))  # teacher | student
    student_id: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    sessions: Mapped[list["LabSession"]] = relationship(back_populates="teacher")
    submissions: Mapped[list["LabSubmission"]] = relationship(back_populates="student")
    practice_problems: Mapped[list["PracticeProblem"]] = relationship(back_populates="student")
    learning_profile: Mapped["LearningProfile | None"] = relationship(back_populates="student", uselist=False)


class LabSession(Base):
    __tablename__ = "lab_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft=Upcoming | active=Live | closed=Past
    marks_per_lab: Mapped[int] = mapped_column(Integer, default=100)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True, default=60)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ends_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    teacher: Mapped["User"] = relationship(back_populates="sessions")
    problems: Mapped[list["LabProblem"]] = relationship(back_populates="session", cascade="all, delete-orphan")
    submissions: Mapped[list["LabSubmission"]] = relationship(back_populates="session")


class LabProblem(Base):
    __tablename__ = "lab_problems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("lab_sessions.id"))
    order: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    input_format: Mapped[str] = mapped_column(Text, default="")
    output_format: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    sample_input: Mapped[str] = mapped_column(Text, default="")
    sample_output: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(20), default="python")
    difficulty: Mapped[str] = mapped_column(String(20), default="easy")
    test_cases_json: Mapped[str] = mapped_column(Text, default="[]")
    rubric_json: Mapped[str] = mapped_column(Text, default="[]")
    total_marks: Mapped[int] = mapped_column(Integer, default=10)
    ai_prompt: Mapped[str] = mapped_column(Text, default="")
    rubric_prompt: Mapped[str] = mapped_column(Text, default="")
    rubric_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["LabSession"] = relationship(back_populates="problems")
    submissions: Mapped[list["LabSubmission"]] = relationship(back_populates="problem")


class LabSubmission(Base):
    __tablename__ = "lab_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("lab_sessions.id"))
    problem_id: Mapped[int] = mapped_column(ForeignKey("lab_problems.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    code: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(20), default="python")
    verdict: Mapped[str] = mapped_column(String(20), default="PENDING")
    test_cases_passed: Mapped[int] = mapped_column(Integer, default=0)
    total_test_cases: Mapped[int] = mapped_column(Integer, default=0)
    execution_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    compilation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    runtime_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_final: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_feedback_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_total_marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_notes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["LabSession"] = relationship(back_populates="submissions")
    problem: Mapped["LabProblem"] = relationship(back_populates="submissions")
    student: Mapped["User"] = relationship(back_populates="submissions")


class LearningProfile(Base):
    """Cached Gemma analysis of a student's lab history."""

    __tablename__ = "learning_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    analysis_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    student: Mapped["User"] = relationship(back_populates="learning_profile")


class PracticeProblem(Base):
    """Personalized practice generated from weak topics in past labs."""

    __tablename__ = "practice_problems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    input_format: Mapped[str] = mapped_column(Text, default="")
    output_format: Mapped[str] = mapped_column(Text, default="")
    constraints: Mapped[str] = mapped_column(Text, default="")
    sample_input: Mapped[str] = mapped_column(Text, default="")
    sample_output: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(20), default="python")
    difficulty: Mapped[str] = mapped_column(String(20), default="easy")
    test_cases_json: Mapped[str] = mapped_column(Text, default="[]")
    rubric_json: Mapped[str] = mapped_column(Text, default="[]")
    total_marks: Mapped[int] = mapped_column(Integer, default=10)
    focus_topic: Mapped[str] = mapped_column(String(200), default="")
    based_on: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    student: Mapped["User"] = relationship(back_populates="practice_problems")
    submissions: Mapped[list["PracticeSubmission"]] = relationship(
        back_populates="practice", cascade="all, delete-orphan"
    )


class PracticeSubmission(Base):
    __tablename__ = "practice_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    practice_id: Mapped[int] = mapped_column(ForeignKey("practice_problems.id"))
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    code: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(20), default="python")
    verdict: Mapped[str] = mapped_column(String(20), default="PENDING")
    test_cases_passed: Mapped[int] = mapped_column(Integer, default=0)
    total_test_cases: Mapped[int] = mapped_column(Integer, default=0)
    ai_total_marks: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    practice: Mapped["PracticeProblem"] = relationship(back_populates="submissions")
