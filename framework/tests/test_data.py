import pytest

from utilities.data import backend, parse_cdr, query_df


def test_backend_is_bigquery_when_cdr_set():
    assert backend({"WORKSPACE_CDR": "proj.R2025"}) == "bigquery"


def test_backend_is_duckdb_locally():
    assert backend({}) == "duckdb"
    assert backend({"WORKSPACE_CDR": ""}) == "duckdb"


def test_parse_cdr_splits_project_and_dataset():
    assert parse_cdr("wb-affable-acorn-7941.R2025Q4R6") == ("wb-affable-acorn-7941", "R2025Q4R6")


def test_parse_cdr_rejects_malformed():
    with pytest.raises(ValueError):
        parse_cdr("no-dataset")


def test_query_df_runs_on_duckdb(tmp_path):
    duckdb = pytest.importorskip("duckdb")
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE person AS SELECT * FROM (VALUES (1, 1950), (2, 1960)) t(person_id, year_of_birth)")
    con.close()
    df = query_df("SELECT COUNT(*) AS n FROM person", env={}, duckdb_path=str(db))
    assert int(df["n"].iloc[0]) == 2
