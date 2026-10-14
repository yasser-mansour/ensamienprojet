# ENERGY LAB nine-presenter operations deliverables

Recovery on 14 October 2026: supplied folder had no Git metadata. Recovered GitHub repository `yasser-mansour/ensamienprojet`, branch `claude/ensamien-classroom-platform-cl7v5e`, commit `306eb20`. The three available application commits contain no reported 105-page manual, generators, manual dataset, nine dossiers or manual QA script. Claude's uncommitted cloud workspace was not accessible. Existing technical/rehearsal docs and all application content were reused; manual generation was necessarily implemented anew.

The supplied PPTX contains 88 slides and 88 speaker notes. The older guide contains 12 pages, the student dossier two pages, and the deck PDF 88 pages. Source copies used by the generator are in `source/`; full original slide texts/notes are in `slide_source.json`. Original notes contain eight-presenter assignments and some timing conflicts: the manual's nine-presenter registry and timeline supersede them. No application code, configuration, database or deployed service was changed.

## Outputs

All final files are under `deliverables/`:

- ENERGY_LAB_NINE_PRESENTER_OPERATIONS_MANUAL.pdf (85 pages)
- ENERGY_LAB_PRESENTER_01.pdf through ENERGY_LAB_PRESENTER_09.pdf (exact dossier extracts)
- ENERGY_LAB_QUICK_REFERENCE_CARDS.pdf (nine pages)
- ENERGY_LAB_ROLE_ASSIGNMENTS.md
- ENERGY_LAB_MASTER_TIMELINE.md
- ENERGY_LAB_REHEARSAL_CHECKLIST.md
- ENERGY_LAB_FULL_MANUAL.md (additional editable full manual)
- manifest.json (page extraction ranges, source hashes, owners, timing)
- QA_REPORT.json (42 automated checks)

## Rebuild

Python dependencies for the documentation pipeline only: `reportlab`, `pypdf`, `pymupdf`, `Pillow`. Do not add these to the Django deployment requirements. The generator currently uses macOS Arial fonts at `/System/Library/Fonts/Supplemental/`; supply compatible embedded font paths if rebuilding on another OS.

From repository root:

```sh
python3 docs/operations/generate.py
python3 docs/operations/qa.py
```

QA verifies exact extracted text and rendered pixels for every dossier page, all nine single-page cards, all 88 owners, timeline continuity, mission counts, source checksums, text margins and embedded rendered fonts. Text uses plain numbered option labels and ASCII hyphens/arrows to avoid missing bullet/symbol glyphs. No tables are used in the generated PDF, so table overflow is inapplicable.

Representative rendered pages were reviewed from every major section and all nine dossier openings, cue pages, preparation pages and cards, with higher-resolution review of host instructions, the matching answer sheet and captain/co-pilot cards. No clipping, broken glyphs or visual defects were observed. Render previews are reproducible and excluded from version control.

## Content decisions and limits

- P1 captain, P9 technical co-pilot; P3 covers final host clicks while P9 teaches.
- Reading slides 35-40, Crash Detective 41-55; language teaching 56-61, Error 404 62-72.
- Five source-fixture missions contain 5/8/7/5/1 questions. Use the fixture-based manual sheets offline as well, since the local quiz bank differs from the app.
- App final mission is 300 EP; older deck double-EP label is documented as a legacy difference.
- Four writing minutes start the report; complete the 100-120 words after class.
- Official textbook pages and listening audio/key were not supplied; Task 7 gap 5 is unverified and ungraded. Labels trace to supplied quotations and fixture, not independent textbook verification.
- Application behavior was inspected statically. Deployed database content, real devices, Wi-Fi, projector and actual 105-minute performance require the included classroom rehearsal checks.
- Nine presenter PDFs retain master page numbers; the manifest gives exact ranges. Quick-card PDF has independent page numbering.
