"""Ingest-boundary validation: a corrupt record must fail fast and by name.

``rag/ingest_json.py`` wraps every chunker rejection as
``Invalid <doc_type> record '<id>': <reason>`` so an operator can find the
offending row without a stack-trace safari. Validation runs before embeddings
and before the database is touched, so a bad file can never strand a
half-replaced source in Supabase (the guarantee ``replace_source_chunks``
relies on).
"""

import json

import pytest

from rag.ingest_json import ingest_json_file


def test_invalid_cv_record_fails_fast_with_the_record_id(tmp_path):
    path = tmp_path / "bad_cvs.json"
    path.write_text(json.dumps([{"cv_id": "CV-0007"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="CV-0007"):
        ingest_json_file(str(path), "cv")


def test_invalid_project_record_names_the_project_id(tmp_path):
    path = tmp_path / "bad_projects.json"
    path.write_text(
        json.dumps([{"project_id": "PRJ-0007", "summary": "too early to be valid"}]),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="PRJ-0007"):
        ingest_json_file(str(path), "project")


def test_missing_source_file_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        ingest_json_file(str(tmp_path / "nope.json"), "cv")


def test_schema_flags_are_validated_before_reading_the_file(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="olivesoft"):
        ingest_json_file(str(path), "cv", record_schema="olivesoft")
