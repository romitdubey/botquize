# AI Prompt: Extract MCQ Questions from Book Images

Copy and paste the prompt below (everything between the lines) and send it to an AI vision model (e.g., GPT-4o, Gemini 1.5 Pro, Claude 3.5 Sonnet) **along with your book page images**.

---

```
You are an expert OCR and data extraction assistant. I am providing you with images of pages from a study book or question bank. Your task is to extract all multiple-choice questions (MCQs) and format them as a JSON file I can use with my Telegram Quiz Bot.

## YOUR TASKS

1. **Carefully read all provided pages.**
2. **Identify every MCQ question** on those pages.
3. **Extract the exact question text** — preserve the original wording as accurately as possible. Do not paraphrase or simplify.
4. **Extract all answer options** exactly as written, including option labels if present (A, B, C, D, etc.) — but do NOT include the letter prefix in the option text itself. The bot handles numbering.
5. **Identify the correct answer** from any answer key, tick marks, underlines, bold text, or annotations visible in the images.
6. **If the book provides an explanation or rationale**, extract it exactly and include it in the "explanation" field.
7. **Use 0-based indexing** for correct_option:
   - First option  = 0
   - Second option = 1
   - Third option  = 2
   - Fourth option = 3
   - And so on.
8. **Do NOT invent or modify questions.** Only extract what is clearly visible.
9. **Do NOT change the meaning** of any question or option.
10. **Preserve question numbering** where visible (you can use the original numbers in the question text if helpful, but it is not required).

## IMPORTANT RULES

- Return ONLY valid JSON — no markdown code fences, no extra explanation, no preamble.
- Follow the exact schema shown below.
- If a correct answer is ambiguous or unclear from the images, set "correct_option" to -1 and add a note in the "explanation" field: "ANSWER UNCLEAR — please verify manually."
- If an explanation is not present or cannot be reliably determined, omit the "explanation" field entirely (do not guess).
- Maximum 10 options per question.
- Minimum 2 options per question.
- **Each option must be under 100 characters** (Telegram poll limit). If an option is very long, summarize or truncate it cleanly.
- Question text must be under 300 characters.
- Question text must not be empty.
- Options must not be empty strings.

## JSON SCHEMA

{
  "quiz_title": "Chapter Name or Topic (e.g., Biology Chapter 3 - DNA Replication)",
  "description": "Brief description, e.g., MCQs from pages 45-55",
  "questions": [
    {
      "question": "The exact question text here?",
      "options": [
        "First option text",
        "Second option text",
        "Third option text",
        "Fourth option text"
      ],
      "correct_option": 1,
      "explanation": "Optional explanation text here. Only include if clearly available."
    }
  ]
}

## EXAMPLE

Input (image shows):
  7. Which enzyme unwinds the DNA double helix during replication?
     A. DNA Polymerase   B. Helicase   C. Ligase   D. Primase
     Answer: B

Expected JSON:
{
  "quiz_title": "Chapter 7 - DNA Replication",
  "description": "MCQs extracted from pages X-Y",
  "questions": [
    {
      "question": "Which enzyme unwinds the DNA double helix during replication?",
      "options": [
        "DNA Polymerase",
        "Helicase",
        "Ligase",
        "Primase"
      ],
      "correct_option": 1,
      "explanation": "Helicase is the enzyme responsible for unwinding the DNA double helix by breaking hydrogen bonds between base pairs."
    }
  ]
}

## NOW PROCESS THE IMAGES

Look at all the provided images carefully. Extract every MCQ question visible.

Return ONLY the JSON. No other text.
```

---

## Tips for Better Results

- **Higher quality images = more accurate extraction.** Scan or photograph pages in good lighting.
- **Send 8–12 pages at a time** for best results with most AI models.
- **If OCR misreads text**, manually correct the JSON before uploading to the bot.
- **Always double-check `correct_option`** values before starting the quiz.
- After generating the JSON, you can validate it locally by checking the bot's response when you upload it — the bot will report any errors.

## Supported AI Models

| Model | Notes |
|-------|-------|
| GPT-4o | Excellent OCR, highly recommended |
| GPT-4 Vision | Good, slightly older |
| Gemini 1.5 Pro / 2.0 Flash | Excellent for long documents |
| Claude 3.5 Sonnet / Claude 3 Opus | Great accuracy and instruction following |
| Mistral Pixtral | Good free alternative |

## After Getting the JSON

1. Save the output as a `.json` file (e.g., `biology_ch3.json`).
2. Open your Telegram bot chat.
3. Send the `.json` file as a document (not as a photo).
4. The bot will validate it and show a summary.
5. Press **🚀 Start Quiz** to begin.
