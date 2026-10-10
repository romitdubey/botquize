"""
tests/test_json_validator.py – Unit tests for JSON validation.
"""

import json
import pytest
from app.services.json_validator import load_and_validate, validate_json_bytes


def _make_json(**overrides) -> bytes:
    """Build a minimal valid quiz JSON, with optional field overrides."""
    base = {
        "quiz_title": "Test Quiz",
        "description": "A test",
        "questions": [
            {
                "question": "What is 2 + 2?",
                "options": ["3", "4", "5", "6"],
                "correct_option": 1,
                "explanation": "Basic arithmetic.",
            }
        ],
    }
    base.update(overrides)
    return json.dumps(base).encode("utf-8")


# ─── Happy path ───────────────────────────────────────────────────────────────

class TestValidJSON:
    def test_valid_minimal(self):
        raw = json.dumps({
            "quiz_title": "Q",
            "questions": [
                {"question": "Q?", "options": ["A", "B"], "correct_option": 0}
            ]
        }).encode()
        result, data = load_and_validate(raw)
        assert result.ok
        assert result.question_count == 1

    def test_valid_with_explanation(self):
        result, _ = load_and_validate(_make_json())
        assert result.ok

    def test_quiz_title_extracted(self):
        result, _ = load_and_validate(_make_json())
        assert result.quiz_title == "Test Quiz"

    def test_question_count(self):
        data = {
            "quiz_title": "Q",
            "questions": [
                {"question": f"Q{i}?", "options": ["A", "B"], "correct_option": 0}
                for i in range(10)
            ]
        }
        result, _ = load_and_validate(json.dumps(data).encode())
        assert result.ok
        assert result.question_count == 10

    def test_max_options(self):
        opts = [f"Option {i}" for i in range(10)]
        data = {
            "quiz_title": "Q",
            "questions": [
                {"question": "Q?", "options": opts, "correct_option": 9}
            ]
        }
        result, _ = load_and_validate(json.dumps(data).encode())
        assert result.ok


# ─── Failure cases ────────────────────────────────────────────────────────────

class TestInvalidJSON:
    def test_not_json(self):
        result = validate_json_bytes(b"this is not json")
        assert not result.ok
        assert any("Invalid JSON" in str(e) for e in result.errors)

    def test_empty_bytes(self):
        result = validate_json_bytes(b"")
        assert not result.ok

    def test_missing_questions_field(self):
        result = validate_json_bytes(json.dumps({"quiz_title": "Q"}).encode())
        assert not result.ok

    def test_empty_questions_array(self):
        data = {"quiz_title": "Q", "questions": []}
        result = validate_json_bytes(json.dumps(data).encode())
        assert not result.ok

    def test_missing_question_text(self):
        data = {
            "quiz_title": "Q",
            "questions": [{"options": ["A", "B"], "correct_option": 0}]
        }
        result = validate_json_bytes(json.dumps(data).encode())
        assert not result.ok

    def test_missing_options(self):
        data = {
            "quiz_title": "Q",
            "questions": [{"question": "Q?", "correct_option": 0}]
        }
        result = validate_json_bytes(json.dumps(data).encode())
        assert not result.ok

    def test_too_few_options(self):
        data = {
            "quiz_title": "Q",
            "questions": [{"question": "Q?", "options": ["A"], "correct_option": 0}]
        }
        result = validate_json_bytes(json.dumps(data).encode())
        assert not result.ok

    def test_too_many_options(self):
        opts = [f"Option {i}" for i in range(11)]
        data = {
            "quiz_title": "Q",
            "questions": [{"question": "Q?", "options": opts, "correct_option": 0}]
        }
        result = validate_json_bytes(json.dumps(data).encode())
        assert not result.ok

    def test_correct_option_out_of_range_high(self):
        data = {
            "quiz_title": "Q",
            "questions": [{"question": "Q?", "options": ["A", "B", "C"], "correct_option": 5}]
        }
        result = validate_json_bytes(json.dumps(data).encode())
        assert not result.ok
        assert any("out of range" in str(e) for e in result.errors)

    def test_correct_option_negative(self):
        data = {
            "quiz_title": "Q",
            "questions": [{"question": "Q?", "options": ["A", "B"], "correct_option": -1}]
        }
        result = validate_json_bytes(json.dumps(data).encode())
        assert not result.ok

    def test_empty_option_text(self):
        data = {
            "quiz_title": "Q",
            "questions": [{"question": "Q?", "options": ["A", ""], "correct_option": 0}]
        }
        result = validate_json_bytes(json.dumps(data).encode())
        assert not result.ok

    def test_missing_correct_option(self):
        data = {
            "quiz_title": "Q",
            "questions": [{"question": "Q?", "options": ["A", "B"]}]
        }
        result = validate_json_bytes(json.dumps(data).encode())
        assert not result.ok

    def test_multiple_errors_reported(self):
        data = {
            "quiz_title": "Q",
            "questions": [
                {"question": "", "options": ["A"], "correct_option": 5},
                {"question": "Q?", "options": ["A", "B"], "correct_option": 0},
            ]
        }
        result = validate_json_bytes(json.dumps(data).encode())
        assert not result.ok
        assert len(result.errors) >= 2
