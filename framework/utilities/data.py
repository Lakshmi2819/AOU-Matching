"""Run SQL against the active data backend and return a pandas DataFrame.

Python counterpart of pick_connection() in framework/shared/utilities.R:
  - in AoU (WORKSPACE_CDR set): BigQuery over the CDR, with the CDR dataset as
    the default dataset so unqualified table names resolve
  - locally: DuckDB over the Eunomia fixture (data/eunomia.duckdb)
Backend libraries are imported lazily so the core install stays light.
The returned frame is row-level: keep it in memory, print only aggregates.
"""
from __future__ import annotations

import os
from typing import Mapping


def backend(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return "bigquery" if env.get("WORKSPACE_CDR") else "duckdb"


def parse_cdr(cdr: str) -> tuple[str, str]:
    """Split WORKSPACE_CDR ('project.dataset') into its two parts."""
    project, sep, dataset = cdr.partition(".")
    if not (project and sep and dataset):
        raise ValueError(f"WORKSPACE_CDR must look like 'project.dataset', got {cdr!r}")
    return project, dataset


def query_df(sql: str, env: Mapping[str, str] | None = None,
             duckdb_path: str = "data/eunomia.duckdb"):
    env = os.environ if env is None else env
    if backend(env) == "bigquery":
        from google.cloud import bigquery

        project, dataset = parse_cdr(env["WORKSPACE_CDR"])
        client = bigquery.Client(project=env.get("GOOGLE_CLOUD_PROJECT") or None)
        job_config = bigquery.QueryJobConfig(default_dataset=f"{project}.{dataset}")
        return client.query(sql, job_config=job_config).to_dataframe()

    import duckdb

    con = duckdb.connect(duckdb_path, read_only=True)
    try:
        return con.execute(sql).df()
    finally:
        con.close()
