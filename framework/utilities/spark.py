"""Spark session setup that works both locally and on the AoU Dataproc cluster.

Locally, pyspark from pip starts an in-process local[*] cluster. On Dataproc,
the cluster's spark-defaults pick the master (YARN), so the same call works.
Pure-Python packages that run inside executors (e.g. brpmatch's applyInPandas
functions) must also be shipped to the workers: ship_package() zips the
package and registers it with addPyFile.
"""
from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path
from typing import Iterable, Mapping

from utilities.data import backend, parse_cdr


def get_spark(app_name: str):
    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder.appName(app_name)
        .config("spark.sql.execution.arrow.pyspark.enabled", "true")
        # Stage progress bars would otherwise land in the scrubbed summary.md.
        .config("spark.ui.showConsoleProgress", "false")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")
    return spark


def zip_package(module, dest_dir: Path) -> Path:
    """Zip an imported package so `import <name>` works from the archive."""
    pkg_dir = Path(module.__file__).resolve().parent
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{module.__name__}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(pkg_dir.rglob("*.py")):
            if "__pycache__" not in f.parts:
                zf.write(f, Path(module.__name__) / f.relative_to(pkg_dir))
    return out


def ship_package(spark, module) -> Path:
    """Make an installed pure-Python package importable on every executor."""
    out = zip_package(module, Path(tempfile.mkdtemp(prefix="spark-pkg-")))
    spark.sparkContext.addPyFile(str(out))
    return out


def spark_sql_text(sql: str) -> str:
    """Spark SQL rejects the trailing ';' that DuckDB and BigQuery accept."""
    return sql.rstrip().rstrip(";").rstrip()


def load_cohort(spark, sql: str, tables: Iterable[str],
                env: Mapping[str, str] | None = None,
                duckdb_path: str = "data/eunomia.duckdb",
                params: Mapping[str, object] | None = None):
    """Run cohort SQL in Spark SQL over CDR tables registered as temp views.

    In AoU the BigQuery connector reads each table straight into the executors
    (with column pruning and filter pushdown), so no row-level data passes
    through the small master node. Locally the Eunomia tables are copied in
    from DuckDB, which exercises the same Spark SQL. `params` fills named
    markers in the SQL (e.g. `:outcome_days`).
    """
    env = os.environ if env is None else env
    if backend(env) == "bigquery":
        project, dataset = parse_cdr(env["WORKSPACE_CDR"])
        for t in tables:
            (spark.read.format("bigquery")
             .option("parentProject", env.get("GOOGLE_CLOUD_PROJECT") or project)
             .load(f"{project}.{dataset}.{t}")
             .createOrReplaceTempView(t))
    else:
        import duckdb

        con = duckdb.connect(duckdb_path, read_only=True)
        try:
            for t in tables:
                spark.createDataFrame(con.execute(f"SELECT * FROM {t}").df()).createOrReplaceTempView(t)
        finally:
            con.close()
    if params:
        return spark.sql(spark_sql_text(sql), args=dict(params))
    return spark.sql(spark_sql_text(sql))
