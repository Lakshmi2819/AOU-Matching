"""Spark session setup that works both locally and on the AoU Dataproc cluster.

Locally, pyspark from pip starts an in-process local[*] cluster. On Dataproc,
the cluster's spark-defaults pick the master (YARN), so the same call works.
Pure-Python packages that run inside executors (e.g. brpmatch's applyInPandas
functions) must also be shipped to the workers: ship_package() zips the
package and registers it with addPyFile.
"""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path


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
