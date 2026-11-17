# Audit: hard-coding and hallucination (2026-10-19)

Branch `feat/proposal-generator` at `4efa2f6` plus **uncommitted** changes (nothing committed, nothing pushed).
LLM runs: `openai/gpt-oss-20b`, `reasoning_effort=low`; `max_tokens=1024` in the audit, `max_completion_tokens=2048` after the fixes.
The first part of this file, "After the fixes", is the re-run; everything from "Verdict" down is the audit as found,
before any fix. Raw data: `audit_claims.json`, `audit_labels.csv`, `llm_run.json`.

## After the fixes (same day, 2026-10-19)

All 8 items are done. Nothing is committed or pushed. The sections below this one are the audit **as found, before
the fixes**; they are kept unchanged so the comparison stays honest.

| | Audit (before) | After the fixes |
|---|---|---|
| Tests | 96 (86 pass, 10 fail) | **198 pass**; 0 failing, 0 xfail, 0 skipped |
| Odd inputs that crash or give a broken deck | 7 of 13 | **0 of 13** (see "What each odd input does now") |
| Mutations the tests do not notice | 13 of 33 | **0 of 50** (the 33 earlier ones plus 17 for the new features; the check is `feasibility/mutation_check.py`) |
| Simulated tenders (14), gpt-oss-20b | 13 proposals, 1 failed | 11 proposals, **1 no-bid deck**, 2 failed |
| Held-out tenders (5) | 5 proposals | 3 proposals, **2 no-bid decks** |
| Replies rejected, simulated | 27% (37 of 138) | **39% (49 of 127)** |
| Replies rejected, held-out | 31% (13 of 42) | **35% (11 of 31)** |
| Fields cut by code, simulated / held-out | 3 / 3 | 12 / 2 (2 of the 14 were lists) |
| Banned-word warnings, simulated / held-out | 11 in 13 decks / 6 in 5 | 6 in 11 decks / 2 in 3 |
| Claim-check precision | 2 of 79 flags real (2.5%) on decks I had read | **0 of 11 clear, 1 borderline**, on fresh decks |
| Claim check | on | **off by default** (`--claim-check` turns it on) |
| No-bid decks | none | `tender-014`, `heldout-002`, `heldout-003` |
| Thresholds 0.55 / 0.40 | untouched | untouched |

The re-run used 162,841 tokens of gpt-oss-20b (`reasoning_effort=low`, `max_completion_tokens=2048`); the daily cap
was not reached. The simulated and held-out runs are `olivesoft/llm-run-final-sim` and `llm-run-final-heldout`.

### Two outcomes that went the wrong way

- **Fewer proposals.** 11 of 14 simulated tenders gave a proposal, against 13 before. The two failures are real
  retry failures, not infrastructure:
  - `tender-003`: two over-length `brief` replies, then a third that hit the 2,048-token cap (2,007 of them
    reasoning) and was cut off, so there was nothing to trim. The second reply was over by 3 characters and would
    have been trimmed to a valid deck; the cut only looks at the **last** reply. Keeping the last *trimmable* reply
    instead would have saved this tender. I did not change it: it is a pipeline decision, and it is not one of the
    eight items.
  - `tender-009`: `CV-022` (a near miss of the real `CV-0022`), then an over-length reply, then `CV-006` (a near miss
    of `CV-0006`). The retry after `CV-022` listed the exact ids; the model then dropped a zero again. Code does not
    repair it, as specified.
- **More rejected replies** (39% against 27%; 35% against 31%). I did not identify the cause. 51 of the 158
  attempts were over-length strings. Candidates: the new `cite only these ids` line in the prompt, the 2,048-token
  cap letting the model reason longer about character counts, or plain run-to-run variation (the earlier runs
  ranged 26% to 31%). Measuring needs a controlled A/B run on the same tenders.

### What each odd input does now (the choices I made)

| Input | Behaviour | Why |
|---|---|---|
| Tender without a title or an issuer | `InputError` naming `tender.title` / `tender.issuer`, no LLM call | The deck cannot name its buyer |
| No requirements | `InputError`, no LLM call | The matrix would be empty |
| No CV hits | Continue: a placeholder card (`[__]`, "No match") and the bid warning "no CV matched: the team slide is a placeholder" | A deck without a named team still has value; F7 says unknown values render `[__]` |
| No project hits | Same, with "no project matched" | Same |
| Similarity below 0 or above 1 | `InputError` naming the list and the hit, no LLM call. Float noise within 1e-6 of 0 or 1 is clipped, not an error | 1.0000001 comes from rounding, not from bad data |
| A hit without `metadata.record_id` | `InputError`; it no longer falls back to the chunk id | The fallback silently produced empty facts |
| Duplicate record ids | Removed, keeping the best-ranked one, before anything else | |
| More than 7 requirements | The 7 best by score are shown, in the tender's order; the bid warning says "7 of 25 requirements shown; the full list is in the CSV; 5 of the 18 hidden requirements are Gap". `<deck>.matrix.csv` lists all of them | Hiding the weakest rows is the dangerous way to cut, so the warning says how many of the hidden ones are Gap |
| Very long buyer name | Cut with an ellipsis in every data field; an unbroken word is cut by characters | The footer could overflow on every slide |
| Every requirement is Gap | `NoBid`: cover, matrix and warnings, and a line written by code; no model call. `force_bid` overrides | Your item 5 |

A row scored 0.3999 used to be called weak by code but labelled Partial on the slide, because the label uses the
rounded score. The weak test now uses the rounded score too (0.40 or more is Partial everywhere).

### The no-bid rule on the 19 tenders

It fires on **`tender-014`** (catering) and **`heldout-003`** (school construction), as you expected, and not on the
healthcare or telecom tenders (`heldout-001`, `heldout-004`). It also fires on **`heldout-002`** (parcel tracking):
an on-topic data and ML tender whose best row scores 0.37. That is a false no-bid on the evidence available, and it
is the cost of cutoffs that are not trusted on new sectors. It is why I would not widen the rule before Task 3.
(Computed offline with an LLM that refuses to be called, then confirmed live: the three no-bid tenders spent 0 tokens.)

### The validator now blocks

`build()` (and `python -m proposal data.json out.pptx`) renders to a temporary file, validates, and writes the deck
only if it passes. With issues the CLI exits 1 and writes nothing; `--allow-issues` writes it and adds each issue to
the bid warnings as `validator: ...`. Tests prove it with a real overflow, a real oversize table cell and a real
off-palette colour (each is injected into a rendered deck), so the validator is no longer an untested component.

### The claim check, judged on fresh decks

Scope is now running text only (letter, summary and need/approach bodies, evidence lines, key messages), and
known asset ids are removed first. Names are checked only as CamelCase or ACRONYM tokens and as runs of two or more
capitalised words with no word in any input. Titles, labels and greetings are out of scope. The first-word problem
that caused the `Azure Kubernetes` miss is fixed.

I judged the 11 flags from the new generations (the 11 simulated proposals, the 3 held-out proposals, and the two
held-out tenders the no-bid rule skips, which I wrote with `--force-bid` for this purpose). Each flag was read against
the tender text.

| Judgment | Count |
|---|---|
| Real invention | **0** |
| Borderline | 1 (`KPIs` in `tender-005`: a generic term the tender does not use, no new fact) |
| False alarm | 10 |

The false alarms are abbreviations of phrases the tender uses (`ML` for machine learning, 4 times; `NLP` for
"natural language processing"; `EHRs` for electronic patient record systems; `ID` and `IDs` for "identifier", 3
times) and the word "delivered" used as a verb about status updates. **Precision is 0 to 9%, far below 50%, so it
ships off by default.** The eight decks you named (5 held-out, 3 simulated I had not judged: `tender-002`,
`tender-006`, `tender-010`) carry 3 of the 11 flags, all false alarms. The sample is small, and the real inventions in
the earlier decks were lowercase overclaims that this check cannot see, so the honest reading is: with the noise
removed there was almost nothing left for it to find in running text, and it should stay off until it is worth
turning on for something concrete.

### A bug the re-run found in my own code

`compose()` let a raw `ValidationError` escape on one forced held-out tender. The cause: when a list is too long,
pydantic reports only the list error. The last-resort cut trimmed the list, which exposed a too-long item that the
first error never mentioned, and the final validation raised. A fuzz over 3,000 random replies showed **636 escaped**
for the letter schema alone. It is fixed (the cut is checked again, up to 3 passes, and a reply that still cannot be
made valid becomes a `StepError`), with a pinned regression test and a seeded fuzz over all five schemas. I replayed
every recorded reply from the re-run through the fixed code: all 20 outcomes and decks are identical, so the numbers
above stand.

### Tests I changed because the spec changed (none loosened)

- The claim tests that expected a lone capitalised word, or a name in a title, to be flagged now expect it not to be
  (your item 6). The Title Case headline test is now `test_titles_and_labels_are_outside_the_claim_check`: it
  asserts the opposite of what it did.
- The invented-claim tests inject into running text (`key_messages`) rather than `subtitle`, and no longer expect the
  one-word names `Initech`, `Epic`, `Europe`, `Gartner`. **An invented one-word client name is now a known miss.**
- A full proposal from all-Gap retrieval now needs `force_bid=True` in two tests.
- The adapter test expects `max_completion_tokens: 2048` and no `max_tokens`.
- The fake reply that cited `CV-0002` when no CV is supplied was rejected by the citation check, rightly; the tests
  now cite only ids they provide.
- The sample JSON files gained the keys that used to be defaults (signatory, letter title, approach title, currency,
  note), with the same values: the rendered sample is character-for-character identical (checked on both themes).

### Items 7b

`is_delivered` uses an explicit status (`status`, `evidence_status`, `is_completed`) when the data has one, and treats
"not completed", "cancelled", "in progress", "on hold", "proposed" as not delivered. **Where a record has no status
at all, as with the synthetic projects, a non-empty outcome still counts as delivered unless it says otherwise**;
without that fallback every synthetic project would show as Proposed. That is the part of your request I could not
fully meet on this data, and it needs a status field in the data. The approach title works for any number of phases;
the stale numbers in the comments now read 14 of 16 and 10 of 17; all OliveSoft-specific text (company sentence,
the "Why OliveSoft" task line, offices, next steps, signatory, currency, footers) is in `proposal/config.py` and is
passed to `compose()` and `render()`.

### Follow-ups, after your answers (same day)

**1. The last-resort cut now uses the best reply from any attempt.** When every attempt fails, code cuts the reply that
was only over-length and ran over the least, from any attempt, not just the last. A candidate that cites an id outside
its inputs, or is wrong in another way, is never cut. The trace records which attempt was used (`trim_attempt`).
Tests pin: a truncated third reply with a good second one, an earlier smaller overage beating a later larger one,
an invented id disqualifying a candidate, and a too-long reply with an extra key staying an error. Two new
mutations (use only the last attempt; do not record the attempt) are both caught. Replaying the recorded replies of the
two failed tenders through the new code: the failing step now passes in **both** (`tender-003`'s `brief`, cut from
attempt 2; `tender-009`'s `summary`, cut from attempt 2). A live re-run of those two tenders gave proposals, but the
model answered correctly that time, so the fallback was not needed; the evidence for it is the replay and the tests.

**2. Why rejected replies rose: counted from the logs of the last two runs** (19 tenders each; before is
`llm-run-20b-v2` plus `llm-run-heldout`, after is `llm-run-final-sim` plus `llm-run-final-heldout`).

| | Before | After |
|---|---|---|
| Attempts / rejected | 180 / 50 (28%) | 158 / 60 (38%) |
| Too long | 34 (19%) | **51 (32%)** |
| Truncated at the token cap | 4 | 1 |
| Invalid JSON | 3 | 2 |
| Citation | 3 | 3 |
| Other schema error | 6 | 3 |
| Mean reasoning tokens a call | 126 | 119 |

Rejected over attempts, by step: `brief` 3/22 (14%) → **14/26 (54%)**; `letter` 12/30 (40%) → 14/27 (52%);
`summary` 9/27 (33%) → 10/23 (43%); `needs` 9/26 (35%) → 8/21 (38%); `evidence` 4/46 (9%) → 5/40 (12%);
`approach` 13/29 (45%) → 9/21 (43%). The fields that overran most: `brief.subtitle` 3 → **10** (limit 80),
`letter.paragraphs` 3 → 7, `approach.phases.name` 10 → 9 (the top field in both runs).

**What rose: length overruns in `brief.subtitle` and `letter` paragraphs, and nothing else.** Truncations fell (the
2,048-token cap helped there) and reasoning length did not rise, so neither is the cause. The rise is unlikely to be
noise (too-long replies p = 0.006; `brief` p = 0.006; all rejections p = 0.049, Fisher exact), though `brief` first
attempts alone (2 of 19 against 6 of 16) are not significant. The only prompt text that differs between the two runs
is a clause telling the model to cite only the ids it is given, which has nothing to do with the length of a subtitle.
**The logs do not explain why**, so an A/B is justified, and I would keep it small: the `brief` step alone, 7 tenders
by 3 repeats by 2 prompt variants (with and without that clause), 42 calls, about 60,000 tokens. I have not run it.

**3. Project data.** Not edited. The status question is recorded for Task 3 and answered in `data_rag_check.md`: the
branch's projects have no status field either (`synthetic: true` for all 149, 33 null outcomes, the rest templated
text), so `is_delivered` still has to guess from the outcome.

**4. Commit.** You wrote "only if I said so" and you have not, so nothing is committed.

**5. Evidence and reference cards come only from CV and project records.** On the `fix/data-rag` corpus, website and
client pages were reaching the matrix (5 of 16 Strong rows) and the reference cards (4 of 42). `compose()` now reads
each hit's `metadata.original_doc_type` (or `doc_type`) and accepts only `cv` and `project` records as requirement
evidence, `cv` records in team slots and `project` records in reference cards (PFE ideas still fill empty slots, F10).
Company profile, service, client and project-reference pages are given to the summary step as `COMPANY_PAGES`, for
the "Why OliveSoft" line only; citing one is rejected like any invented id. Six tests and five mutations (M53 to M57,
all caught) pin it. On main's corpus nothing changes: no row or card in the last two runs used a tool record, and
main has no website pages. The `fix/data-rag` numbers in `data_rag_check.md` are from the re-run with the filter.

**Task 3** is in `data_rag_check.md`. Headline: the chunks carry no `metadata.record_id` (the ingest adds it); 0.40
holds and 0.55 is no better than 0.45; the OliveSoft boost is gone and ideas now top 3 of 57 rows instead of 19 of 53;
`heldout-002` improves from 0.37 to 0.47 and bids; the no-bid rule fires only on the two off-topic tenders.

## Verdict

- **The pipeline works on tenders it was not tuned on, at the structural level.** 5 held-out tenders in unused
  sectors gave 5 of 5 decks, a 31% rejected-reply rate (27% on the 14 simulated tenders), and 0 validator issues.
- **It does not work on every input.** 7 of 13 generated input classes end in a crash or a broken deck instead of a
  clear error, and most of the crashes come *after* the LLM calls were already spent (4 to 11 calls). 10 of the 96 tests fail,
  on purpose; each is a real gap, listed in Part B.
- **The fitted values do not carry over cleanly.** On the held-out tenders there are 0 Strong rows out of 24 (33% on
  the 14 simulated) and 71% Gap (31%). The 0.55 / 0.40 thresholds were fitted on the same 13 tenders they are
  judged on, so this is the expected failure, and it is large.
- **The new hallucination check is mostly noise.** Of 79 flags, 2 were real inventions (2.5%) and 77 were false
  alarms. Every deck now carries about 4 to 5 spurious bid warnings. The check also cannot see lowercase technical
  claims or capability overclaims, which is where the real inventions are.
- **Every tender in these runs was written by someone on the team, in the same short English style.** Nothing here
  says how it behaves on a real 20-page tender.

## Part A: hard-coding audit

"Same data?" means the value was chosen or fitted on the same tenders it is later judged on.

### A1. Ids, tender numbers, names, sectors, phrases from our tenders

Production code, prompts and schemas contain **no** tender ids, `PRJ-`/`CV-` ids, client names or sector words
(grep for `tender-0`, `PRJ-`, `CV-`, `Employee_`, `olivesoft-0` and the client names finds them only in fixtures,
docstrings and one comment). What is hard-coded is OliveSoft itself, and the layout of its data.

| file:line | What is specific | Same data? | How to make it general |
|---|---|---|---|
| `compose.py:115` | `COMPANY` names OliveSoft and its four offices; it is also what the claim check treats as support | no | Read it from a config object passed to `compose()` |
| `compose.py:449-451` | Next steps "Discovery session / Express data audit / Sign and kick off" and their timings come from olivesoft.fr | no | Config or an argument |
| `schemas.py:38-39` | Signatory "Head of Sales, OliveSoft", `sales@[domain]` | no | Config |
| `schemas.py:153,155` | Currency `€`; the pricing note | no | Config |
| `schemas.py:118`, `compose.py:442` | Approach title is built from `('Two','Three','Four')[n-2]`, so it only works for 2 to 4 phases | no | Generate the title from `n`, or take it from config |
| `render.py:24-35,64-66` | Brand palettes and fonts (Inter, Montserrat), `TOTAL = 9` slides, a 1280x720 canvas (`:79`) | no | Fine for one brand; make theme and slide list data-driven for another |
| `render.py:170,265,329,352,405,428` | Slide footers and sources ("OliveSoft · Data & AI", "Source: CV bank retrieval", ...) | no | Strings from config |
| `compose.py:325-327` | `is_idea` tests for the label `pfe_internship_project`, which exists only in `olivesoft_projects.json` | yes (data shape) | A predicate or a `status` field on source records |
| `compose.py:414-416` | Consultants are reordered so their distinguishing skills come first. Written because the synthetic CVs from one past team share their first five skills | yes | Harmless on real CVs; drop or keep behind a flag |
| `feasibility/calibrate.py:11` | Mentions CV-0007 (a comment) | yes | Comment only |

### A2. Values fitted to this data

| file:line | Value | Fitted on the same tenders it is judged on? | How to make it general |
|---|---|---|---|
| `schemas.py:99-100` | `STRONG_AT = 0.55`, `PARTIAL_AT = 0.40` | **Yes.** Fitted on 53 hand-labelled rows from 13 simulated tenders, with one embedding model (MiniLM) on main's 224-chunk corpus. The comment at `:97-98` and `compose.py:396` quote stale numbers ("12 of 15", "11 of 17"; the report says 14 of 16 and 10 of 17). Held-out rows: 0 Strong of 24 | Recalibrate per corpus and model from a labelled set that is not the one being judged; store the cutoffs with the corpus, not in code |
| `compose.py:56-65` | `BANNED_WORDS` (proven, seamless, ...). The list came from you after seeing outputs on these tenders; the `zero disruption` pattern at `:60` (also matching "zero service disruption") was added after seeing tender-006 | **Yes** | The words recur on unseen tenders (1.2 hits per held-out deck against 0.8), but words that appeared and are not listed: "immediately", "seasoned", "strategic", "robust", "holistic". Keep a list per client, or check against the tender's own wording |
| `compose.py:46`, `:133-142` | `MARGIN = 0.85`; "about 10/14/15/30 words" length hints | **Yes**, chosen after seeing the 20b length failures on these tenders | Held-out rejected-reply rate is 31% against 27%, so no sign it was overfit. Derive the hints from each schema field's limit |
| `compose.py:45` | `MAX_ATTEMPTS = 3` | **Yes**, chosen after the 2-attempt experiment (4 of 14 decks) | Make it a parameter; it is a cost against a model's length discipline, so it will move with the model |
| `llm_adapter.py:93-96,116` | 2 s between calls (Groq's 30 requests a minute), a `Retry-After` above 120 s means "daily quota", 3 retries, 20 waits | **Yes**, and Groq-specific | Read the limits from the provider's response headers instead |
| `compose.py:367,382,410,422,349,371` | At most 7 requirements, 3 CVs, 3 projects, 5 skills; asset text cut at 500 characters, tender text at 3000 | no (layout-derived), but **silent**: a 25-requirement tender shows 7 rows and says nothing | Warn when anything is dropped; cut by score, not by position |
| `schemas.py:57,77,165-168` | Exactly 3 pillars, 1 to 3 needs, 1 to 7 requirements, 1 to 3 consultants and references | no | A slide-count limit is fine; an empty list should be a clear error before any LLM call |
| `claims.py:92` | Title Case rule: at least 4 words of 4 or more letters, 60% capitalised | Chosen on synthetic strings, then judged on the decks and **not retuned**. It misfires: a short sentence with the first word capitalised counts as Title Case | Exclude the sentence-initial word from the ratio, or only check running text |
| `claims.py:31-41` | Status words, currency list, spelled-out numbers (two to ninety-nine), all English | no | Per-language lists |

### A3. Tests that pass when the feature is broken

I broke one feature at a time in a scratch copy and ran the tests (`feasibility/mutation_check.py`, 33 breakages
applied). On the 36-test suite from before this audit, **16 survived**. After adding the general tests, **13 still
survive**. These features have no passing test that notices when they break:

| Broken feature | Why no test notices |
|---|---|
| `STRONG_AT` 0.55 -> 0.30 (`schemas.py:99`); `fit_for` returning Strong for Partial (`schemas.py:103-107`) | Every fixture score is 0.87 or higher or 0.17; nothing sits near a cutoff |
| `is_delivered` ignoring `evidence_status == "proposed"` (`compose.py:330-339`) | The branch is covered twice over by `is_idea`, so the test passes either way |
| Distinguishing skills first (`compose.py:416`); team cut to 1 consultant (`:410-412`) | The fixtures contain a single consultant |
| Asset and tender text caps (`:349,371`) | No test passes long text |
| `load_records` reading only `cv_id` (`:309-318`) | `load_records` has no test at all |
| `validate()` running no overflow, table or palette check | No test builds an overflowing deck and expects an issue. The tests that do are among the 10 failing ones |
| Matrix evidence column swapped for the requirement text (`render.py`) | `render.py` has no test: nothing reads a rendered slide back |
| `to_pdf` keeping the stale PDF, or dropping the private profile (`export.py`) | Only `soffice_path()` is tested, never `to_pdf()` |
| Per-user Windows font folder (`measure.py:17-18`) | The test replaces `FONT_DIRS`, so the Windows branch is never executed |

Other weaknesses I read in the tests: every test uses `fake_llm` or `stand_in`, which always return valid JSON
within limits (6 of 123 real replies in the last 12-tender run were not valid JSON); every fixture uses the same
ids (`PRJ-0003`, `CV-0002`, `Employee_002`) and exact strings; the adapter tests use a mocked transport, so Groq's
real error shape is untested.

### A4. Assumptions about the data layout

| file:line | Assumption | How to make it general |
|---|---|---|
| `compose.py:305-306` | Source files are `fake_cvs.json`, `fake_projects.json`, `olivesoft_projects.json`, `fake_tools.json`. `fix/data-rag` renames them (Task 3) | Pass the file list in, or read the files `rag` ingested |
| `compose.py:309-318` | Record id keys are `cv_id`, `project_id`, `tool_id`, `id`; a file is a list or a dict whose first value is the list | Ask the ingest for its id field |
| `compose.py:321-322` | `metadata.record_id` names the source record. The fallback is `hit["id"]`, which in production is a chunk UUID, so facts silently come out empty | Fail loudly when `record_id` is missing |
| `compose.py:337-339` | **A non-empty `outcome` text means "delivered".** True only because this dataset has an outcome only for finished projects; "Not completed" would count as delivered | Use an explicit status field |
| `compose.py:410-427` | Keys `name`/`person`, `years_experience`, `skills`, `client_sector`/`domain`, `summary`/`description`/`outcome` | Map them in one adapter |
| `measure.py:17-21,32-34` | Fonts: Windows folders or `/usr/share/fonts`; macOS is missing. Files must be static `Name-Regular.ttf` / `Name-Bold.ttf`; a variable font (`Inter[wght].ttf`) is not found | Add the macOS folders; read the family from the file |
| `export.py:11` | Default soffice path is the Windows install; macOS is not tried | Add macOS |
| `feasibility/run_llm.py:58-60,188`, `run_feasibility.py:72-76` | Corpus is main's four files; MiniLM default; `research=None` | Take them from the environment |
| `compose.py:366,432` | `tender["issuer"]` and `tender["title"]` are required, and `KeyError` is what a missing one gives | Validate the tender first |

### A5. Prompts that teach to the test

| file:line | What | Why it is a concern |
|---|---|---|
| `compose.py:122-123` | "no 'instant' or guarantees where the tender sets a deadline" | Written after "real-time consent sync" appeared in tenders 004 and 015, both of which set a consent deadline |
| `compose.py:121` | The prompt lists the same words the checker enforces | The ban and the check cannot disagree, so "banned hits per deck" is not an independent measure of the prompt. The prompt did not reduce hits: 11 in 12 decks before, 11 after |
| `compose.py:133-142` | "about 10 words", "about 15 words" | Chosen after the 20b overran those fields |
| `compose.py:60` | `zero\s+(?:\w+\s+)?disruption` | Added to catch one phrase in one deck |

## Part B: general tests

New tests: `tests/test_general.py` (39) and `tests/test_claims.py` (17); `tests/test_compose.py` grew from 9 to 28.
Suite: **96 tests, 86 pass, 10 fail**. The 10 failures are intentional reports of real gaps, not left-over breakage.
They add about 25 s to a run that took 1.2 s.

### B1. Seeded random inputs (hypothesis is not installed; I did not add it)

6 seeds per scenario. Each must end as a valid deck that renders and passes the validator, or as a `StepError`.

| Scenario | Result | What happened |
|---|---|---|
| 1 requirement; 25 requirements; unicode titles; missing `raw_text`/`id`/`deadline`/`source`; no hits for any requirement; all-weak hits | **pass** | Unicode titles (accents, Arabic, emoji) pass the validator, but Inter has no Arabic glyphs, so "no overflow" is a measurement, not a look at the rendered slide |
| 0 requirements | **fail, 6 of 6** | `ValidationError` "requirements: at least 1 item" **after 5 LLM calls** |
| very long names (400-character title, 200-character issuer) | **fail, 6 of 6** | The footer on every slide overflows (needs 36 px, box is 20 px); the validator reports it, nothing gates the deck |
| title or issuer missing | **fail, 6 of 6** | `KeyError: 'issuer'` (5 seeds) or `'title'` (1 seed, after 8 LLM calls) |
| no CV hits; no project hits | **fail, 6 of 6 each** | `ValidationError` on `team` or `references` after 5 to 10 calls |
| edge similarities (-0.2, 1.0000001) | **fail, 5 of 6** | `ValidationError: score >= 0` after 4 to 11 calls. A similarity of exactly 1.0 plus float noise is plausible for a verbatim match |
| duplicate ids | **fail, 6 of 6** | The same consultant listed 3 times; `compose()` does not de-duplicate (the real `rag` does, per record) |
| 25 requirements, silent truncation | **fail** | 18 of 25 requirements are missing from the matrix and nothing says so |

My first run of this generator was confounded: it gave every scenario a random 200-character issuer, so footer
overflows appeared everywhere. I isolated the factor into its own scenario and re-ran; the table is the second run.

### B2. Adversarial stand-ins

| Misbehaviour | Result |
|---|---|
| Cites ids that were not retrieved (3 variants) | **caught**: `StepError` naming `summary` after 3 attempts |
| A deck tampered to cite an unretrieved id | **caught** by `validate()` |
| Extra keys in any of the 6 replies, including a `score`, a `price`, a `delivered` flag | **caught**: `StepError` naming the step |
| Lists too long (5 steps) | **caught**: cut to the first items, flagged in the trace and in a bid warning |
| An empty required list | **caught**: `StepError` |
| Invented numbers, years, money, ISO and "certified", client names, "delivered" in the 6 steps | **19 of 21 claims flagged**, as bid warnings (a deck is still produced). Missed: `Azure Kubernetes` in a short sentence (the Title Case rule counts the first word), and the client name `Globex` in a Title Case headline (`test_an_invented_client_name_in_a_title_case_headline_is_flagged` fails) |
| Prose that says "every project listed was delivered" | **cannot change data**: `Reference.delivered` comes from the record |

These stand-ins were written by me knowing the check's categories, so this measures coverage, not recall in the wild.

### B3. Held-out tenders (`feasibility/heldout/`, written blind to the corpus, nothing tuned on them)

Healthcare records, parcel tracking, an off-topic school construction, telecom churn, student analytics (with a
unicode, 134-character title). Same pipeline, same settings as the 14-tender run.

| | 14 simulated tenders | 5 held-out tenders |
|---|---|---|
| Decks OK | 13 of 14 (`tender-014` failed, see B4) | **5 of 5** |
| Replies rejected | 27% (37 of 138): 34 parse, 3 citation | **31%** (13 of 42), all parse |
| Strings cut by code / lists cut | 3 / 0 | 3 / 0 |
| Banned-word warnings | 11 (0.8 a deck) | 6 (1.2 a deck) |
| Claim-check flags | 56 (4.3 a deck) | 23 (4.6 a deck) |
| Validator issues | 0 | 0 |
| Requirement rows Strong / Partial / Gap | 17 / 19 / 16 (33% / 37% / 31%) | **0 / 7 / 17 (0% / 29% / 71%)** |
| References that are delivered | 29 of 39 | 7 of 15 |

- **Pipeline behaviour generalises; retrieval scores do not.** Rejection rate, cuts and banned hits are the same
  order on unseen sectors. The Strong share is 0. Either the corpus does not cover these domains (healthcare
  interoperability, telecom, logistics tracking) or my requirement wording scores lower. I cannot tell which from
  this data, and it is untested against `fix/data-rag`.
- **7 of 24 held-out rows had score 0.00**: all 5 retrieved hits were internship ideas, so the matrix says "No
  matching asset found". The construction tender had 3 of 5 and the telecom tender 2 of 6.
- **Bid warnings behaved.** All 5 carry "no requirement has strong evidence"; the construction tender also carries
  "no delivered reference project" and "every matched consultant is a weak match".
- **But the construction deck still reads as a capability claim.** It says OliveSoft "delivers precise construction
  solutions backed by seasoned experts" and lists foundations, framing and plumbing as phases. Only bid warnings
  stand between that deck and a client.
- **Held-out tenders were written by me.** They are short English, 4 to 6 requirements, like the feed.

### B4. tender-014 and tender-015

`tender-015` completed. `tender-014` failed: the summary step cited `CV-005`, an id that was never in its inputs,
3 attempts in a row; the citation check rejected all three. That is the check working. The 14-tender figures above
include both. gpt-oss-20b use for this audit: 51,002 tokens (37,786 for the held-out tenders, 13,216 for tenders 014 and 015); the daily cap was not reached.

## Part C: hallucination check

**What it is:** `proposal/claims.py`, run in `run_step` on every accepted reply. For each prose field it extracts
numbers (digits and spelled out), percentages, years, money, ISO and certification claims, the words delivered,
certified, accredited, awarded, and proper names (CamelCase, ACRONYMS, and capitalised words in running text). It
flags any whose value is not in that step's inputs: the company sentence, the task text with its digits removed,
the step's payload, and the source records of the assets in it. Hits appear as `unsupported <kind> "<claim>" in
<step>.<field>` in the bid warnings. It is built from the spec and tested on synthetic strings; I did not change it
after looking at real decks.

I replayed every recorded reply offline through the current `compose()` (the replay reproduced each deck exactly,
and the script asserts it): 19 tenders, 18 decks, **79 flags** (76 names, 3 numbers) and 534 fields with no flag.
Each flag was read against its text; the labels are in `audit_labels.csv`.

| Judgment | Count | Share |
|---|---|---|
| Real invention | **2** | 2.5% |
| False alarm | **77** | 97.5% |

False alarms by cause: 64 label words in a short Title Case phrase (phase names such as "Data Prep" and "Model
Build", pillar and need titles); 7 abbreviations of an input phrase; 3 the cited asset id read as a number; 3 a
generic word in the greeting ("Dear Calderon Team,").

**The false-alarm rate is very high, and it makes the bid warnings worse, not better.** Every deck carries about 4 to 5
spurious claim warnings. A what-if, labelled as tuned on the judged decks so it is not a result: dropping label
fields alone would leave 15 flags, 2 of them real.

### Real inventions the check flagged (only 2)

1. `tender-003` `letter.salutation`: "Dear Hiring Committee," names an addressee the tender does not mention.
2. `tender-009` `approach.phases[1].body`: "Train and validate CNNs ..." chooses a technique the tender never mentions.

### Real inventions the check missed (5, found by reading)

The check cannot see lowercase technical terms, overpromises or capability claims.

1. `tender-004` pillar: "Opt-in/out changes reach marketing and other downstream systems **immediately**." The tender says "within one day".
2. `tender-003` pillar: "... three years of workforce data for **strategic** comparison." The tender says "executive view".
3. `heldout-003` `summary.why_us`: "OliveSoft delivers precise construction solutions backed by **seasoned experts** ..." A capability OliveSoft does not have.
4. `heldout-003` letter: "Integrated M&E systems **guarantee** full functionality." (The banned-word check does catch the word "guarantee".)
5. `tender-007` pillar: "... refine future predictions **continuously**." An unsupported promise.

### False alarms (5 of the 77)

1. `tender-009` phase name "Data Prep", flagged as the name "Prep" (64 flags have this shape).
2. `tender-005` "Dear Calderon Team," flagged as the name "Calderon Team"; "Calderon" is in the issuer, "Team" is a generic word.
3. `tender-007` headline "ML Demand Forecasting ...", flagged as the name "ML"; the tender says "machine learning".
4. `tender-011` evidence line "PRJ-0035 offline case handling ...", flagged as the number "0035"; it is the cited asset id.
5. `tender-015` "loyalty ID" flagged as the name "ID"; the tender says "loyalty number".

### Unflagged fields

I read a seeded sample of 40 of the 534. No unsupported number, year, name or status claim among them (three
I was unsure about, I checked against the tender text: all grounded). A second probe, listing every word in the
prose that appears nowhere in the tender's inputs, found the lowercase overclaims above and a lot of generic
vocabulary. So the unflagged fields are clean of the kinds the check looks for, and dirty in a kind it cannot see.
I did not measure the second kind beyond what is quoted here.

## What is still specific to our data

- The corpus: main's 224 chunks, synthetic CVs and projects, OliveSoft internship ideas, all-MiniLM-L6-v2. The
  cutoffs, the delivered rule and the idea rule all depend on it.
- The tenders: 19 short English texts of 500 to 900 characters, written by the team or by me. No real tender, no
  PDF text, no non-English tender has been run.
- OliveSoft: the brand, the offices, the next steps, the signatory, the euro, the file names and field names of
  its data.
- The model: gpt-oss-20b at low effort on Groq, whose length discipline, rate limits and token budget shaped the
  retry count, the margin and the adapter.
- The check: English only, and tuned by design to numbers and names, so it is blind to capability claims.

## What needed your call (all answered; nothing here is still open)

This was the list I gave you with the audit. Each point has since been answered; the outcome is in "After the fixes" at
the top of this file.

1. **Fix order.** Answered: you set the order and I followed it. Clear errors before any LLM call, the validator gate,
   the silent requirement drop and the footer are all fixed ("What each odd input does now", "The validator now blocks").
2. **The claim check on by default.** Answered: it is off by default (the flag is `--claim-check`), and re-judged on fresh decks at
   0 of 11 clear ("The claim check, judged on fresh decks").
3. **Thresholds.** Answered by Task 3: 0.40 holds, 0.55 is no better than 0.45, and the held-out Strong rows go from 0 to 3
   of 24 on the `fix/data-rag` corpus. The cutoffs were left alone, as you said; see `data_rag_check.md`.
4. **Capability overclaims.** Answered: the all-Gap rule now writes a no-bid deck with no model prose ("The no-bid rule on
   the 19 tenders"). Lowercase overclaims in a deck that does bid are still invisible to every check.
5. **The 10 failing tests.** Answered: you chose strict xfail, each mark was removed as its finding was fixed, and none are
   left (198 tests, now 209, all pass).
