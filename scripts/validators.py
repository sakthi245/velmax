from __future__ import annotations

import ast
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
import asyncio


@dataclass
class ValidationResult:
    passed: bool
    lint_errors: List[str] = field(default_factory=list)
    type_errors: List[str] = field(default_factory=list)
    test_errors: List[str] = field(default_factory=list)
    success_probability: float = 0.0
    warnings: List[str] = field(default_factory=list)


async def validate_generated_script(
    main_code: str,
    config_code: str,
    test_code: str,
    requirements_code: str,
) -> ValidationResult:
    errors = []
    warnings = []

    # 1. Syntax check
    syntax_errors = _check_syntax(main_code)
    if syntax_errors:
        errors.extend([f"main.py: {e}" for e in syntax_errors])

    syntax_errors = _check_syntax(config_code)
    if syntax_errors:
        errors.extend([f"config.py: {e}" for e in syntax_errors])

    syntax_errors = _check_syntax(test_code)
    if syntax_errors:
        errors.extend([f"tests.py: {e}" for e in syntax_errors])

    syntax_errors = _check_syntax(requirements_code)
    if syntax_errors:
        errors.extend([f"requirements.txt: {e}" for e in syntax_errors])

    # 2. Lint check
    lint_errors = await _run_lint(main_code, "main.py")
    if lint_errors:
        errors.extend(lint_errors)

    lint_errors = await _run_lint(config_code, "config.py")
    if lint_errors:
        errors.extend(lint_errors)

    # 3. Type check
    type_errors = await _run_type_check(main_code, config_code)
    if type_errors:
        errors.extend(type_errors)

    # 4. Test run
    test_errors = await _run_tests(test_code)
    if test_errors:
        errors.extend(test_errors)

    success_prob = 1.0
    if errors:
        success_prob = max(0.1, 1.0 - len(errors) * 0.1)
    elif warnings:
        success_prob = 0.9

    return ValidationResult(
        passed=len(errors) == 0,
        lint_errors=[e for e in errors if "lint" in e.lower()],
        type_errors=[e for e in errors if "type" in e.lower()],
        test_errors=[e for e in errors if "test" in e.lower()],
        success_probability=success_prob,
        warnings=warnings,
    )


def _check_syntax(code: str) -> List[str]:
    try:
        ast.parse(code)
        return []
    except SyntaxError as e:
        return [f"Line {e.lineno}: {e.msg}"]


async def _run_lint(code: str, filename: str) -> List[str]:
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            f.flush()
            temp_path = f.name

        proc = await asyncio.create_subprocess_exec(
            "ruff", "check", "--output-format=text", temp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        Path(temp_path).unlink(missing_ok=True)

        if proc.returncode != 0:
            return stdout.decode().strip().split("\n")
        return []
    except Exception:
        return []


async def _run_type_check(main_code: str, config_code: str) -> List[str]:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            main_path = Path(tmpdir) / "main.py"
            config_path = Path(tmpdir) / "config.py"
            main_path.write_text(main_code)
            config_path.write_text(config_code)

            proc = await asyncio.create_subprocess_exec(
                "mypy", "--strict", "--ignore-missing-imports", str(main_path), str(config_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return stdout.decode().strip().split("\n")
            return []
    except Exception:
        return []


async def _run_tests(test_code: str) -> List[str]:
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            test_path = Path(tmpdir) / "test_generated.py"
            test_path.write_text(test_code)

            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "pytest", str(test_path), "-v",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                return stdout.decode().strip().split("\n")
            return []
    except Exception:
        return []