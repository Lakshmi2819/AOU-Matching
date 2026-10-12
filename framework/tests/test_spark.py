import types
import zipfile

from utilities.spark import spark_sql_text, zip_package


def test_spark_sql_text_drops_trailing_semicolon():
    # Spark SQL rejects a trailing ';' that DuckDB and BigQuery accept.
    assert spark_sql_text("SELECT 1;\n\n") == "SELECT 1"
    assert spark_sql_text("-- note\nSELECT 1") == "-- note\nSELECT 1"


def test_zip_package_keeps_package_dir_at_archive_root(tmp_path):
    pkg = tmp_path / "src" / "mypkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "sub" / "mod.py").write_text("x = 1\n")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "junk.pyc").write_bytes(b"")
    module = types.SimpleNamespace(__name__="mypkg", __file__=str(pkg / "__init__.py"))

    out = zip_package(module, tmp_path / "out")

    assert out.name == "mypkg.zip"
    names = set(zipfile.ZipFile(out).namelist())
    assert {"mypkg/__init__.py", "mypkg/sub/mod.py"} <= names
    assert not any("__pycache__" in n for n in names)
