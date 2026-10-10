"""
json_validator.py – Validates the uploaded MCQ JSON file.
"""

import json
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MAX_OPTIONS = 10
MIN_OPTIONS = 2
MAX_QUESTION_LEN = 300
MAX_OPTION_LEN = 100


@dataclass
class ValidationError:
    question_number: Optional[int]   # 1-based for display; None = top-level
    field: str
    message: str

    def __str__(self) -> str:
        if self.question_number is not None:
            return f"Question {self.question_number} → {self.field}: {self.message}"
        return f"{self.field}: {self.message}"


@dataclass
class ValidationResult:
    ok: bool
    quiz_title: str = ""
    description: str = ""
    question_count: int = 0
    errors: list[ValidationError] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def format_errors(self) -> str:
        lines = ["❌ JSON Validation Failed\n"]
        for err in self.errors:
            lines.append(f"• {err}")
        lines.append("\nPlease fix the JSON and upload it again.")
        return "\n".join(lines)


def validate_json_bytes(raw: bytes) -> ValidationResult:
    """Parse and validate raw bytes from an uploaded file."""
    # ── 1. Parse JSON ────────────────────────────────────────────────────────
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return ValidationResult(
            ok=False,
            errors=[ValidationError(None, "file", f"Invalid JSON: {exc}")]
        )

    if not isinstance(data, dict):
        return ValidationResult(
            ok=False,
            errors=[ValidationError(None, "root", "JSON must be an object (dict)")]
        )

    errors: list[ValidationError] = []

    # ── 2. Top-level fields ──────────────────────────────────────────────────
    quiz_title = str(data.get("quiz_title", "")).strip()
    if not quiz_title:
        errors.append(ValidationError(None, "quiz_title", "Field is missing or empty"))

    description = str(data.get("description", "")).strip()

    questions = data.get("questions")
    if questions is None:
        errors.append(ValidationError(None, "questions", "Field is missing"))
        return ValidationResult(ok=False, errors=errors)

    if not isinstance(questions, list):
        errors.append(ValidationError(None, "questions", "Must be a list/array"))
        return ValidationResult(ok=False, errors=errors)

    if len(questions) == 0:
        errors.append(ValidationError(None, "questions", "Array is empty"))
        return ValidationResult(ok=False, errors=errors)

    # ── 3. Per-question validation ───────────────────────────────────────────
    for i, q in enumerate(questions):
        num = i + 1  # 1-based for display

        if not isinstance(q, dict):
            errors.append(ValidationError(num, "question", "Must be a JSON object"))
            continue

        # question text
        text = q.get("question", "")
        if not isinstance(text, str) or not text.strip():
            errors.append(ValidationError(num, "question", "Missing or empty question text"))
        elif len(text) > MAX_QUESTION_LEN:
            errors.append(ValidationError(
                num, "question",
                f"Too long ({len(text)} chars; max {MAX_QUESTION_LEN})"
            ))

        # options
        options = q.get("options")
        if options is None:
            errors.append(ValidationError(num, "options", "Field is missing"))
            continue
        if not isinstance(options, list):
            errors.append(ValidationError(num, "options", "Must be a list/array"))
            continue
        if len(options) < MIN_OPTIONS:
            errors.append(ValidationError(
                num, "options",
                f"Too few options ({len(options)}); minimum {MIN_OPTIONS}"
            ))
            continue
        if len(options) > MAX_OPTIONS:
            errors.append(ValidationError(
                num, "options",
                f"Too many options ({len(options)}); maximum {MAX_OPTIONS}"
            ))
            continue

        for j, opt in enumerate(options):
            if not isinstance(opt, str) or not opt.strip():
                errors.append(ValidationError(
                    num, f"options[{j}]", "Empty or invalid option"
                ))
            elif len(opt) > MAX_OPTION_LEN:
                errors.append(ValidationError(
                    num, f"options[{j}]",
                    f"Too long ({len(opt)} chars; max {MAX_OPTION_LEN})"
                ))

        # correct_option
        correct = q.get("correct_option")
        if correct is None:
            errors.append(ValidationError(num, "correct_option", "Field is missing"))
            continue
        if not isinstance(correct, int):
            errors.append(ValidationError(
                num, "correct_option",
                f"Must be an integer; got {type(correct).__name__}"
            ))
            continue
        if correct < 0 or correct >= len(options):
            errors.append(ValidationError(
                num, "correct_option",
                f"Value {correct} is out of range; available options: 0–{len(options)-1}"
            ))

    if errors:
        return ValidationResult(ok=False, errors=errors)

    return ValidationResult(
        ok=True,
        quiz_title=quiz_title,
        description=description,
        question_count=len(questions),
    )


def parse_questions(data: dict) -> list[dict]:
    """Return the raw list of question dicts from already-validated data."""
    return data["questions"]


def load_and_validate(raw: bytes) -> tuple[ValidationResult, Optional[dict]]:
    """Validate bytes; if OK return (result, parsed_dict), else (result, None)."""
    result = validate_json_bytes(raw)
    if not result.ok:
        return result, None
    data = json.loads(raw.decode("utf-8"))
    return result, data
