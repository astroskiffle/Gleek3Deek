import io
import json
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
def folder(tmp_path, monkeypatch):
    for n in ("a.glb", "b.stl", "skip.bvh", "notes.txt"):
        (tmp_path / n).write_text("x")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.obj").write_text("x")
    try:
        os.symlink(tmp_path / "a.glb", tmp_path / "link.glb")
    except (OSError, NotImplementedError):
        pass

    def fake_load(p):
        if os.path.basename(p) == "b.stl":
            raise formats.LoadError("broken file")
        return fakes.actors("hole" if os.path.basename(p) == "c.obj" else "good")

    monkeypatch.setattr(cli, "load_scene", fake_load)
    return tmp_path


def test_audit_model_sections_and_text():
    res = analysis.audit_model(fakes.actors(), "/x/cube.glb", {"textures", "mesh", "uv", "measure"}, ("m", "cm"))
    json.dumps(res)                                           # plain data only
    assert res["mesh"]["watertight"] and res["textures"]["unique_images"] == 1
    assert abs(res["measure"]["volume"] - 6e6) < 1 and res["measure"]["unit"] == "cm"
    text = cli.format_text(res, set())
    assert "watertight" in text and "Base colour" in text and "Measure" in text


def test_checks():
    good = analysis.audit_model(fakes.actors(), "/x/g.glb", {"mesh", "uv", "textures"}, ("m", "m"))
    bad = analysis.audit_model(fakes.actors("hole"), "/x/h.glb", {"mesh", "uv"}, ("m", "m"))
    assert cli.run_checks(good, {"holes", "flipped", "duplicates", "open"}, {}) == []
    reasons = cli.run_checks(bad, {"holes", "open"}, {})
    assert any(r.startswith("holes") for r in reasons) and any(r.startswith("open") for r in reasons)
    assert cli.run_checks(good, set(), {"triangles": 5})


def test_single_file_json(folder):
    code, out, err = go([str(folder / "a.glb"), "--all", "--json", "--units", "m:cm"])
    assert code == 0, err
    assert json.loads(out)["files"][0]["measure"]["unit"] == "cm"


def test_folder_run_reports_errors_and_skips(folder):
    code, out, _ = go([str(folder), "--no-isolate", "--mesh"])
    assert code == 3 and "ERROR: broken file" in out and "skipped skip.bvh" in out
    assert "c.obj" not in out                                   # sub-folders need --recursive


def test_fail_on_gives_exit_code_1(folder):
    code, out, _ = go([str(folder), "-r", "--no-isolate", "--mesh", "--fail-on", "holes"])
    assert code == 1 and "FAILED: holes" in out


@pytest.mark.parametrize("argv,fragment", [
    (["/does/not/exist"], "does not exist"),
    (["{d}", "--fail-on", "bogus"], "unknown --fail-on"),
    (["{d}", "--units", "parsec"], "units must be"),
])
def test_usage_errors(folder, argv, fragment):
    code, _out, err = go([a.replace("{d}", str(folder)) for a in argv])
    assert code == 2 and fragment in err


def test_report_safety(folder, tmp_path_factory):
    model = str(folder / "a.glb")
    rep = str(tmp_path_factory.mktemp("rep") / "r.txt")
    assert go([model, "--report", rep, "-q"])[0] == 0 and os.path.exists(rep)
    code, _o, err = go([model, "--report", rep])
    assert code == 2 and "already exists" in err
    assert go([model, "--report", rep, "--force", "-q"])[0] == 0
    code, _o, err = go([str(folder), "--report", str(folder / "audit.txt"), "--no-isolate"])
    assert code == 2 and "inside the folder" in err and not (folder / "audit.txt").exists()


def test_nothing_is_modified(folder):
    before = sorted(os.listdir(folder))
    go([str(folder), "-r", "--all", "--no-isolate"])
    assert sorted(os.listdir(folder)) == before


def test_isolated_mode_survives_a_failing_child(folder):
    code, out, _ = go([str(folder), "--mesh", "--timeout", "60"])
    assert code == 3 and "ERROR" in out                         # every child fails to load these fake files
