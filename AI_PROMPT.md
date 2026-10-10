# AI Prompt: Extract MCQ Questions from Book Images

Copy and paste the prompt below (everything between the lines) and send it to an AI vision model (e.g., GPT-4o, Gemini 1.5 Pro, Claude 3.5 Sonnet) **along with your book page images**.

---

```
You are an expert OCR and data extraction assistant for competitive exams and study books.
I am providing you with images/scans of pages from my MCQ question bank.

Your task is to:
1. Extract ALL multiple-choice questions into a structured JSON file for my Telegram Quiz Bot.
2. Flag any questions that require a visual diagram or figure so I can manually screenshot them.

## INSTRUCTIONS & RULES:

1. **Text & Equation Questions:**
   - Extract the question and all options accurately.
   - For chemical reactions, equilibrium arrows, math symbols, and units, transcribe them as clean Unicode text (e.g. ⇄, →, ΔG, °, kJ/mol, mM). Do NOT require an image if it can be typed.
   - Keep each option under 100 characters (Telegram poll limit).

2. **Diagram / Figure / Graph Questions:**
   - If a question has a visual diagram, succession flowchart, anatomy sketch, gel electrophoresis picture, or pathway that CANNOT be cleanly typed as text:
     - Set `"image_url": "NEEDS_IMAGE_Q<number>"` (e.g., `"NEEDS_IMAGE_Q59"`).
     - In `"options"`, output simple labels: `["Option 1", "Option 2", "Option 3", "Option 4"]`.
   - If a question does NOT need an image, omit the `"image_url"` key or set it to `null`.

3. **Answer & Explanation:**
   - Identify the correct answer (from the answer key or markings on the pages).
   - Use 0-based indexing for `correct_option`:
     0 = first option, 1 = second option, 2 = third option, 3 = fourth option.
   - Include the explanation if available in the book.

4. **OUTPUT FORMAT:**
   - Output the valid JSON block first inside a ```json code block.
   - After the JSON block, provide a short **"📸 Questions Requiring Images"** list telling me exactly which question numbers need a screenshot and why.

## JSON SCHEMA:

```json
{
  "quiz_title": "Subject / Chapter Name",
  "description": "MCQs extracted from pages X-Y",
  "questions": [
    {
      "question": "59. Which of the following species replacement sequence depicts tolerance model of community succession? (Refer to diagram)",
      "image_url": "NEEDS_IMAGE_Q59",
      "options": [
        "Option 1",
        "Option 2",
        "Option 3",
        "Option 4"
      ],
      "correct_option": 1,
      "explanation": "In the tolerance model, later species can invade and grow to maturity in the presence of early species without being inhibited."
    },
    {
      "question": "74. In a human cell, the concentration of ATP, ADP and Pi are 2.25, 0.50 and 0.825mM respectively. The free energy of hydrolysis of ATP at pH 7.0 and 25°C is:",
      "options": [
        "-30.5 kJ/mol",
        "-61 kJ/mol",
        "-15.25 kJ/mol",
        "-52 kJ/mol"
      ],
      "correct_option": 3,
      "explanation": "ΔG = ΔG°' + RT ln([ADP][Pi]/[ATP]). Calculating gives approx -52 kJ/mol."
    }
  ]
}
```

Now, carefully process all uploaded pages and generate the JSON and the Image List.

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
