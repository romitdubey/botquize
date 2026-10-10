"""
statistics.py – Helpers for formatting statistics messages.
"""

from app.models import QuizSession
from app.state import get_overall_stats, get_history, get_history_count
from app.config import HISTORY_PAGE_SIZE, REVIEW_PAGE_SIZE


# ─── Session statistics ───────────────────────────────────────────────────────

def format_result(session: QuizSession) -> str:
    acc_str = f"{session.accuracy:.2f}%"
    lines = [
        "━━━━━━━━━━━━━━━━━━",
        "📊 QUIZ RESULT",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"📚 {session.quiz_title}",
        "",
        f"Total Questions  : {session.total_questions}",
        f"Attempted        : {session.attempted}",
        "",
        f"✅ Correct        : {session.correct}",
        f"❌ Wrong          : {session.wrong}",
        f"⏭️  Unattempted    : {session.unattempted}",
        "",
        f"🏆 Score          : {session.correct}/{session.total_questions}",
        f"🎯 Accuracy       : {acc_str}",
        "",
        "━━━━━━━━━━━━━━━━━━",
    ]
    if session.status.value == "COMPLETED":
        lines[1] = "📊 QUIZ COMPLETED"
    return "\n".join(lines)


def format_status(session: QuizSession) -> str:
    acc_str = f"{session.accuracy:.2f}%"
    published = session.current_question
    return (
        f"📚 Current Quiz\n\n"
        f"Quiz: {session.quiz_title}\n\n"
        f"Progress  : {published}/{session.total_questions}\n"
        f"Correct   : {session.correct}\n"
        f"Wrong     : {session.wrong}\n"
        f"Unattempted: {session.unattempted}\n\n"
        f"Accuracy  : {acc_str}"
    )


# ─── Review (wrong questions) ─────────────────────────────────────────────────

def format_review_page(session: QuizSession, page: int) -> tuple[str, int]:
    """Return (text, total_pages) for the given page of wrong questions."""
    wrong = session.wrong_questions
    if not wrong:
        return "✅ No wrong answers! Perfect score on answered questions.", 1

    total_pages = max(1, (len(wrong) + REVIEW_PAGE_SIZE - 1) // REVIEW_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    start = page * REVIEW_PAGE_SIZE
    chunk = wrong[start: start + REVIEW_PAGE_SIZE]

    lines = ["❌ WRONG QUESTIONS\n"]
    for q in chunk:
        real_num = q.question_index + 1
        user_ans_text = (
            q.options[q.user_answer]
            if q.user_answer is not None and 0 <= q.user_answer < len(q.options)
            else "—"
        )
        correct_ans_text = q.options[q.correct_option]

        lines.append(f"Q{real_num}")
        lines.append(f"Question: {q.question_text}")
        lines.append(f"\n❌ Your answer:\n{user_ans_text}")
        lines.append(f"\n✅ Correct answer:\n{correct_ans_text}")
        if q.explanation:
            lines.append(f"\n💡 Explanation:\n{q.explanation}")
        lines.append("\n" + "─" * 20)

    return "\n".join(lines), total_pages


# ─── History ──────────────────────────────────────────────────────────────────

def format_history_page(page: int) -> tuple[str, int]:
    entries = get_history(page=page, page_size=HISTORY_PAGE_SIZE)
    total = get_history_count()
    total_pages = max(1, (total + HISTORY_PAGE_SIZE - 1) // HISTORY_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    if not entries:
        return "📚 No quiz history yet.", 1

    lines = ["📚 QUIZ HISTORY\n"]
    offset = page * HISTORY_PAGE_SIZE
    for idx, e in enumerate(entries, start=offset + 1):
        date_str = e.completed_at.strftime("%d %b %Y")
        lines.append(
            f"{idx}. {e.quiz_title}\n"
            f"   Score: {e.correct}/{e.total_questions}  •  "
            f"Accuracy: {e.accuracy:.2f}%  •  {date_str}"
        )

    return "\n".join(lines), total_pages


# ─── Overall statistics ───────────────────────────────────────────────────────

def format_overall_stats() -> str:
    s = get_overall_stats()
    overall_acc = f"{s['overall_accuracy']:.2f}%"
    best_acc = f"{s['best_accuracy']:.2f}%"
    return (
        "📈 OVERALL STATISTICS\n\n"
        f"Quizzes Completed  : {s['quizzes_completed']}\n"
        f"Questions Attempted: {s['questions_attempted']}\n\n"
        f"✅ Correct          : {s['total_correct']}\n"
        f"❌ Wrong            : {s['total_wrong']}\n\n"
        f"🎯 Overall Accuracy : {overall_acc}\n"
        f"🏆 Best Score       : {best_acc}"
    )
