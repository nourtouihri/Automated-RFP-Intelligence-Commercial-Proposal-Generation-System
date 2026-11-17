# OliveSoft proposal generator

Turns a detected tender, its prospect research and the RAG matches into a 9-slide proposal deck (.pptx and PDF),
with a requirements matrix that scores every requirement against OliveSoft's own CVs and projects.
Code decides every fact (scores, names, years, delivered status); the model only writes prose, one small section at a
time, and every reply is checked before it reaches a slide. When the evidence is too weak, it writes a no-bid deck instead.

**Bonus items covered:** PowerPoint export and PDF export (LibreOffice), and the requirements matrix with match
scores, on a slide and as a CSV of every requirement.

## Try it in two minutes

From the repository root, Python 3.10 or later:

```bash
pip install -r proposal/requirements.txt
python -m proposal.demo
```

With no API key this **replays** a recorded `gpt-oss-20b` run: the tender, its RAG hits, the source records and the
model's replies are read from `proposal/showcase/recordings/`, and today's code composes, checks, renders and
exports them. No key and no network are needed. It writes to `out/`, for three tenders, `<id>.pptx`,
`<id>.matrix.csv` and, if LibreOffice is installed, `<id>.pdf`, and prints each tender's matrix and bid warnings.

| Option | Effect |
|---|---|
| `python -m proposal.demo tender-014` | One tender only (recorded: `tender-001`, `heldout-001`, `tender-014`) |
| `--live` | Call the model instead of replaying (needs `LLM_API_KEY` and `LLM_URL`, from the environment or the repo's `.env`). Default model `openai/gpt-oss-20b`. Retrieval is not re-run: it uses the recorded RAG hits. With `PROPOSAL_VERIFIER_LLM_MODEL` set, the grounding verifier judges the decks live on its own model; without it the demo says the check is off |
| `--replay` | Replay even when a key is set (with a key and neither flag, the demo runs live) |
| `--out DIR` | Output folder (default `out/`) |

For the PDF, install LibreOffice and set `SOFFICE_PATH` to `soffice` if it is not on `PATH`. Without it, the demo
says "PDF skipped" and writes the rest. The finished decks are already in `proposal/showcase/`.

## Branding

The cover shows the OliveSoft horizontal lockup; every other slide shows the symbol in the bottom-right corner, next to
the page number. The files are in `proposal/assets/` and their paths in `proposal/config.py`
(`logo_lockup`, `logo_symbol`). Both PNGs were rendered once, transparent, from `OliveSoft_Horizontal_Lockup.svg`;
the symbol is the lockup's own symbol, cropped, because the supplied `OliveSoft_Symbol.png` (kept unchanged) has a white
background. A missing or unreadable logo stops the build with an error naming the file, before anything is written.

## The showcase (`proposal/showcase/`)

Three decks from real runs, made by `python -m proposal.demo --replay --out proposal/showcase` (pptx, PDF and CSV each).

| Tender | What it shows |
|---|---|
| `tender-001`: HRIS integration across 11 countries | A strong match: 2 Strong, 1 Partial, 1 Gap. Every evidence line traces to a CV or project record |
| `heldout-001`: patient record interoperability (a held-out tender, never tuned on) | An honest weak case: 2 Partial, 3 Gap, and the warning "no requirement has strong evidence". The model wrote "Not applicable." as one Partial row's evidence; code replaced it with "Related asset only, flagged for review" and a bid warning quotes the model's line |
| `tender-014`: catering and facilities framework | The no-bid deck: every requirement below 0.40, so no model call was made and the deck says why |

Research was not run in these runs, so the buyer profile is estimated from the tender by `proposal/estimate.py`
(sector rules, the size the tender states with its EU SME band, named products; no revenue is guessed) and each field is labelled "(est.)"; `Proposal.estimated`
lists every formula-filled field for a reviewer to re-check. The slide's title and source line say that the
facts come from the tender text, and a bid warning says research was unavailable.

## How we keep it honest

Every number below was measured; the source is in the last column.

| What | Measured | Source |
|---|---|---|
| Tests | 301 pass, 0 skipped, 0 expected failures | `python -m pytest proposal/tests` |
| Mutation check: features broken one at a time that no test notices | **0 of 68** on the last full run; a run over 77, including this round's logo, font and ingest-warning checks, is in progress | `proposal/feasibility/mutation_check.py`; earlier results in `proposal/feasibility/results/audit.md` |
| Odd inputs (no requirements, no title, no CV hits, bad similarities, duplicates, 25 requirements, very long names, ...) that crash or give a broken deck | **0 of 13** (7 of 13 before the fixes) | `results/audit.md`, "What each odd input does now" |
| Real run, 14 simulated tenders, `gpt-oss-20b` | 11 proposals, 1 no-bid deck, 2 failed after 3 attempts. Both failed steps pass when the recorded replies are replayed through the current code, which cuts the best over-length reply | `results/audit.md`, "After the fixes" and "Follow-ups" item 1 |
| Model replies rejected by the checks and retried | 38% (60 of 158), mostly over-length text | `results/audit.md`, "Why rejected replies rose" |
| Citations: a reply may cite only the asset ids in its own inputs | 3 of 158 replies cited another id and were rejected; ids are never mapped to a near match | `results/audit.md`, same table |
| No-bid rule (every requirement below 0.40) | Fires on the off-topic tenders `tender-014` (catering) and `heldout-003` (school construction). On main's corpus it also fires on `heldout-002` (parcel tracking, best match 0.37), a false no-bid; on the `fix/data-rag` corpus that tender scores 0.47 and bids | `results/audit.md`, "The no-bid rule"; `results/data_rag_check.md` |
| Held-out tenders (5, written blind, never tuned on) | 3 proposals, 2 no-bid decks; 0 Strong rows of 24 on main's corpus, 3 of 24 on `fix/data-rag` | `results/audit.md`; `results/data_rag_check.md` |
| Claim check (numbers and names the inputs do not contain) | 0 real inventions among 11 flags on fresh decks, so it is **off by default** (`claim_check=True` turns it on) | `results/audit.md`, "The claim check, judged on fresh decks" |
| Speed promises: prose saying "same-day", "immediately", "instant" or "real-time" when the tender states a duration or deadline (and does not use the word itself) | 11 hits in 53 recorded decks, all real overpromises (e.g. "immediately" against "within one day"); each becomes a bid warning | `proposal/feasibility/speed_check.py`, `results/speed_check.json` |
| Evidence lines that disclaim their asset ("Not applicable.", "No relevant evidence") | 1 of 152 recorded evidence replies; code writes the cell instead and warns | `compose.DISCLAIMS`; tests in `proposal/tests/test_facts.py` |
| Output validity (A7): slides, PDF pages and CSV rows of the three showcase decks | 9/9/9 slides and pages for the two proposals, 3/3 for the no-bid deck; CSV rows equal the tender's requirement count in all three | `proposal/feasibility/output_check.py`, `results/output_check.md` |
| Missing or broken template assets (A8): logo missing or corrupt, no font, brand fonts missing, no LibreOffice | A clear message every time, never a traceback, never a partial file. Logo or font missing: exit 2, nothing written. Brand fonts missing: a valid deck plus a warning naming the substitute. No LibreOffice: .pptx and CSV written, "PDF skipped" | same |
| Deck validator (overflow, table cells, palette, cited ids, a logo covering text) | Gates every deck: a deck with issues is not written | `proposal/build.py`; tests in `proposal/tests/test_inputs.py` |

What code writes, never the model: every score and Strong / Partial / Gap label (0.55 and 0.40,
`proposal/schemas.py`), the text of every Gap row, names, roles, years, skills, sectors, delivered status, the buyer
profile, prices, and the no-bid text.

## What is not done

- **Not wired.** The HTTP service (`POST /proposals/{tender_id}` on port 8003) does not exist yet, and n8n does not
  call the generator. What it needs from research is in `proposal/RESEARCH_CONTRACT.md`; the full integration
  write-up is shared separately.
- **No rate card.** Each phase is priced as weeks × 5 days × team size × day rate, from placeholder figures in
  `proposal/config.py` (`day_rate`, `team_size`), so the slide reads "Indicative". A plan over `long_plan_weeks`
  (26) adds a bid warning.
- **The cutoffs were fitted on synthetic data.** 0.55 and 0.40 come from 53 hand-labelled rows from 13 simulated
  tenders, one embedding model and main's corpus. On held-out tenders and on `fix/data-rag`, 0.40 holds and 0.55 is
  no more precise than 0.45 (`results/data_rag_check.md`).
- **The data is synthetic.** CVs and projects are generated. They have no status field, so every reference shows
  "Unverified": outcome text can mark a project not delivered, never delivered.
- **Research was not run** in any measured run.
- **The prose can still overclaim in lowercase.** The speed check catches promises faster than the tender's own
  timeline, but not other capability claims (for example "ensuring compliance"). Bid warnings and a human read
  still come first. What exists for this now is the **opt-in grounding verifier** (`proposal/verifier.py`): a
  judge on a *different model* than the writer reads each accepted reply's checked prose fields against exactly
  the sources they cite (its chunk and source record; uncited fields against the step's input) and rules each
  claim `supported` / `partial` / `unsupported`. Code re-finds every "supported" quote inside those sources
  before believing it; a supported without a findable quote is downgraded to partial. Verdicts never touch deck
  text: partial and unsupported become bid warnings. It runs when `PROPOSAL_VERIFIER_LLM_MODEL` names a judge
  (never the writer's model); unset means off, and the demo says so. `feasibility/run_verifier.py` measures it
  on the recorded decks (flags on real prose, recall on an injected unsourced claim) - its numbers in
  `proposal/feasibility/results/` are the gate for ever turning it on by default.
- All tenders so far are short English texts written by the team.

## Package map

| Path | What it is |
|---|---|
| `demo.py` | The demo above: replay or live, writes .pptx, PDF and CSV |
| `compose.py` | The filling pipeline: input checks (`InputError`), facts by code, the no-bid gate, then brief and 5 scoped writer steps with citation and schema checks, retries with exact feedback (3 attempts), last-resort cut; an optional verifier judges accepted replies (verifier=) |
| `schemas.py` | The `Proposal` and `NoBid` contracts, length limits, Strong/Partial/Gap cutoffs |
| `config.py` | Everything OliveSoft-specific (company sentence, next steps, signatory, currency, footers) |
| `render.py`, `measure.py` | python-pptx renderer (themes `website` and `sample`) and text measurement |
| `validate.py`, `build.py` | Deck validator, and the gate that writes a deck only when it passes, plus the matrix CSV |
| `export.py` | PDF through LibreOffice headless; matrix CSV |
| `claims.py` | The opt-in claim check |
| `verifier.py` | Agent E, the grounding verifier: a judge on a different model than the writers, rules each accepted claim `supported`/`partial`/`unsupported` against its cited source; verdicts become bid warnings |
| `llm_adapter.py` | `llm(system, user)` for any OpenAI-compatible endpoint, with rate-limit, quota and retry handling |
| `showcase/` | The three decks and their recordings |
| `tests/` | The test suite (fake LLM, no network) |
| `feasibility/` | Measurement scripts (real run, held-out tenders, audit, mutation check, `fix/data-rag` and `phase2` checks, recordings) and their results in `feasibility/results/`; `run_verifier.py` audits the grounding verifier over the recorded decks |

Other commands, from the repo root:

```bash
python -m pytest proposal/tests
python -m proposal proposal/sample_maison_aurele.json out/sample.pptx   # render a deck JSON; exits 1 and writes nothing if the validator objects
python -X utf8 proposal/feasibility/run_llm.py <out_dir> --reasoning-effort low   # the real run (needs a key)
```

**Fonts:** the deck uses Montserrat and Inter (static Regular and Bold TTFs). Text is measured with the installed font
files (`/usr/share/fonts`, or the Windows system and per-user font folders). Without them it falls back to DejaVu
Sans or Arial, and rendering fails rather than skip the overflow check when no font is found.
