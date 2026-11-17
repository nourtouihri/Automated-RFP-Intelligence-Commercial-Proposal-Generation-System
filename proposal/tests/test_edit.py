"""The prompt-edit feature end to end, with the LLM faked:

- edit_agent.WholeSpec / EDITABLE: the spec table agrees with schemas.py,
  slide value by slide value;
- edit_agent.EditAgent: fail-closed reply handling (bad JSON, a missing or
  foreign key, a reshaped list, a blank string, an invalid value) exactly
  like research.extractor's discipline; the whole-value contract;
- edit_runner.edit_proposal: spec resolution, the whole-value application,
  the owned-field restore, the evidence guard, the saved deck and the
  no-change path;
- shared.store.save_proposal: an update keeps warnings, artifacts and
  review_status the caller did not pass.

The store runs against a temp sqlite file per test, never the developer's
shared/sqlite.db.
"""

import json
from typing import Any

import pytest
from pydantic import ValidationError

import proposal.edit_agent as ea
from proposal.compose import InputError
from proposal.edit_agent import rules
from proposal.edit_runner import OWNED, edit_proposal
from proposal.schemas import (Approach, BuyerProfile, BuyerUnderstanding,
                              Consultant, CoverLetter, EditProposalRequest,
                              ExecutiveSummary, Investment, Meta, Need, NoBid,
                              Phase, Pillar, PriceLine, NextStep, Proposal,
                              Reference, RequirementRow, Signatory)
from shared import store
from shared.errors import ApiError

TID = "tender-edit-1"


def _deck() -> Proposal:
    return Proposal(
        meta=Meta(buyer="AquaWorks", tender_title="Data platform upgrade",
                  reference="R-1", date="2026-10-27",
                  headline="A data platform that holds",
                  subtitle="Design, build and operate in agreed phases"),
        signatory=Signatory(name="OliveSoft Sales Team", role="Sales, OliveSoft",
                            contact="olivesoft.fr"),
        letter=CoverLetter(salutation="Dear AquaWorks team,",
                           paragraphs=["We will deliver the platform in agreed phases."],
                           closing="We look forward to the discovery session.",
                           title="A partner for your data journey"),
        summary=ExecutiveSummary(title="A data platform that holds", pillars=[
            Pillar(title="Delivery", body="Phased build with a release at each gate.",
                   evidence=["PROJECT-1"]),
            Pillar(title="Operations", body="Run on your stacks, not ours."),
            Pillar(title="Compliance", body="Controls mapped to your audit needs."),
        ], why_us="Local senior engineers on every phase."),
        buyer=BuyerUnderstanding(profile=BuyerProfile(), needs=[
            Need(title="One platform", body="Retire the fragmented pipelines.")]),
        requirements=[RequirementRow(requirement="Data platform upgrade",
                                     evidence="Migration scripts", score=0.6,
                                     evidence_id="PROJECT-1")],
        approach=Approach(title="Three phases, a release at each", phases=[
            Phase(name="Build", weeks=2, body="Core pipelines."),
            Phase(name="Run", weeks=1, body="Handover with the team."),
        ], milestones="Kickoff week 1, go-live week 3."),
        team=[Consultant(cv_id="CV-1", name="A. Professional", role="Lead engineer",
                         years=7, skills="Postgres, Kafka", score=0.9)],
        references=[Reference(project_id="PROJECT-1", title="Utility data hub",
                              summary="A data hub for one utility.", sector="Water",
                              score=0.8, delivered=True)],
        investment=Investment(currency="EUR",
                              lines=[PriceLine(workstream="Build + Run", days=15,
                                               amount=9750)],
                              note="Indicative", next_steps=[
                                  NextStep(title="Discovery session",
                                           detail="30 minutes, this week")]),
    )


@pytest.fixture()
def fresh_store(tmp_path, monkeypatch):
    """A private sqlite file and a booted schema, reused as `store`."""
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "db.sqlite")
    store.init_db()
    return store


class FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def __call__(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.reply


class FakeAgent:
    """Patched in where the runner builds EditAgent(_llm()): it captures what
    the runner asked and answers with a fixed whole slide value (or None)."""

    def __init__(self, result: Any = None):
        self.result = result
        self.calls: list[tuple[Any, Any, str]] = []

    def edit(self, spec, current, prompt):
        self.calls.append((spec, current, prompt))
        return self.result


@pytest.fixture()
def fake_agent(monkeypatch):
    """Factory: fake_agent(FakeAgent(...)) and _llm() is never consulted."""
    def install(agent: FakeAgent) -> FakeAgent:
        monkeypatch.setattr(ea, "EditAgent", lambda llm: agent)
        monkeypatch.setattr(ea, "_llm", lambda: None)
        return agent
    return install


def _current(slide: int) -> Any:
    """The stored slide value, as the runner would hand it over."""
    return _deck().model_dump()[ea.EDITABLE[slide].attr]


def _rewritten(slide: int, **changes: Any) -> Any:
    """A whole-value reply for `slide` with just the given keys changed."""
    value = _current(slide)
    for key, v in changes.items():
        assert key in value, f"slide {slide} holds no key {key}"
        value[key] = v
    return value


# --- the spec table matches the schema --------------------------------------

def test_editable_specs_match_the_schema():
    deck = _deck()
    models = {1: Meta, 2: CoverLetter, 3: ExecutiveSummary, 6: Approach,
              7: Consultant, 8: Reference, 9: Investment}
    for n, spec in ea.EDITABLE.items():
        assert spec.n == n and spec.model is models[n]
        assert spec.attr in deck.model_dump(), f"slide {n}: attr off-deck"
    assert set(ea.EDITABLE) == {1, 2, 3, 6, 7, 8, 9}


def test_optionality_matches_the_schema():
    assert set(OWNED) == {1, 7, 8}
    assert set(OWNED[1]) <= set(Meta.model_fields)
    assert set(OWNED[7]) <= set(Consultant.model_fields)
    assert set(OWNED[8]) <= set(Reference.model_fields)
    # slides 4 and 5 (buyer profile, verification matrix) stay code-owned
    assert 4 not in ea.EDITABLE and 5 not in ea.EDITABLE


def test_rules_prompt_carries_the_company_words_and_bans():
    text = " ".join(rules("Cover").split())  # the prompt wraps prose freely
    assert "OliveSoft" in text and "world-class" in text
    assert "same shape as CURRENT (same keys, same list lengths)" in text
    assert "JSON null" in text


# --- EditAgent reply handling ------------------------------------------------

def test_agent_returns_the_whole_slide_value():
    current = _current(1)
    reply = {**current, "headline": "Said plainly"}
    out = ea.EditAgent(FakeLLM(json.dumps(reply))).edit(
        ea.EDITABLE[1], current, "say it plainly")
    assert out == reply
    assert out["buyer"] == current["buyer"]  # untouched keys ride along


def test_agent_context_carries_the_whole_value():
    current = _current(6)
    llm = FakeLLM("null")
    ea.EditAgent(llm).edit(ea.EDITABLE[6], current, "x")
    system, user = llm.calls[0]
    assert "OliveSoft" in system and "Approach and timeline" in system
    assert "CURRENT" in user and "phases" in user
    assert "EDIT = x" in user


def test_agent_braces_and_brackets_in_prose_reply_still_parse():
    current = _current(1)
    reply = json.dumps({**current, "headline": "ok {brace} "})
    # schemas strips string edges, so the trailing space rounds to the brace
    out = ea.EditAgent(FakeLLM(f'```json\n{reply}\n```')).edit(
        ea.EDITABLE[1], current, "x")
    assert out["headline"] == "ok {brace}"
    # a list slide unwraps from brackets too
    team_current = _current(7)
    team_reply = json.dumps([dict(team_current[0], role="Technical lead")])
    out = ea.EditAgent(FakeLLM(f"sure!\n{team_reply}")).edit(
        ea.EDITABLE[7], team_current, "x")
    assert out == [dict(team_current[0], role="Technical lead")]


def test_agent_null_reply_means_no_change():
    assert ea.EditAgent(FakeLLM("null")).edit(
        ea.EDITABLE[1], _current(1), "leave it") is None


def test_agent_echo_of_the_current_value_means_no_change():
    assert ea.EditAgent(FakeLLM(json.dumps(_current(1)))).edit(
        ea.EDITABLE[1], _current(1), "x") is None


def test_agent_fails_closed_on_missing_and_foreign_keys():
    # a missing key would make the runner's replace dangle; a foreign key is
    # a slide the prompt must not touch (Strict models forbid extras)
    current = _current(1)
    missing = {k: v for k, v in current.items() if k != "subtitle"}
    foreign = {**current, "score": 0.9}
    for reply in (missing, foreign):
        assert ea.EditAgent(FakeLLM(json.dumps(reply))).edit(
            ea.EDITABLE[1], current, "x") is None


def test_agent_fails_closed_on_bad_json_and_invalid_value():
    current = _current(6)
    assert ea.EditAgent(FakeLLM("not json")).edit(
        ea.EDITABLE[6], current, "x") is None
    bad_weeks = dict(current, phases=[
        dict(current["phases"][0], weeks=True),
        *current["phases"][1:]])
    assert ea.EditAgent(FakeLLM(json.dumps(bad_weeks))).edit(
        ea.EDITABLE[6], current, "x") is None


def test_agent_fails_closed_on_list_resizing():
    current = _current(6)
    grown = dict(current, phases=current["phases"] + [dict(current["phases"][0])])
    shrunk = dict(current, phases=current["phases"][:1])
    for reply in (grown, shrunk):
        assert ea.EditAgent(FakeLLM(json.dumps(reply))).edit(
            ea.EDITABLE[6], current, "x") is None


def test_agent_fails_closed_on_blank_strings():
    current = _current(1)
    assert ea.EditAgent(FakeLLM(json.dumps(
        {**current, "headline": "   "}))).edit(
        ea.EDITABLE[1], current, "x") is None


# --- edit_proposal -----------------------------------------------------------

def test_edit_replaces_the_whole_meta_and_stamps_the_row(fresh_store, fake_agent):
    fresh_store.save_proposal(TID, _deck())
    reply = _rewritten(1, headline="New headline")
    agent = fake_agent(FakeAgent(reply))

    res = edit_proposal(TID, EditProposalRequest(slide=1, prompt="new headline"))

    spec, current, _prompt = agent.calls[0]
    assert spec.label == "Cover"
    assert current == _current(1)
    assert res.changed is True and res.updated == reply
    saved = fresh_store.get_proposal_by_tender_id(TID)
    assert saved.meta.headline == "New headline"
    assert saved.updated_at is not None


def test_edit_letter_paragraphs_without_an_index(fresh_store, fake_agent):
    fresh_store.save_proposal(TID, _deck())
    reply = _rewritten(
        2, paragraphs=["We will start with a discovery session."])
    fake_agent(FakeAgent(reply))

    res = edit_proposal(TID, EditProposalRequest(
        slide=2, prompt="start with discovery"))
    assert res.changed is True
    saved = fresh_store.get_proposal_by_tender_id(TID)
    assert saved.letter.paragraphs == ["We will start with a discovery session."]
    assert saved.letter.salutation == _current(2)["salutation"]


def test_edit_targets_every_list_item_it_needs(fresh_store, fake_agent):
    fresh_store.save_proposal(TID, _deck())
    phases = _current(6)["phases"]
    reply = _rewritten(6, phases=[
        dict(phases[0], body="Shorter core build."),
        dict(phases[1], body="Longer handover drill."),
    ])
    fake_agent(FakeAgent(reply))

    edit_proposal(TID, EditProposalRequest(slide=6, prompt="rebalance"))
    saved = fresh_store.get_proposal_by_tender_id(TID)
    assert [p.body for p in saved.approach.phases] == \
        ["Shorter core build.", "Longer handover drill."]


def test_no_change_leaves_the_row_untouched(fresh_store, fake_agent):
    fresh_store.save_proposal(TID, _deck())
    fake_agent(FakeAgent(None))

    res = edit_proposal(TID, EditProposalRequest(slide=1, prompt="no rewrite"))
    assert res.changed is False and res.updated is None

    with fresh_store._connect() as conn:
        row = conn.execute("SELECT * FROM proposals WHERE tender_id=?",
                           (TID,)).fetchone()
    assert row is not None  # the deck is still served, but no edit landed


def test_review_status_and_reviewables_survive_an_edit(fresh_store, fake_agent):
    fresh_store.save_proposal(TID, _deck(), warnings=["speed promise"],
                              artifacts={"pptx": "t.pptx"},
                              review_status="accepted")
    fake_agent(FakeAgent(_rewritten(1, headline="New headline")))

    edit_proposal(TID, EditProposalRequest(slide=1, prompt="head again"))

    saved = fresh_store.get_proposal_by_tender_id(TID)
    assert saved.review_status == "accepted"
    assert saved.meta.headline == "New headline"
    with fresh_store._connect() as conn:
        row = conn.execute("SELECT warnings, artifacts FROM proposals "
                           "WHERE tender_id=?", (TID,)).fetchone()
    assert json.loads(row["warnings"]) == ["speed promise"]
    assert json.loads(row["artifacts"]) == {"pptx": "t.pptx"}


def test_owned_card_fields_are_restored_despite_the_reply(fresh_store, fake_agent):
    fresh_store.save_proposal(TID, _deck())
    meta = dict(_current(1), tender_title="Fake title", reference="R-9",
                date="1999-01-01", sample=True, headline="New headline")
    team = [dict(_current(7)[0], cv_id="CV-9")]
    refs = [dict(_current(8)[0], delivered=False)]
    fake_agent(FakeAgent(meta))
    edit_proposal(TID, EditProposalRequest(slide=1, prompt="new headline"))
    saved = fresh_store.get_proposal_by_tender_id(TID)
    assert saved.meta.tender_title == "Data platform upgrade"
    assert saved.meta.reference == "R-1" and saved.meta.date == "2026-10-27"
    assert saved.meta.sample is False
    assert saved.meta.headline == "New headline"  # the prose edit did land

    fake_agent(FakeAgent(team))
    edit_proposal(TID, EditProposalRequest(slide=7, prompt="rename"))
    saved = fresh_store.get_proposal_by_tender_id(TID)
    assert saved.team[0].cv_id == "CV-1"  # restored, the agent's echo ignored
    assert saved.team[0].score == 0.9

    fake_agent(FakeAgent(refs))
    edit_proposal(TID, EditProposalRequest(slide=8, prompt="doubt it"))
    saved = fresh_store.get_proposal_by_tender_id(TID)
    assert saved.references[0].delivered is True
    assert saved.references[0].project_id == "PROJECT-1"

    # the prose fields themselves did land
    assert saved.team[0].name == _current(7)[0]["name"]
    assert saved.references[0].title == _current(8)[0]["title"]


def test_owned_fields_survive_a_consultant_prose_rewrite(fresh_store, fake_agent):
    fresh_store.save_proposal(TID, _deck())
    reply = [dict(_current(7)[0], role="Principal engineer", years=9)]
    fake_agent(FakeAgent(reply))

    edit_proposal(TID, EditProposalRequest(slide=7, prompt="bump the role"))
    saved = fresh_store.get_proposal_by_tender_id(TID)
    assert saved.team[0].role == "Principal engineer" and saved.team[0].years == 9
    assert saved.team[0].cv_id == "CV-1" and saved.team[0].score == 0.9


def test_pillar_citation_to_an_unknown_id_is_refused(fresh_store, fake_agent):
    fresh_store.save_proposal(TID, _deck())
    pillars = _current(3)["pillars"]
    reply = _rewritten(3, pillars=[
        dict(pillars[0], evidence=["PROJECT-9"]), *pillars[1:]])
    fake_agent(FakeAgent(reply))

    with pytest.raises(ApiError) as e:
        edit_proposal(TID, EditProposalRequest(slide=3, prompt="cite it"))
    assert e.value.status_code == 400 and "PROJECT-9" in str(e.value)
    # nothing landed
    saved = fresh_store.get_proposal_by_tender_id(TID)
    assert saved.summary.pillars[0].evidence == ["PROJECT-1"]


def test_code_owned_slides_and_no_bid_decks_are_refused(fresh_store, fake_agent):
    fresh_store.save_proposal(TID, _deck())
    with pytest.raises(InputError):
        edit_proposal(TID, EditProposalRequest(slide=5, prompt="raise the score"))
    with pytest.raises(InputError):
        edit_proposal(TID, EditProposalRequest(slide=4, prompt="rewrite the buyer"))

    fresh_store.save_proposal(
        TID, NoBid(meta=_deck().meta, requirements=_deck().requirements,
                   warnings=["no requirement reached Partial"],
                   recommendation="No bid"))
    fake_agent(FakeAgent(_rewritten(1, headline="Bid anyway")))
    with pytest.raises(InputError):
        edit_proposal(TID, EditProposalRequest(slide=1, prompt="bid"))


def test_the_request_schema_has_no_index():
    with pytest.raises(ValidationError):
        EditProposalRequest(slide=1, index=0, prompt="x")


def test_unknown_tender_gives_the_store_404(fresh_store, fake_agent):
    fake_agent(FakeAgent(_rewritten(1, headline="x")))
    with pytest.raises(ApiError) as e:
        edit_proposal("missing-tender",
                      EditProposalRequest(slide=1, prompt="x"))
    assert e.value.status_code == 404


def test_save_proposal_update_keeps_what_was_not_passed(fresh_store):
    fresh_store.save_proposal(TID, _deck(), warnings=["w"], artifacts={"pdf": None},
                              review_status="accepted")
    fresh_store.save_proposal(TID, _deck())  # the generate path's bare re-save
    with fresh_store._connect() as conn:
        row = conn.execute("SELECT review_status, warnings, artifacts, "
                           "created_at, updated_at FROM proposals "
                           "WHERE tender_id=?", (TID,)).fetchone()
    assert row["review_status"] == "accepted"
    assert json.loads(row["warnings"]) == ["w"]
    assert json.loads(row["artifacts"]) == {"pdf": None}
    assert row["created_at"] is not None
    # a real re-clean can still clear them explicitly
    fresh_store.save_proposal(TID, _deck(), warnings=[], artifacts={})
    with fresh_store._connect() as conn:
        row = conn.execute("SELECT warnings, artifacts FROM proposals "
                           "WHERE tender_id=?", (TID,)).fetchone()
    assert json.loads(row["warnings"]) == [] and json.loads(row["artifacts"]) == {}


def test_list_proposals_reports_the_row_identity(fresh_store):
    fresh_store.save_proposal(TID, _deck(), review_status="accepted")
    deck = _deck()
    fresh_store.save_proposal(
        "tender-no-bid", NoBid(meta=deck.meta, requirements=deck.requirements,
                               warnings=["no requirement reached Partial"],
                               recommendation="No bid"))

    rows = fresh_store.list_proposal_entries()
    assert [r["tender_id"] for r in rows] == ["tender-no-bid", TID]  # newest first
    by_id = {r["tender_id"]: r for r in rows}
    assert by_id[TID]["kind"] == "proposal"
    assert by_id[TID]["review_status"] == "accepted"
    assert isinstance(by_id[TID]["deck"], Proposal)
    assert by_id["tender-no-bid"]["kind"] == "no_bid"
    assert isinstance(by_id["tender-no-bid"]["deck"], NoBid)
    # hydrating is lossless: the entry deck equals the saved one
    assert by_id[TID]["deck"].model_dump() == fresh_store.get_proposal_by_tender_id(TID).model_dump()
