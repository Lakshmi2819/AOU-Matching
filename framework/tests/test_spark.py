import types
import zipfile

from utilities.spark import zip_package


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
