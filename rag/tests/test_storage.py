from types import SimpleNamespace

import pytest

from rag.storage import (
    StatsError,
    build_rows,
    count_records,
    make_chunk_id,
    make_source_id,
    replace_source_chunks,
)


class FakeTable:
    def __init__(self, existing=None, fail_upsert=False):
        self.existing = existing or []
        self.fail_upsert = fail_upsert
        self.action = None
        self.upserts = []
        self.deletes = []

    def select(self, _columns):
        self.action = "select"
        return self

    def eq(self, _column, _value):
        return self

    def upsert(self, rows, on_conflict):
        if self.fail_upsert:
            raise RuntimeError("database unavailable")
        self.action = "upsert"
        self.upserts.extend(rows)
        assert on_conflict == "id"
        return self

    def delete(self):
        self.action = "delete"
        return self

    def in_(self, _column, values):
        self.deletes.extend(values)
        return self

    def execute(self):
        if self.action == "select":
            return SimpleNamespace(data=[{"id": value} for value in self.existing])
        return SimpleNamespace(data=[])


class FakeClient:
    def __init__(self, table):
        self.fake_table = table

    def table(self, name):
        assert name == "knowledge_chunks"
        return self.fake_table


def make_rows():
    return build_rows(
        [{"content": "first", "metadata": {"record_id": "CV-1"}}],
        [[0.0] * 384],
        doc_type="cv",
        source_id="cv:data/cvs.json",
        source_file="cvs.json",
    )


def test_chunk_ids_are_deterministic():
    assert make_chunk_id("source", 1) == make_chunk_id("source", 1)
    assert make_chunk_id("source", 1) != make_chunk_id("source", 2)


def test_source_id_can_be_explicit(tmp_path):
    assert make_source_id(tmp_path / "x.json", "cv", "internal/cvs") == "cv:internal/cvs"


def test_replace_upserts_before_deleting_stale_rows():
    rows = make_rows()
    table = FakeTable(existing=["old-id"])
    replace_source_chunks(rows, source_id=rows[0]["source_id"], client=FakeClient(table))
    assert len(table.upserts) == 1
    assert table.deletes == ["old-id"]


def test_failed_upsert_never_deletes_old_rows():
    rows = make_rows()
    table = FakeTable(existing=["old-id"], fail_upsert=True)
    with pytest.raises(RuntimeError, match="unavailable"):
        replace_source_chunks(rows, source_id=rows[0]["source_id"], client=FakeClient(table))
    assert table.deletes == []


def test_build_rows_rejects_wrong_vector_size():
    with pytest.raises(ValueError, match="dimensions"):
        build_rows(
            [{"content": "first"}],
            [[0.0] * 10],
            doc_type="cv",
            source_id="cv:data/cvs.json",
            source_file="cvs.json",
        )


class PageQuery:
    def __init__(self, rows):
        self.rows = rows
        self.filters = []
        self.columns = None
        self.ordered_by = None
        self.window = None

    def select(self, columns):
        self.columns = columns
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def order(self, column):
        self.ordered_by = column
        return self

    def range(self, start, end):
        self.window = (start, end)
        return self

    def execute(self):
        doc_type = dict(self.filters)["doc_type"]
        start, end = self.window
        return SimpleNamespace(data=self.rows[doc_type][start : end + 1])


class PageClient:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def table(self, name):
        assert name == "knowledge_chunks"
        query = PageQuery(self.rows)
        self.queries.append(query)
        return query


def rows_by_type(**by_type):
    return {"cv": [], "project": [], "tool": [], **by_type}


def test_counts_distinct_records_per_type():
    rows = rows_by_type(
        cv=[{"record_id": f"cv-{n}", "source_id": "cv:data/cvs.json"} for n in range(3)],
        project=[{"record_id": "p-1", "source_id": "project:data/p.json"}],
    )
    assert count_records(PageClient(rows)) == {"cv": 3, "project": 1, "tool": 0}


def test_two_chunks_of_one_record_count_once():
    rows = rows_by_type(
        project=[
            {"record_id": "p-1", "source_id": "project:data/p.json"},
            {"record_id": "p-1", "source_id": "project:data/p.json"},
            {"record_id": "p-2", "source_id": "project:data/p.json"},
        ]
    )
    assert count_records(PageClient(rows))["project"] == 2


def test_rows_without_record_id_count_once_per_source():
    rows = rows_by_type(
        tool=[
            {"record_id": None, "source_id": "tool:data/a.md"},
            {"record_id": None, "source_id": "tool:data/a.md"},
            {"source_id": "tool:data/b.md"},
            {"record_id": "t-1", "source_id": "tool:data/c.json"},
        ]
    )
    assert count_records(PageClient(rows))["tool"] == 3


def test_pages_through_every_row(monkeypatch):
    monkeypatch.setattr("rag.storage.COUNT_PAGE_SIZE", 2)
    rows = rows_by_type(
        cv=[{"record_id": f"cv-{n}", "source_id": "cv:x"} for n in range(5)]
    )
    client = PageClient(rows)
    assert count_records(client)["cv"] == 5
    cv_queries = [q for q in client.queries if ("doc_type", "cv") in q.filters]
    assert [q.window for q in cv_queries] == [(0, 1), (2, 3), (4, 5)]
    assert all(q.ordered_by == "id" for q in client.queries)
    assert all(q.columns == "metadata->>record_id,source_id" for q in client.queries)


def test_an_exact_multiple_of_the_page_size_ends_on_an_empty_page(monkeypatch):
    monkeypatch.setattr("rag.storage.COUNT_PAGE_SIZE", 2)
    rows = rows_by_type(
        cv=[{"record_id": f"cv-{n}", "source_id": "cv:x"} for n in range(4)]
    )
    assert count_records(PageClient(rows))["cv"] == 4


@pytest.mark.parametrize("bad", [None, "rows", [1, 2], [{"record_id": "a"}, "x"]])
def test_count_rejects_a_malformed_response(bad):
    class Bad:
        def table(self, _name):
            return self

        def select(self, *_a, **_k):
            return self

        def eq(self, *_a):
            return self

        def order(self, *_a):
            return self

        def range(self, *_a):
            return self

        def execute(self):
            return SimpleNamespace(data=bad)

    with pytest.raises(StatsError, match="invalid response"):
        count_records(Bad())


def test_count_wraps_a_failing_database_call():
    class Down:
        def table(self, _name):
            raise RuntimeError("connection refused")

    with pytest.raises(StatsError, match="failed"):
        count_records(Down())
