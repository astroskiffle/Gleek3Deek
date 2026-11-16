"""CSV and HTML reports for the command-line mode."""
import csv
import io
import os
import types
from contextlib import redirect_stderr, redirect_stdout

import pytest

import analysis
import cli
import formats
import fakes


@pytest.fixture(autouse=True)
def fake_vtk_arrays(monkeypatch):
    monkeypatch.setattr(analysis, "numpy_support", types.SimpleNamespace(
        vtk_to_numpy=lambda x: x.arr if hasattr(x, "arr") else x))


def go(argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = cli.run(argv)
    return code, out.getvalue(), err.getvalue()


@pytest.fixture
def outdir(tmp_path_factory):
    return tmp_path_factory.mktemp("reports")                # reports may not go inside the scanned folder


@pytest.fixture
def folder(tmp_path, monkeypatch):
    for n in ("a.glb", "b.stl", "c.obj", "=evil.glb"):
        (tmp_path / n).write_text("x")

    def fake_load(p):
        name = os.path.basename(p)
        if name == "b.stl":
            raise formats.LoadError("<script>alert(1)</script> broke it")
        return fakes.actors("hole" if name == "c.obj" else "good")

    monkeypatch.setattr(cli, "load_scene", fake_load)
    return tmp_path


def rows_of(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_on_the_console(folder):
    code, out, err = go([str(folder), "--no-isolate", "--all", "--format", "csv", "--fail-on", "holes"])
    assert code == 1, err
    rows = {r["file"]: r for r in rows_of(out)}
    assert set(rows) == {"a.glb", "b.stl", "c.obj", "'=evil.glb"}
    assert rows["a.glb"]["result"] == "ok" and rows["a.glb"]["triangles"] == "12"
    assert rows["c.obj"]["result"] == "FAILED" and "holes" in rows["c.obj"]["failed_checks"]
    assert rows["b.stl"]["result"] == "ERROR" and rows["b.stl"]["triangles"] == ""
    assert rows["a.glb"]["watertight"] == "yes" and rows["c.obj"]["watertight"] == "no"
    assert float(rows["a.glb"]["volume"]) > 0 and rows["a.glb"]["unit"] == "m"
    assert int(rows["a.glb"]["size_bytes"]) == 1


def test_csv_columns_follow_the_sections(folder):
    _c, out_info, _e = go([str(folder / "a.glb"), "--format", "csv"])
    _c, out_all, _e = go([str(folder / "a.glb"), "--format", "csv", "--all", "--lod"])
    h_info, h_all = out_info.splitlines()[0].split(","), out_all.splitlines()[0].split(",")
    assert "triangles" in h_info and "mesh_boundary" not in h_info and "volume" not in h_info
    assert {"mesh_boundary", "uv_oob", "volume", "texture_gpu_bytes", "lod_50pct_triangles"} <= set(h_all)
    # every row has the same number of columns, including a failed load
    assert len({len(r) for r in csv.reader(io.StringIO(go([str(folder), "--no-isolate", "--all", "--format", "csv"])[1]))}) == 1


def test_spreadsheet_formulas_are_defused(folder):
    _c, out, _e = go([str(folder), "--no-isolate", "--format", "csv"])
    cells = [r["file"] for r in rows_of(out)]
    assert "'=evil.glb" in cells and "=evil.glb" not in cells
    assert cli._csv_cell("@SUM(A1)") == "'@SUM(A1)" and cli._csv_cell(-3.5) == "-3.5" and cli._csv_cell(None) == ""


def test_report_format_follows_the_extension(folder, outdir):
    target = outdir / "audit.csv"
    code, out, err = go([str(folder), "--no-isolate", "--mesh", "--report", str(target)])
    assert code == 3, err
    assert "Summary" in out                                          # the console stays text
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")                           # BOM for Excel
    assert rows_of(raw.decode("utf-8-sig"))[0]["file"]


def test_html_report(folder, outdir):
    target = outdir / "audit.html"
    code, out, err = go([str(folder), "--no-isolate", "--all", "--fail-on", "holes", "--report", str(target)])
    assert code == 1, err
    page = target.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and "Gleek3Deek audit report" in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "<script>alert(1)" not in page
    assert page.count("<script>") == 1                               # only our own sort/filter script
    assert "http://" not in page and "https://" not in page and "src=" not in page    # nothing is loaded from anywhere
    assert "FAILED" in page and "c.obj" in page and "a.glb" in page
    assert "Summary" in out                                          # the console shows text


def test_html_needs_a_report_path_and_json_conflicts(folder):
    code, _o, err = go([str(folder / "a.glb"), "--format", "html"])
    assert code == 2 and "--report" in err
    code, _o, err = go([str(folder / "a.glb"), "--json", "--format", "csv"])
    assert code == 2 and "--json" in err


def test_quiet_prints_nothing_but_still_writes(folder, outdir):
    target = outdir / "q.csv"
    code, out, err = go([str(folder / "a.glb"), "-q", "--format", "csv", "--report", str(target)])
    assert code == 0 and out == "" and target.exists()


def test_json_still_works_and_report_extension_does_not_override_it(folder, outdir):
    target = outdir / "j.txt"
    code, out, _e = go([str(folder / "a.glb"), "--json", "--report", str(target)])
    assert code == 0 and out.lstrip().startswith("{") and target.read_text(encoding="utf-8").lstrip().startswith("{")


def test_html_table_keeps_long_errors_short(folder, outdir, monkeypatch):
    long = "The loader stopped unexpectedly: " + "x" * 400
    monkeypatch.setattr(cli, "load_scene", lambda p: (_ for _ in ()).throw(formats.LoadError(long)))
    target = outdir / "long.html"
    go([str(folder / "a.glb"), "--report", str(target)])
    page = target.read_text(encoding="utf-8")
    assert page.count("x" * 400) == 1                                # the whole message appears once, in the details
    assert ("x" * 120 + "...") in page                               # and a shortened copy in the table
    assert "td.name{" in page and "min-width:200px" in page
