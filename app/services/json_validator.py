"""
json_validator.py – Validates the uploaded MCQ JSON file.
"""

import json
import logging
from datetime import date
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
    quiz_title = data.get("quiz_title", "")
    quiz_title = quiz_title.strip() if isinstance(quiz_title, str) else ""
    if not quiz_title:
        errors.append(ValidationError(None, "quiz_title", "Field is missing or empty"))

    description = data.get("description", "")
    if not isinstance(description, str):
        errors.append(ValidationError(None, "description", "Must be text"))
        description = ""
    for field in ("topic", "study_date"):
        if field in data and (not isinstance(data[field], str) or not data[field].strip()):
            errors.append(ValidationError(None, field, "Must be non-empty text"))
    if isinstance(data.get("study_date"), str):
        try:
            parsed_date = date.fromisoformat(data["study_date"])
            if parsed_date.isoformat() != data["study_date"]:
                raise ValueError
        except ValueError:
            errors.append(ValidationError(None, "study_date", "Use YYYY-MM-DD"))
    if data.get("quiz_kind", "book") not in ("book", "revision"):
        errors.append(ValidationError(None, "quiz_kind", "Use book or revision"))

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

        for field in ("image_url", "explanation"):
            if q.get(field) is not None and not isinstance(q[field], str):
                errors.append(ValidationError(num, field, "Must be text or null"))
        for field in ("source_id", "source_topic"):
            if field in q and (not isinstance(q[field], str) or len(q[field]) > 500):
                errors.append(ValidationError(num, field, "Must be text up to 500 characters"))

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

        # Auto-trim options if longer than MAX_OPTION_LEN
        sanitized_options = []
        for j, opt in enumerate(options):
            if not isinstance(opt, str) or not opt.strip():
                errors.append(ValidationError(
                    num, f"options[{j}]", "Empty or invalid option"
                ))
            else:
                opt_str = opt.strip()
                if len(opt_str) > MAX_OPTION_LEN:
                    # Truncate cleanly so Telegram accepts the poll
                    opt_str = opt_str[:MAX_OPTION_LEN - 3].rstrip() + "..."
                sanitized_options.append(opt_str)

        # correct_option
        correct = q.get("correct_option")
        if correct is None:
            errors.append(ValidationError(num, "correct_option", "Field is missing"))
            continue
        if type(correct) is not int:
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


def sanitize_data(data: dict) -> dict:
    """Trim strings to fit Telegram API limits so send_poll never fails."""
    for q in data.get("questions", []):
        if "question" in q and isinstance(q["question"], str):
            q["question"] = q["question"].strip()
            if len(q["question"]) > MAX_QUESTION_LEN:
                q["question"] = q["question"][:MAX_QUESTION_LEN - 3].rstrip() + "..."

        if "options" in q and isinstance(q["options"], list):
            sanitized = []
            for opt in q["options"]:
                opt_str = str(opt).strip()
                if len(opt_str) > MAX_OPTION_LEN:
                    opt_str = opt_str[:MAX_OPTION_LEN - 3].rstrip() + "..."
                sanitized.append(opt_str)
            q["options"] = sanitized

        if "explanation" in q and isinstance(q["explanation"], str):
            # Telegram quiz poll explanation limit is 200 characters
            expl = q["explanation"].strip()
            if len(expl) > 200:
                q["explanation"] = expl[:197].rstrip() + "..."

    return data


def parse_questions(data: dict) -> list[dict]:
    """Return the raw list of question dicts from already-validated data."""
    return data["questions"]


def load_and_validate(raw: bytes) -> tuple[ValidationResult, Optional[dict]]:
    """Validate bytes; if OK return (result, parsed_dict), else (result, None)."""
    result = validate_json_bytes(raw)
    if not result.ok:
        return result, None
    data = json.loads(raw.decode("utf-8"))
    sanitized_data = sanitize_data(data)
    return result, sanitized_data
