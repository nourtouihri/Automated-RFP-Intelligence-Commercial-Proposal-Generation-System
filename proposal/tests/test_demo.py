"""proposal.demo: a recorded run replayed with no key and no network, or run live."""

import json

import pytest

from proposal import demo, export
from proposal.schemas import NoBid, Proposal
from proposal.tests.test_compose import CVS, PRJ, RECORDS, REPLIES, REQ, TENDER


def recording(replies=None):
    steps = ["brief", "letter", "summary", "needs", "evidence", "approach"]
    return {"source": {"run": "test", "model": "m", "kind": "proposal"}, "tender": TENDER,
            "requirement_matches": REQ, "cv_matches": CVS, "project_matches": PRJ,
            "records": RECORDS,
            "replies": replies if replies is not None else
            [{"step": s, "reply": json.dumps(REPLIES[s])} for s in steps]}


@pytest.fixture
def recordings(tmp_path, monkeypatch):
    folder = tmp_path / "recordings"
    folder.mkdir()
    (folder / "tender-001.json").write_text(json.dumps(recording()), encoding="utf-8")
    monkeypatch.setattr(demo, "RECORDINGS", folder)
    monkeypatch.setattr(demo, "_load_dotenv", lambda: None)  # never read the real .env in tests
    return folder


@pytest.fixture
def no_pdf(monkeypatch):
    def missing():
        raise FileNotFoundError("LibreOffice not found; set SOFFICE_PATH")
    monkeypatch.setattr(export, "soffice_path", missing)


def test_a_replay_calls_no_model_and_reproduces_the_recorded_deck():
    deck, trace = demo.compose_recording(recording())
    assert isinstance(deck, Proposal) and deck.requirements[0].evidence_id == "PRJ-0003"
    assert [s["step"] for s in trace.steps] == ["brief", "letter", "summary", "needs", "evidence",
                                                "approach"]


def test_a_replay_that_runs_out_of_replies_says_which_step():
    with pytest.raises(demo.ReplayExhausted, match="'needs'"):
        demo.compose_recording(recording(recording()["replies"][:3]))


def test_the_demo_writes_the_deck_and_matrix_and_prints_the_warnings(recordings, no_pdf, tmp_path,
                                                                     capsys):
    out = tmp_path / "out"
    assert demo.main(["tender-001", "--replay", "--out", str(out)]) == 0
    assert (out / "tender-001.pptx").is_file() and (out / "tender-001.matrix.csv").is_file()
    printed = capsys.readouterr().out
    assert "replay" in printed and "research unavailable (no research result)" in printed
    assert "PDF skipped" in printed


def test_without_a_key_the_demo_replays(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert demo.mode(live=False, replay=False) == "replay"


def test_with_a_key_the_demo_runs_live_unless_told_to_replay(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-test")
    assert demo.mode(live=False, replay=False) == "live"
    assert demo.mode(live=False, replay=True) == "replay"


def test_live_without_a_key_is_refused(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="LLM_API_KEY"):
        demo.mode(live=True, replay=False)


def test_an_unknown_tender_is_refused(recordings):
    with pytest.raises(SystemExit, match="tender-999"):
        demo.main(["tender-999", "--replay"])


@pytest.mark.parametrize("tid,kind", [("tender-001", Proposal), ("heldout-001", Proposal),
                                      ("tender-014", NoBid)])
def test_the_bundled_recordings_replay(tid, kind):
    deck, _ = demo.compose_recording(demo.load(tid))
    assert isinstance(deck, kind)
