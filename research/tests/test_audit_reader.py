from research.audit import AuditLogger
from research.audit_reader import read_run


def write_log(tmp_path, calls, name="research.log"):
    """calls: (run_id, tool, params, content). Written by the real AuditLogger."""
    path = tmp_path / name
    audit = AuditLogger(log_path=str(path))
    for run_id, tool, params, content in calls:
        audit.run_id = run_id
        audit.log(tool, params, content)
    for handler in audit.logger.handlers:
        handler.close()
    audit.logger.handlers.clear()
    return path


def start(tender_id, run_id):
    return (run_id, "research_run_start", {"tender_id": tender_id, "issuer": "X"}, "")


def search(run_id, content="page", query="q"):
    return (run_id, "search", {"query": query}, content)


def test_reads_the_latest_run_for_a_tender(tmp_path):
    log = write_log(tmp_path, [start("t1", "run_a"), search("run_a"), start("t1", "run_b"), search("run_b")])
    entries = read_run(log, "t1")
    assert {e["params"]["run_id"] for e in entries} == {"run_b"}
    assert [e["tool"] for e in entries] == ["research_run_start", "search"]


def test_pipes_in_content_survive(tmp_path):
    log = write_log(tmp_path, [start("t1", "r"), search("r", content="a | b | c")])
    assert read_run(log, "t1")[-1]["content"] == "a | b | c"


def test_pipes_in_params_survive(tmp_path):
    log = write_log(tmp_path, [start("t1", "r"), search("r", content="x | y", query="a | b")])
    entry = read_run(log, "t1")[-1]
    assert entry["params"]["query"] == "a | b"
    assert entry["content"] == "x | y"


def test_unknown_tender_has_no_run(tmp_path):
    assert read_run(write_log(tmp_path, []), "t9") == []


def test_missing_log_has_no_run(tmp_path):
    assert read_run(tmp_path / "absent.log", "t1") == []


def test_other_tenders_and_interleaved_runs_are_excluded(tmp_path):
    log = write_log(
        tmp_path,
        [start("t1", "a"), start("t2", "b"), search("a", "for t1"), search("b", "for t2")],
    )
    assert [e["content"] for e in read_run(log, "t1")] == ["", "for t1"]


def test_content_is_cut_and_limit_applies(tmp_path):
    log = write_log(tmp_path, [start("t1", "r"), search("r", "z" * 900), search("r"), search("r")])
    entries = read_run(log, "t1", limit=2)
    assert len(entries) == 2
    assert len(entries[1]["content"]) == 300


def test_malformed_lines_are_skipped(tmp_path):
    log = write_log(tmp_path, [start("t1", "r"), search("r", "ok")])
    with open(log, "a", encoding="utf-8") as f:
        f.write("garbage\n")
        f.write("2026-01-01T00:00:00+00:00 | INFO | search | {not json} | " + "a" * 64 + " | x\n")
    assert [e["content"] for e in read_run(log, "t1")] == ["", "ok"]


def test_run_found_in_a_rotated_file_continues_into_the_current_one(tmp_path):
    write_log(tmp_path, [start("t1", "r"), search("r", "before midnight")], name="research.log.2026-01-01")
    log = write_log(tmp_path, [search("r", "after midnight")])
    assert [e["content"] for e in read_run(log, "t1")] == ["", "before midnight", "after midnight"]


def test_newest_run_wins_across_files(tmp_path):
    write_log(tmp_path, [start("t1", "old"), search("old")], name="research.log.2026-01-01")
    log = write_log(tmp_path, [start("t1", "new")])
    assert {e["params"]["run_id"] for e in read_run(log, "t1")} == {"new"}


def test_a_cache_hit_after_a_real_run_leaves_the_real_run_latest(tmp_path):
    log = write_log(
        tmp_path,
        [start("t1", "real"), search("real", "page"), ("hit", "fetch_cache", {"tender_id": "t1", "issuer": "X"}, "")],
    )
    assert {e["params"]["run_id"] for e in read_run(log, "t1")} == {"real"}
