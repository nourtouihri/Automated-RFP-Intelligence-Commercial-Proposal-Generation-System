"""Mutation check: break one feature at a time in a scratch copy of proposal/ and see if the tests notice.

    python -X utf8 proposal/feasibility/mutation_check.py <repo_root> <work_dir>

Each mutation is an exact-text replacement, so one stops applying ("NOT FOUND") when the code it
targets changes; update the list then. A mutation the tests do not notice "SURVIVED": that
feature can break without any test failing. Results: results/audit.md.
"""

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(sys.argv[1]).resolve()
WORK = Path(sys.argv[2])
WORK.mkdir(exist_ok=True)

# (label, file, exact old text, replacement)
M = [
    ("M01 is_idea always False (F10/F11)", "compose.py", 'return "pfe_internship_project" in (rec.get("relationship"), rec.get("project_kind"))', "return False"),
    ("M02 an explicit status is ignored (F6)", "compose.py", "            return status.strip().lower() in _DONE", "            return True"),
    ("M03 evidence_hit takes the top hit even if an idea (F11)", "compose.py", 'return next((h for h in hits if is_record(h, "cv", "project")), None)', "return hits[0] if hits else None"),
    ("M04 STRONG_AT 0.55 -> 0.30", "schemas.py", "STRONG_AT = 0.55", "STRONG_AT = 0.30"),
    ("M05 PARTIAL_AT 0.40 -> 0.10", "schemas.py", "PARTIAL_AT = 0.40", "PARTIAL_AT = 0.10"),
    ("M06 weak hits no longer written by code (F12)", "compose.py", "        if score[req] < PARTIAL_AT:\n            return RequirementRow(requirement=req, evidence=\"Weak", "        if False:\n            return RequirementRow(requirement=req, evidence=\"Weak"),
    ("M07 citation check disabled", "compose.py", "stray = _stray_citations(out, set(allowed_ids))", "stray = []"),
    ("M08 MAX_ATTEMPTS 3 -> 1", "compose.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 1"),
    ("M09 delivered references no longer first (F10)", "compose.py", "projects = sorted(projects, key=lambda h: not is_delivered(rec(h)))", "projects = list(projects)"),
    ("M10 distinguishing skills no longer first", "compose.py", "skills = [k for k in skills if k not in shared] + [k for k in skills if k in shared]", "skills = skills"),
    ("M11 validate() runs no overflow, table or palette check", "validate.py", "issues = (check_overflow(path) + check_tables(path) + check_palette(path)", "issues = ([]"),
    ("M12 autofit never shrinks text", "measure.py", "        size -= 1", "        break"),
    ("M13 check_evidence reports nothing", "validate.py", "        if ev not in retrieved_ids:", "        if False:"),
    ("M14 adapter does not wait on 429", "llm_adapter.py", '                    rec["waited_s"] += wait\n                    self.sleep(wait)\n', '                    rec["waited_s"] += wait\n'),
    ("M15 adapter never treats a long Retry-After as a quota", "llm_adapter.py", 'if wait > self.max_wait_s or rec["rate_limited"] == self.max_429:', 'if rec["rate_limited"] == self.max_429:'),
    ("M16 'no delivered reference' warning removed", "compose.py", "    elif not any(r.delivered for r in refs):", "    elif False:"),
    ("M17 sentence-boundary cut removed", "compose.py", "    if ends:", "    if False:"),
    ("M18 prompt margin 0.85 -> 1.0", "compose.py", "MARGIN = 0.85", "MARGIN = 1.0"),
    ("M19 the matrix shows the first 7 requirements, not the best 7", "compose.py", "sorted(range(len(order)), key=lambda i: -score[order[i]])[:MATRIX_ROWS]", "list(range(len(order)))[:MATRIX_ROWS]"),
    ("M20 tender text no longer cut at 3000", "compose.py", '(tender.get("raw_text") or "")[:3000]', '(tender.get("raw_text") or "")'),
    ("M21 asset text no longer cut at 500", "compose.py", '(a.get("content") or "")[:500]', '(a.get("content") or "")'),
    ("M22 stale PDF no longer deleted", "export.py", "    pdf.unlink(missing_ok=True)\n", ""),
    ("M23 private soffice profile removed", "export.py", 'f"-env:UserInstallation={profile.as_uri()}", ', ""),
    ("M24 load_records reads only cv_id", "compose.py", 'ID_KEYS = ("cv_id", "project_id", "tool_id", "client_id", "id")', 'ID_KEYS = ("cv_id",)'),
    ("M25 record_id falls back to the chunk id", "compose.py", 'rid = (hit.get("metadata") or {}).get("record_id")', 'rid = hit.get("id")'),
    ("M26 fit_for: Partial returns Strong", "schemas.py", '        return "Partial"', '        return "Strong"'),
    ("M27 render: matrix evidence column swapped for the requirement", "render.py", 'evidence = r.evidence if r.evidence_id else "No matching asset found, flagged for review"', "evidence = r.requirement"),
    ("M28 banned word 'leading' removed", "compose.py", '    "leading": r"' + chr(92) + 'bleading' + chr(92) + 'b",\n', ""),
    ("M29 invalid-JSON instruction dropped", "compose.py", "fix = [INVALID_JSON_FIX]\n            continue\n        except ValueError", "pass\n            continue\n        except ValueError"),
    ("M30 team limited to 1 consultant", "compose.py", "team = _team(cvs[:3], rec) or [_no_consultant()]", "team = _team(cvs[:1], rec) or [_no_consultant()]"),
    ("M31 banned words not checked", "compose.py", "    return out + banned_wording(p) + claims", "    return out + claims"),
    ("M32 font lookup ignores the per-user fonts dir", "measure.py", '        if environ.get("LOCALAPPDATA"):', "        if False:"),
    ("M33 claim check never runs", "compose.py", "        if claim_check:\n", "        if False:\n"),
    ("M34 claim support ignores source records", "claims.py", "                      *sources])", "                      ])"),
    ("M35 similarity range not checked", "compose.py", "    if not 0 <= s <= 1:", "    if False:"),
    ("M36 duplicate records not removed", "compose.py", "        if rid not in seen:", "        if True:"),
    ("M37 all-Gap never gives a no-bid result", "compose.py", "    if not force_bid and all(score[r] < PARTIAL_AT for r in order):", "    if False:"),
    ("M38 the validator does not block", "build.py", "        if issues and not allow_issues:", "        if False:"),
    ("M39 hidden requirements raise no warning", "compose.py", '    gap = sum(r.fit == "Gap" for r in hidden)', "    return []\n    gap = 0"),
    ("M40 a retry is not told which ids it may cite", "compose.py", "            fix = [f\"{path} cites {e}, which is not one of your input assets; {may}\"\n                   for path, e in stray]", "            fix = []"),
    ("M41 no placeholder when no CV matched", "compose.py", "team = _team(cvs[:3], rec) or [_no_consultant()]", "team = _team(cvs[:3], rec)"),
    ("M42 cited ids not removed before the claim check", "claims.py", '            text = text.replace(i, " ")', "            pass"),
    ("M43 the CSV marks every row as shown", "export.py", '"yes" if r.requirement in shown else "no"', '"yes"'),
    ("M44 the footer is not truncated", "render.py", 'left, size=15, color=col, name="footer", truncate=True)', 'left, size=15, color=col, name="footer")'),
    ("M45 an unbroken word is not cut by characters", "measure.py", "    if len(words) == 1:  # one unbroken word", "    if False:  # one unbroken word"),
    ("M46 compose ignores the config's signatory", "compose.py", "signatory=config.signatory,", "signatory=DEFAULT.signatory,"),
    ("M47 negative outcome text still counts as delivered", "compose.py", "and not _NOT_DONE.search(outcome)", ""),
    ("M48 adapter sends max_tokens again", "llm_adapter.py", '"max_completion_tokens": max_completion_tokens,', '"max_tokens": max_completion_tokens,'),
    ("M49 approach title wrong for one phase", "compose.py", "phase{'' if n == 1 else 's'}", "phase{'s'}"),
    ("M50 a hit without record_id is accepted", "compose.py", "    if not rid:\n        raise InputError(", "    if False:\n        raise InputError("),
    ("M51 the last-resort cut uses only the last attempt", "compose.py", "sorted(candidates, key=lambda c: c[:2]):", "sorted(candidates, key=lambda c: c[1])[:1]:"),
    ("M52 the trace does not say which attempt was cut", "compose.py", "trim_attempt=attempt)", "trim_attempt=0)"),
    ("M53 requirement evidence accepts any doc type", "compose.py", 'if is_record(h, "cv", "project")), None)', 'if not is_idea(h.get("metadata") or {})), None)'),
    ("M54 reference cards accept website and client pages", "compose.py", 'projects = [h for h in projects if is_record(h, "project") or', 'projects = [h for h in projects if True or'),
    ("M55 CV slots accept any doc type", "compose.py", 'if is_record(h, "cv")]', ']'),
    ("M56 company pages are not given to the summary", "compose.py", '{"COMPANY_PAGES": [_asset_view(a) for a in pages[:3]]} if pages else {}', '{}'),
    ("M57 company pages may be cited", "compose.py", 'allowed_ids={a["id"] for a in summary_assets}', 'allowed_ids={a["id"] for a in summary_assets + company_pages.get("COMPANY_PAGES", [])}'),
    ("M58 an incomplete tender raises no warning", "compose.py", 'if tender.get("status") != "incomplete":', "if True:"),
    ("M59 unusable research is still shown", "compose.py", "    if problem:\n        research = None", "    if False:\n        research = None"),
    ("M60 input warnings are not reported", "compose.py", "out = list(p.input_warnings)", "out = []"),
    ("M61 the research status is not checked", "compose.py", 'if status not in ("complete", "partial"):', "if False:"),
    ("M62 the buyer slide claims research it did not have", "render.py", "{'our research' if B.researched else 'the tender'}", "{'our research'}"),
    ("M63 the deck does not record that research was missing", "compose.py", "researched=problem is None)", "researched=True)"),
    ("M64 missing research fields raise no warning", "compose.py", "return [f\"research incomplete: {', '.join(missing)}\"] if missing else []", "return []"),
    ("M65 an expired deadline raises no warning", "compose.py", "    if deadline and deadline < date.today():", "    if False:"),
    ("M66 speed promises are not checked", "compose.py", "disclaimed + speed_promises(llm_texts(p), tender)", "disclaimed"),
    ("M67 a disclaiming evidence line is kept", "compose.py", "            if DISCLAIMS.search(line):", "            if False:"),
    ("M68 a word the tender uses is still flagged as a speed promise", "compose.py", '"", re.sub(r"[- ]", "", word)) not in flat:', '"", re.sub(r"[- ]", "", word)) or True:'),
    ("M69 a missing logo file is not reported as missing", "render.py", "        if not path.is_file():\n            raise LogoError", "        if False:\n            raise LogoError"),
    ("M70 the validator does not check logo overlap", "validate.py", "\n              + check_logo_overlap(path))", ")"),
    ("M71 no symbol in the footer", "render.py", '        self.logo(s, self.config.logo_symbol, 1195, 652, 28, "logo-symbol", right=True)', "        pass"),
    ("M72 no lockup on the cover", "render.py", '        self.logo(s, self.config.logo_lockup, 86, 64, 40, "logo-lockup")', "        pass"),
    ("M73 the demo does not check the template before writing", "demo.py", "        render.check_logos(DEFAULT)\n        font_gaps((render.FONT, render.HEAD_FONT))", "        pass"),
    ("M74 missing brand fonts are not reported", "build.py", "for g in font_gaps((font, head_font))]", "for g in font_gaps((font, head_font))][:0]"),
    ("M75 phase2 ingest warnings are dropped", "compose.py", 'return [f"tender ingest warning: {f}"', 'return [] and [f"tender ingest warning: {f}"'),
    ("M76 the matrix note can reach the footer", "render.py", "y = min(190 + height + 18, 630)", "y = 190 + height + 18"),
    ("M77 the CLI does not catch a missing font", "__main__.py", "except (render.LogoError, FontNotFound) as e:", "except (render.LogoError,) as e:"),
]

only = [a for a in sys.argv[3:]]
base = WORK / "base"
if base.exists():
    shutil.rmtree(base)
(base / "detection").mkdir(parents=True)
shutil.copytree(REPO / "proposal", base / "proposal", ignore=shutil.ignore_patterns("__pycache__", "results"))
for n in ("__init__.py", "llm.py"):
    shutil.copy(REPO / "detection" / n, base / "detection" / n)


def run(cwd):
    r = subprocess.run([sys.executable, "-X", "utf8", "-m", "pytest", "proposal/tests", "-q", "-x",
                        "-p", "no:cacheprovider"], cwd=cwd, capture_output=True, text=True)
    last = [line for line in r.stdout.strip().splitlines() if line.strip()][-1]
    failed = [line.split("::")[-1].split(" ")[0] for line in r.stdout.splitlines() if line.startswith("FAILED")]
    return r.returncode, last, failed


rc, last, _ = run(base)
print("baseline:", last, flush=True)
survived, applied = [], 0
for label, fname, old, new in M:
    if only and label[:3] not in only:
        continue
    work = WORK / "run"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(base, work)
    f = work / "proposal" / fname
    text = f.read_text(encoding="utf-8")
    if old not in text:
        print("NOT FOUND:", label, flush=True)
        continue
    f.write_text(text.replace(old, new, 1), encoding="utf-8")
    applied += 1
    rc, last, failed = run(work)
    print(("KILLED  " if rc else "SURVIVED"), label, "|", ",".join(failed)[:70], flush=True)
    if not rc:
        survived.append(label)
print(f"\nsurvived {len(survived)} of {applied} applied", flush=True)
