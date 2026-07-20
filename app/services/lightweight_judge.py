"""Lightweight local judge (no Docker). Python / C / C++ / Java on host toolchain."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path


def run_judge(code: str, language: str, test_cases: list[dict], timeout: float = 2.0) -> dict:
    cases = test_cases or []
    if not cases:
        return {
            "verdict": "SKIPPED",
            "test_cases_passed": 0,
            "total_test_cases": 0,
            "execution_time": 0.0,
            "compilation_error": None,
            "runtime_error": "No test cases",
        }

    lang = (language or "python").lower().strip()
    if lang in ("python", "py"):
        return _run_python(code, cases, timeout)
    if lang in ("cpp", "c++", "cplusplus"):
        return _run_compiled(code, cases, timeout, ext="cpp", compiler="g++", flags=["-O2", "-std=c++17"])
    if lang == "c":
        return _run_compiled(code, cases, timeout, ext="c", compiler="gcc", flags=["-O2", "-std=c11"])
    if lang == "java":
        return _run_java(code, cases, timeout)

    return {
        "verdict": "SKIPPED",
        "test_cases_passed": 0,
        "total_test_cases": len(cases),
        "execution_time": 0.0,
        "compilation_error": None,
        "runtime_error": (
            f"Lightweight judge does not support '{language}' yet. "
            "AI rubric grading still runs from source code."
        ),
    }


def _run_python(code: str, cases: list[dict], timeout: float) -> dict:
    with tempfile.TemporaryDirectory(prefix="labgemma_") as tmp:
        path = Path(tmp) / "main.py"
        path.write_text(code, encoding="utf-8")
        return _run_cases(cases, timeout, ["python3", str(path)], cwd=tmp)


def _run_compiled(
    code: str,
    cases: list[dict],
    timeout: float,
    *,
    ext: str,
    compiler: str,
    flags: list[str],
) -> dict:
    if not shutil.which(compiler):
        return {
            "verdict": "SKIPPED",
            "test_cases_passed": 0,
            "total_test_cases": len(cases),
            "execution_time": 0.0,
            "compilation_error": None,
            "runtime_error": f"{compiler} not found on host. AI rubric grading still runs.",
        }

    with tempfile.TemporaryDirectory(prefix="labgemma_") as tmp:
        src = Path(tmp) / f"solution.{ext}"
        exe = Path(tmp) / "solution"
        src.write_text(code, encoding="utf-8")
        try:
            comp = subprocess.run(
                [compiler, *flags, str(src), "-o", str(exe)],
                capture_output=True,
                text=True,
                timeout=15,
                cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return {
                "verdict": "CE",
                "test_cases_passed": 0,
                "total_test_cases": len(cases),
                "execution_time": 0.0,
                "compilation_error": "Compilation timeout",
                "runtime_error": None,
            }
        if comp.returncode != 0:
            return {
                "verdict": "CE",
                "test_cases_passed": 0,
                "total_test_cases": len(cases),
                "execution_time": 0.0,
                "compilation_error": (comp.stderr or comp.stdout or "Compile error")[:800],
                "runtime_error": None,
            }
        return _run_cases(cases, timeout, [str(exe)], cwd=tmp)


def _run_java(code: str, cases: list[dict], timeout: float) -> dict:
    if not shutil.which("javac") or not shutil.which("java"):
        return {
            "verdict": "SKIPPED",
            "test_cases_passed": 0,
            "total_test_cases": len(cases),
            "execution_time": 0.0,
            "compilation_error": None,
            "runtime_error": "javac/java not found on host. AI rubric grading still runs.",
        }

    with tempfile.TemporaryDirectory(prefix="labgemma_") as tmp:
        src = Path(tmp) / "Main.java"
        src.write_text(code, encoding="utf-8")
        try:
            comp = subprocess.run(
                ["javac", "Main.java"],
                capture_output=True,
                text=True,
                timeout=20,
                cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return {
                "verdict": "CE",
                "test_cases_passed": 0,
                "total_test_cases": len(cases),
                "execution_time": 0.0,
                "compilation_error": "Compilation timeout",
                "runtime_error": None,
            }
        if comp.returncode != 0:
            return {
                "verdict": "CE",
                "test_cases_passed": 0,
                "total_test_cases": len(cases),
                "execution_time": 0.0,
                "compilation_error": (comp.stderr or comp.stdout or "Compile error")[:800],
                "runtime_error": None,
            }
        return _run_cases(cases, timeout, ["java", "-Xmx192m", "-cp", tmp, "Main"], cwd=tmp)


def _run_cases(cases: list[dict], timeout: float, cmd: list[str], *, cwd: str) -> dict:
    passed = 0
    total_time = 0.0

    for tc in cases:
        stdin = tc.get("input") or ""
        expected = (tc.get("output") or "").strip("\n")
        start = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                input=stdin,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            return {
                "verdict": "TLE",
                "test_cases_passed": passed,
                "total_test_cases": len(cases),
                "execution_time": round(total_time, 3),
                "compilation_error": None,
                "runtime_error": "Time limit exceeded",
            }
        total_time += time.perf_counter() - start

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "Runtime error")[:800]
            return {
                "verdict": "RE",
                "test_cases_passed": passed,
                "total_test_cases": len(cases),
                "execution_time": round(total_time, 3),
                "compilation_error": None,
                "runtime_error": err,
            }

        actual = (proc.stdout or "").strip("\n")
        if actual == expected:
            passed += 1
        else:
            return {
                "verdict": "WA",
                "test_cases_passed": passed,
                "total_test_cases": len(cases),
                "execution_time": round(total_time, 3),
                "compilation_error": None,
                "runtime_error": f"Expected:\n{expected}\nGot:\n{actual}",
            }

    return {
        "verdict": "AC" if passed == len(cases) else "WA",
        "test_cases_passed": passed,
        "total_test_cases": len(cases),
        "execution_time": round(total_time, 3),
        "compilation_error": None,
        "runtime_error": None,
    }
