import json
import os
import shutil

import pytest

import fileops
from fileops import (FileOpsError, companion_files, execute, plan_transfer, split_ext, undo_moves, unique_path)


def w(path, text="x", binary=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as f:
        f.write(text)
    return str(path)


def names(folder):
    out = []
    for root, _d, files in os.walk(folder):
        out += [os.path.relpath(os.path.join(root, f), folder).replace(os.sep, "/") for f in files]
    return sorted(out)


@pytest.fixture
def tree(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    return str(src), str(dst)


def make_obj(src, name="chair", mtl=None, textures=("chair.png",)):
    mtl = mtl or f"{name}.mtl"
    w(os.path.join(src, f"{name}.obj"), f"# test\nmtllib {mtl}\nv 0 0 0\n")
    w(os.path.join(src, mtl), "newmtl a\n" + "".join(f"map_Kd {t}\n" for t in textures))
    for t in textures:
        w(os.path.join(src, t), "img" + t)


# ----------------------------------------------------------------------------- names
def test_split_ext_and_unique_paths(tmp_path):
    assert split_ext("a.obj") == ("a", ".obj") and split_ext("m.mesh.xml") == ("m", ".mesh.xml")
    f = str(tmp_path)
    assert unique_path(f, "a.obj") == os.path.join(f, "a.obj")
    w(os.path.join(f, "a.obj"))
    assert os.path.basename(unique_path(f, "a.obj")) == "a (2).obj"
    w(os.path.join(f, "a (2).obj"))
    assert os.path.basename(unique_path(f, "a.obj")) == "a (3).obj"
    assert os.path.basename(unique_path(f, "a.obj", "copy")) == "a - Copy.obj"
    w(os.path.join(f, "a - Copy.obj"))
    assert os.path.basename(unique_path(f, "a.obj", "copy")) == "a - Copy (2).obj"
    assert os.path.basename(unique_path(f, "a.obj", "number", {os.path.normcase(os.path.join(f, "a (3).obj"))})) == "a (4).obj"


def test_unc_paths_are_recognised():
    assert fileops._is_unc("\\\\server\\share\\a.obj") and not fileops._is_unc("C:\\models\\a.obj")


# ----------------------------------------------------------------------------- reading dependencies
def test_obj_companions_mtl_and_textures(tree):
    src, _ = tree
    make_obj(src, textures=("chair.png", "tex/normal.png"))
    got = [os.path.relpath(c, src).replace(os.sep, "/") for c in companion_files(os.path.join(src, "chair.obj"))]
    assert sorted(got) == ["chair.mtl", "chair.png", "tex/normal.png"]


def test_mtl_options_backslashes_and_spaces(tree):
    src, _ = tree
    w(os.path.join(src, "a.obj"), "mtllib my materials.mtl\n")
    w(os.path.join(src, "my materials.mtl"),
      "newmtl m\nmap_Kd -s 1 1 1 -bm 0.5 sub\\col map.png\nbump -bm 1 bump.png\nKd 1 1 1\n# map_Kd ignored.png\n")
    w(os.path.join(src, "sub", "col map.png"))
    w(os.path.join(src, "bump.png"))
    w(os.path.join(src, "ignored.png"))
    got = {os.path.relpath(c, src).replace(os.sep, "/") for c in companion_files(os.path.join(src, "a.obj"))}
    assert got == {"my materials.mtl", "sub/col map.png", "bump.png"}


def test_obj_with_several_mtl_files_and_missing_ones(tree):
    src, _ = tree
    w(os.path.join(src, "a.obj"), "mtllib one.mtl two.mtl gone.mtl\n")
    w(os.path.join(src, "one.mtl"), "")
    w(os.path.join(src, "two.mtl"), "")
    got = {os.path.basename(c) for c in companion_files(os.path.join(src, "a.obj"))}
    assert got == {"one.mtl", "two.mtl"}


def test_gltf_companions_ignore_data_uris_urls_and_escapes(tree):
    src, _ = tree
    gl = {"buffers": [{"uri": "scene.bin"}, {"uri": "data:application/octet-stream;base64,AAAA"}],
          "images": [{"uri": "tex%20one.png"}, {"uri": "https://example.com/a.png"}, {"uri": "../outside.png"},
                     {"bufferView": 3}]}
    w(os.path.join(src, "m.gltf"), json.dumps(gl))
    w(os.path.join(src, "scene.bin"))
    w(os.path.join(src, "tex one.png"))
    w(os.path.join(os.path.dirname(src), "outside.png"))
    got = {os.path.basename(c) for c in companion_files(os.path.join(src, "m.gltf"))}
    assert got == {"scene.bin", "tex one.png"}


def test_bad_gltf_and_other_formats_have_no_companions(tree):
    src, _ = tree
    w(os.path.join(src, "bad.gltf"), "{not json")
    w(os.path.join(src, "a.stl"), "solid")
    assert companion_files(os.path.join(src, "bad.gltf")) == [] and companion_files(os.path.join(src, "a.stl")) == []


def test_collada_images(tree):
    src, _ = tree
    w(os.path.join(src, "a.dae"), "<library_images><image id='i'><init_from>tex/wood.png</init_from></image>"
                                  "<x><init_from>not_an_image</init_from></x></library_images>")
    w(os.path.join(src, "tex", "wood.png"))
    assert [os.path.basename(c) for c in companion_files(os.path.join(src, "a.dae"))] == ["wood.png"]


# ----------------------------------------------------------------------------- planning and doing it
def test_copy_takes_the_companions_and_keeps_the_originals(tree):
    src, dst = tree
    make_obj(src)
    res = execute(plan_transfer([os.path.join(src, "chair.obj")], dst, move=False))
    assert not res.errors and names(dst) == ["chair.mtl", "chair.obj", "chair.png"]
    assert len(names(src)) == 3 and len(res.copies) == 3 and res.moves == []


def test_move_takes_the_companions_away(tree):
    src, dst = tree
    make_obj(src, textures=("chair.png", "tex/n.png"))
    res = execute(plan_transfer([os.path.join(src, "chair.obj")], dst, move=True))
    assert not res.errors and names(src) == []
    assert names(dst) == ["chair.mtl", "chair.obj", "chair.png", "tex/n.png"]
    assert len(res.moves) == 4 and res.models == [(os.path.join(src, "chair.obj"), os.path.join(dst, "chair.obj"), True)]


def test_without_companions_only_the_model_moves(tree):
    src, dst = tree
    make_obj(src)
    execute(plan_transfer([os.path.join(src, "chair.obj")], dst, move=True, companions=False))
    assert names(dst) == ["chair.obj"] and names(src) == ["chair.mtl", "chair.png"]


def test_companion_used_by_a_model_that_stays_is_copied_not_moved(tree):
    src, dst = tree
    make_obj(src, "a", mtl="shared.mtl", textures=("tex.png",))
    w(os.path.join(src, "b.obj"), "mtllib shared.mtl\n")
    plan = plan_transfer([os.path.join(src, "a.obj")], dst, move=True)
    assert any("used by other models" in n for n in plan.notes)
    execute(plan)
    assert names(src) == ["b.obj", "shared.mtl", "tex.png"]              # b still works
    assert names(dst) == ["a.obj", "shared.mtl", "tex.png"]


def test_companion_shared_by_two_moved_models_moves_once(tree):
    src, dst = tree
    make_obj(src, "a", mtl="shared.mtl", textures=("tex.png",))
    w(os.path.join(src, "b.obj"), "mtllib shared.mtl\n")
    res = execute(plan_transfer([os.path.join(src, "a.obj"), os.path.join(src, "b.obj")], dst, move=True))
    assert not res.errors and names(src) == [] and names(dst) == ["a.obj", "b.obj", "shared.mtl", "tex.png"]


def test_model_name_clash_gets_a_number_and_nothing_is_overwritten(tree):
    src, dst = tree
    make_obj(src)
    w(os.path.join(dst, "chair.obj"), "old")
    plan = plan_transfer([os.path.join(src, "chair.obj")], dst, move=False)
    assert any("chair (2).obj" in n for n in plan.notes)
    execute(plan)
    assert open(os.path.join(dst, "chair.obj")).read() == "old"
    assert "chair (2).obj" in names(dst)


def test_identical_companion_at_the_destination_is_reused(tree):
    src, dst = tree
    make_obj(src)
    shutil.copy2(os.path.join(src, "chair.png"), os.path.join(dst, "chair.png"))
    plan = plan_transfer([os.path.join(src, "chair.obj")], dst, move=True)
    assert [s.action for s in plan.bundles[0].companions].count("reuse") == 1
    res = execute(plan)
    assert not res.errors and sorted(names(dst)) == ["chair.mtl", "chair.obj", "chair.png"]


def test_different_companion_at_the_destination_skips_the_whole_bundle(tree):
    src, dst = tree
    make_obj(src)
    w(os.path.join(dst, "chair.png"), "something else entirely")
    plan = plan_transfer([os.path.join(src, "chair.obj")], dst, move=True)
    assert plan.bundles == [] and "different file" in plan.skipped[0][1]
    assert len(names(src)) == 3 and names(dst) == ["chair.png"]


def test_move_into_the_same_folder_is_skipped_and_copy_makes_a_numbered_model(tree):
    src, _ = tree
    make_obj(src)
    p = os.path.join(src, "chair.obj")
    assert plan_transfer([p], src, move=True).skipped[0][1] == "it is already in that folder"
    plan = plan_transfer([p], src, move=False)
    res = execute(plan)
    assert not res.errors and "chair - Copy.obj" in names(src)
    assert names(src).count("chair.mtl") == 1                              # the companions are reused, not duplicated


def test_bad_destination_and_missing_files(tree):
    src, dst = tree
    with pytest.raises(FileOpsError):
        plan_transfer([], os.path.join(dst, "nope"), move=True)
    plan = plan_transfer([os.path.join(src, "gone.obj")], dst, move=True)
    assert plan.bundles == [] and "no longer there" in plan.skipped[0][1]


def test_a_failing_model_puts_its_companions_back(tree, monkeypatch):
    src, dst = tree
    make_obj(src)
    model = os.path.join(src, "chair.obj")
    real = fileops._move_file

    def flaky(a, b):
        if os.path.basename(a) == "chair.obj" and a == model:
            raise OSError("disk full")
        return real(a, b)
    monkeypatch.setattr(fileops, "_move_file", flaky)
    res = execute(plan_transfer([model], dst, move=True))
    assert res.errors and "disk full" in res.errors[0]
    assert names(src) == ["chair.mtl", "chair.obj", "chair.png"] and names(dst) == []


def test_one_bad_bundle_does_not_stop_the_others(tree, monkeypatch):
    src, dst = tree
    make_obj(src, "a")
    make_obj(src, "b")
    real = fileops._move_file
    monkeypatch.setattr(fileops, "_move_file", lambda a, b: (_ for _ in ()).throw(OSError("locked"))
                        if os.path.basename(a) == "a.obj" else real(a, b))
    res = execute(plan_transfer([os.path.join(src, "a.obj"), os.path.join(src, "b.obj")], dst, move=True))
    assert len(res.errors) == 1 and "b.obj" in names(dst) and "a.obj" in names(src)


def test_move_across_drives_falls_back_to_copy_and_remove(tree, monkeypatch):
    src, dst = tree
    make_obj(src)
    monkeypatch.setattr(os, "rename", lambda a, b: (_ for _ in ()).throw(OSError("cross-device")))
    res = execute(plan_transfer([os.path.join(src, "chair.obj")], dst, move=True))
    assert not res.errors and names(src) == [] and len(names(dst)) == 3


def test_progress_is_reported_per_bundle(tree):
    src, dst = tree
    make_obj(src, "a")
    make_obj(src, "b")
    seen = []
    execute(plan_transfer([os.path.join(src, "a.obj"), os.path.join(src, "b.obj")], dst, move=False),
            progress=lambda n, t: seen.append((n, t)))
    assert seen == [(1, 2), (2, 2)]


def test_plain_files_are_transferred_alone(tree):
    src, dst = tree
    w(os.path.join(src, "a.stl"), "solid")
    res = execute(plan_transfer([os.path.join(src, "a.stl")], dst, move=True))
    assert names(dst) == ["a.stl"] and not res.errors


# ----------------------------------------------------------------------------- undo
def test_undo_puts_moved_files_back(tree):
    src, dst = tree
    make_obj(src)
    res = execute(plan_transfer([os.path.join(src, "chair.obj")], dst, move=True))
    restored, skipped = undo_moves(res.moves)
    assert restored == 3 and skipped == [] and names(dst) == []
    assert names(src) == ["chair.mtl", "chair.obj", "chair.png"]


def test_undo_skips_files_that_changed_since(tree):
    src, dst = tree
    make_obj(src)
    res = execute(plan_transfer([os.path.join(src, "chair.obj")], dst, move=True))
    os.remove(os.path.join(dst, "chair.png"))                              # gone since
    w(os.path.join(src, "chair.mtl"), "new file in the old place")         # old place taken
    restored, skipped = undo_moves(res.moves)
    assert restored == 1 and len(skipped) == 2
    assert open(os.path.join(src, "chair.mtl")).read() == "new file in the old place"


def test_selected_companions_are_not_transferred_twice(tree):
    """Copying an OBJ together with its .mtl and texture from Explorer must not produce 'chair (2).mtl'."""
    src, dst = tree
    make_obj(src)
    paths = [os.path.join(src, n) for n in ("chair.obj", "chair.mtl", "chair.png")]
    res = execute(plan_transfer(paths, dst, move=False))
    assert not res.errors and names(dst) == ["chair.mtl", "chair.obj", "chair.png"]


def test_companions_off_transfers_each_selected_file_on_its_own(tree):
    src, dst = tree
    make_obj(src)
    paths = [os.path.join(src, n) for n in ("chair.obj", "chair.mtl")]
    execute(plan_transfer(paths, dst, move=True, companions=False))
    assert names(dst) == ["chair.mtl", "chair.obj"] and names(src) == ["chair.png"]


def test_undo_of_a_rename_and_of_several_steps_in_order(tree):
    src, dst = tree
    a = w(os.path.join(src, "a.stl"), "A")
    b = os.path.join(src, "b.stl")
    os.rename(a, b)                                                        # a rename, as the app does it
    res = execute(plan_transfer([b], dst, move=True))                      # then a move
    assert names(dst) == ["b.stl"]
    assert undo_moves(res.moves) == (1, []) and names(src) == ["b.stl"]    # the move is undone first
    assert undo_moves([(a, b)]) == (1, []) and names(src) == ["a.stl"]     # then the rename


def test_undo_does_not_overwrite_a_file_that_took_the_old_name(tree):
    src, dst = tree
    p = w(os.path.join(src, "a.stl"), "original")
    res = execute(plan_transfer([p], dst, move=True))
    w(os.path.join(src, "a.stl"), "newer")
    restored, skipped = undo_moves(res.moves)
    assert restored == 0 and len(skipped) == 1 and open(p).read() == "newer"


# ----------------------------------------------------------------------------- batch rename
from fileops import expand_pattern, name_problem, plan_batch_rename, rename_many


def test_pattern_numbers_and_names():
    assert expand_pattern("holiday_###", "x", 7) == "holiday_007"
    assert expand_pattern("C64_[name]", "tree", 1) == "C64_tree"
    assert expand_pattern("[name]_#_##", "a", 3) == "a_3_03"
    assert expand_pattern("fixed", "a", 3) == "fixed"


def test_name_problems():
    assert name_problem("ok name.obj") == ""
    assert "can't contain" in name_problem('a?b.obj') and "empty" in name_problem("  ")
    assert "space or dot" in name_problem("a.obj.") and "reserved" in name_problem("CON.obj")
    assert "too long" in name_problem("a" * 300 + ".obj") and name_problem("a:b") != ""


def files3(src):
    return [w(os.path.join(src, n), n) for n in ("c.stl", "a.obj", "b.fbx")]


def test_plan_numbers_in_the_order_given_and_keeps_extensions(tree):
    src, _ = tree
    c, a, b = files3(src)
    items = plan_batch_rename([c, a, b], "part_###", first=5)
    assert [i.name for i in items] == ["part_005.stl", "part_006.obj", "part_007.fbx"]
    assert all(not i.problem for i in items)


def test_plan_flags_duplicates_existing_files_and_bad_names(tree):
    src, _ = tree
    c, a, b = files3(src)
    w(os.path.join(src, "taken.stl"))
    assert not any(i.problem for i in plan_batch_rename([c, a], "same"))      # same.stl and same.obj differ
    same_ext = [w(os.path.join(src, "x1.stl")), w(os.path.join(src, "x2.stl"))]
    assert all("same new name" in i.problem for i in plan_batch_rename(same_ext, "same"))
    assert "already exists" in plan_batch_rename([c], "taken")[0].problem
    assert "can't contain" in plan_batch_rename([c], "a/b")[0].problem
    assert "no longer" in plan_batch_rename([os.path.join(src, "gone.stl")], "x")[0].problem


def test_unchanged_names_are_not_problems(tree):
    src, _ = tree
    c, a, _b = files3(src)
    items = plan_batch_rename([c, a], "[name]")
    assert not any(i.changed or i.problem for i in items)


def test_a_new_name_may_be_a_name_another_selected_file_is_leaving(tree):
    src, _ = tree
    a = w(os.path.join(src, "a.stl"), "A")
    b = w(os.path.join(src, "b.stl"), "B")
    items = plan_batch_rename([a, b], "[name]")                       # unchanged
    assert not any(i.problem for i in items)
    items = plan_batch_rename([a, b], "#", first=1)                    # a->1, b->2: fine
    assert not any(i.problem for i in items)
    w(os.path.join(src, "2.stl"), "old two")
    items = plan_batch_rename([a, b], "#", first=1)                    # b->2 would hit an unrelated file
    assert items[1].problem and not items[0].problem


def test_rename_many_swaps_and_shifts_names(tree):
    src, _ = tree
    a = w(os.path.join(src, "a.stl"), "A")
    b = w(os.path.join(src, "b.stl"), "B")
    c = w(os.path.join(src, "c.stl"), "C")
    done, err = rename_many([(a, b), (b, a)])                         # a swap
    assert err == "" and len(done) == 2
    assert open(a).read() == "B" and open(b).read() == "A"
    done, err = rename_many([(a, b), (b, c), (c, a)])                 # a rotation
    assert err == "" and (open(a).read(), open(b).read(), open(c).read()) == ("C", "B", "A")
    assert sorted(names(src)) == ["a.stl", "b.stl", "c.stl"]
    assert not [n for n in names(src) if n.startswith(".g3d")]


def test_rename_many_refuses_clashes_before_touching_anything(tree):
    src, _ = tree
    a = w(os.path.join(src, "a.stl"), "A")
    b = w(os.path.join(src, "b.stl"), "B")
    w(os.path.join(src, "z.stl"), "Z")
    done, err = rename_many([(a, os.path.join(src, "z.stl")), (b, os.path.join(src, "y.stl"))])
    assert done == [] and "already exists" in err and names(src) == ["a.stl", "b.stl", "z.stl"]
    done, err = rename_many([(a, os.path.join(src, "n.stl")), (b, os.path.join(src, "n.stl"))])
    assert done == [] and err


def test_rename_many_rolls_back_when_the_second_phase_fails(tree, monkeypatch):
    src, _ = tree
    a = w(os.path.join(src, "a.stl"), "A")
    b = w(os.path.join(src, "b.stl"), "B")
    real = os.rename
    calls = {"n": 0}

    def flaky(x, y):
        calls["n"] += 1
        if calls["n"] == 4:                       # two moves aside, one placed, then the second placement fails
            raise OSError("disk error")
        return real(x, y)
    monkeypatch.setattr(os, "rename", flaky)
    done, err = rename_many([(a, os.path.join(src, "n1.stl")), (b, os.path.join(src, "n2.stl"))])
    monkeypatch.setattr(os, "rename", real)
    assert done == [] and "disk error" in err
    assert names(src) == ["a.stl", "b.stl"] and open(a).read() == "A" and open(b).read() == "B"
