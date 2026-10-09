# Mission content and sources

All questions live in `fixtures/energy_lab.json`. Each question records a `source`
(**TEXTBOOK** or **SUPPLEMENTARY**) and a `source_reference`, which are shown on the projector
and the host dashboard.

## Source material used

Supplied by the team and read for this build:

* `ENERGY_LAB_PRESENTER_GUIDE.pdf` (12 pp.): answer keys (Sections 6, 8, 9, 12, 13), the abstract
  quoted in full, and the source-fidelity rule.
* `ENERGY_LAB_UNIT5.pptx` / `.pdf` (88 slides with speaker notes): the exact Game 1 situations,
  Game 3 statements, Game 4 bugs and Final Boss cards, plus the colour palette and fonts.
* `ENERGY_LAB_STUDENT_DOSSIER.pdf`: vocabulary list and revision sequence.
* `listening_fallback.md`: listening Tasks 6–7 (not used in the game; see below).

Textbook: *Career Paths: Engineering*, Book 1 (Lloyd & Frazier, Express Publishing 2011),
Unit 5 — Energy, pp. 12–13. The textbook itself was **not** supplied. Every textbook item here
is taken from the quotations in the presenter guide and deck.

## Mission by mission

| Mission | Questions | Origin |
|---|---|---|
| 01 ENERGY SCAN | 5 | Deck Game 1 situations 1–5, verbatim. Options are POTENTIAL / KINETIC / POTENTIAL, THEN KINETIC, because situation 5 is "both — first potential, then kinetic" in the deck. |
| 02 VOCABULARY BATTLE | 8 | Textbook Task 3 sentences (Q1–Q5), Task 4 matching verbatim (Q6, all-or-nothing), and two gap-fills from the textbook abstract (Q7 *Gs*, Q8 *transfers*). Distractors are other Unit 5 vocabulary words. |
| 03 CRASH DETECTIVE | 7 | Deck Game 3: statements 1–3 are textbook Task 2 (reworded for True/False, as in the deck); statements 4–7 are the deck's supplementary revision statements. Answers and explanations come from guide Section 13. |
| 04 ERROR 404 | 5 | Deck Game 4 bugs and fixes, verbatim. The three wrong repair options per bug were **written for this app** (supplementary), because the deck's game is spoken, not multiple choice. |
| 05 FINAL CRASH SIMULATION | 1 (300 EP) | Deck Final Boss cards A–D, correct order B → D → A → C. |

## Scientific wording

The textbook abstract says passengers "have potential energy", which then "becomes kinetic
energy" in a crash. In standard physics this is a simplification. As the brief requires, the
game keeps the textbook's wording in the question and explanation, and adds a separate,
clearly labelled **"Science note · supplementary"** where it matters:

* Mission 03, statement 1 (potential → kinetic in a crash);
* Mission 02, Q6 (the textbook's definition of the work-energy principle).

## Missing or deliberately excluded material

* **`quiz_questions.md` (the deck's Game 2 / Vocabulary Battle question bank) was not supplied.**
  Mission 02 was therefore built only from textbook items quoted in the guide (Tasks 3 and 4
  and the abstract). No question was invented beyond choosing distractors from the unit's
  own vocabulary list. If you have `quiz_questions.md`, compare and replace Mission 02 in the
  JSON, then run `python manage.py seed_energy_lab`.
* **Listening (Tasks 6–7)** is not a game mission. The official audio was not available, and
  gap 5 of Task 7 is not printed in the textbook, so it cannot be scored honestly.
* **Writing (Task 9)** and **Speaking (Task 8)** are not auto-scored. Use the host's manual EP
  buttons ("Excellent explanation", "Speaking participation", "Engineering design challenge",
  "Good teamwork"). Every adjustment is logged with a reason.

## Editing content

Edit `fixtures/energy_lab.json`, then run `python manage.py seed_energy_lab`. The loader
validates every answer key: the option must exist, matching must pair every item, and ordering
must be a permutation. It upserts by mission/question order, so past session history stays intact.
