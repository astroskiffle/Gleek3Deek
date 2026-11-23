import json
import os

import pytest

import library as L
from library import Library, matches, parse_query


def mk(tmp_path, name="a.glb", data=b"x" * 1000):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_set_and_read_back_and_persist(tmp_path):
    f = mk(tmp_path)
    lib = Library(str(tmp_path / L.LIB_NAME))
    lib.set_rating([f], 4)
    lib.set_color([f], "Red")
    lib.set_tags(f, ["Rock", "hard surface", "rock", " "])
    g = lib.get(f)
    assert g == {"tags": ["Rock", "hard surface"], "color": "red", "rating": 4}
    again = Library(str(tmp_path / L.LIB_NAME))
    assert again.get(f) == g
    d = json.loads((tmp_path / L.LIB_NAME).read_text(encoding="utf-8"))
    assert d["gleek3deek_library"] == 1 and list(d["files"]) == ["a.glb"]   # relative to the library file


def test_clearing_everything_removes_the_entry(tmp_path):
    f = mk(tmp_path)
    lib = Library(str(tmp_path / L.LIB_NAME))
    lib.set_rating([f], 3)
    lib.set_rating([f], 0)
    assert not lib.has_any()
    assert json.loads((tmp_path / L.LIB_NAME).read_text())["files"] == {}


def test_values_are_clamped_and_cleaned(tmp_path):
    f = mk(tmp_path)
    lib = Library(str(tmp_path / L.LIB_NAME))
    lib.set_rating([f], 99)
    lib.set_color([f], "chartreuse")
    lib.set_tags(f, ["#a, b", "x" * 100] + [f"t{i}" for i in range(60)])
    g = lib.get(f)
    assert g["rating"] == 5 and g["color"] == "" and len(g["tags"]) == L.MAX_TAGS
    assert g["tags"][0] == "a b" and len(g["tags"][1]) == L.MAX_TAG_LEN


def test_change_tags_keeps_other_tags_per_file(tmp_path):
    a, b = mk(tmp_path, "a.glb"), mk(tmp_path, "b.glb")
    lib = Library(str(tmp_path / L.LIB_NAME))
    lib.set_tags(a, ["x", "common"])
    lib.set_tags(b, ["y", "common"])
    lib.change_tags([a, b], ["common"], ["new"])
    assert lib.get(a)["tags"] == ["x", "new"] and lib.get(b)["tags"] == ["y", "new"]


def test_rename_and_remove_follow_the_file(tmp_path):
    a = mk(tmp_path, "a.glb")
    lib = Library(str(tmp_path / L.LIB_NAME))
    lib.set_rating([a], 2)
    b = str(tmp_path / "b.glb")
    os.rename(a, b)
    lib.rename(a, b)
    assert lib.get(b)["rating"] == 2 and lib.get(a)["rating"] == 0
    lib.remove(b)
    assert not lib.has_any()


def test_relink_after_rename_outside_the_app(tmp_path):
    a = mk(tmp_path, "a.glb", b"hello" * 5000)
    other = mk(tmp_path, "other.glb", b"different" * 100)
    lib = Library(str(tmp_path / L.LIB_NAME))
    lib.set_tags(a, ["keep"])
    b = str(tmp_path / "renamed.glb")
    os.rename(a, b)
    assert lib.relink(str(tmp_path), [b, other]) == 1
    assert lib.get(b)["tags"] == ["keep"]
    assert lib.relink(str(tmp_path), [b, other]) == 0


def test_damaged_file_is_set_aside_not_overwritten(tmp_path):
    p = tmp_path / L.LIB_NAME
    p.write_text("{ not json", encoding="utf-8")
    lib = Library(str(p))
    assert not lib.has_any() and "could not be read" in lib.notice
    assert any(n.startswith(L.LIB_NAME + ".damaged-") for n in os.listdir(tmp_path))
    lib.set_rating([mk(tmp_path)], 1)
    assert json.loads(p.read_text())["gleek3deek_library"] == 1


def test_a_foreign_json_file_is_not_treated_as_a_library(tmp_path):
    p = tmp_path / L.LIB_NAME
    p.write_text(json.dumps({"hello": 1}), encoding="utf-8")
    assert "could not be read" in Library(str(p)).notice


def test_backup_and_merge_with_another_running_copy(tmp_path):
    a, b = mk(tmp_path, "a.glb"), mk(tmp_path, "b.glb")
    path = str(tmp_path / L.LIB_NAME)
    one, two = Library(path), Library(path)
    one.set_rating([a], 5)
    os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
    two.set_rating([b], 3)                              # two has not seen a's rating yet
    fresh = Library(path)
    assert fresh.get(a)["rating"] == 5 and fresh.get(b)["rating"] == 3
    assert os.path.isfile(path + ".bak")


def test_smart_folders_and_find(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    a, b, c = mk(tmp_path, "a.glb"), mk(sub, "b.glb"), mk(tmp_path, "c.glb")
    lib = Library(str(tmp_path / L.LIB_NAME))
    lib.set_tags(a, ["rock"])
    lib.set_rating([a], 5)
    lib.set_tags(b, ["rock", "old"])
    lib.set_rating([b], 2)
    lib.set_tags(c, ["tree"])
    assert lib.find("tag:rock") == sorted([os.path.normpath(a), os.path.normpath(b)],
                                           key=lambda p: (os.path.basename(p), p))
    assert lib.find("tag:rock rating:>=4") == [os.path.normpath(a)]
    assert lib.find("tag:rock -tag:old") == [os.path.normpath(a)]
    os.remove(a)
    assert lib.find("tag:rock rating:>=4") == []         # missing files are skipped
    assert lib.save_smart("Best rocks", "tag:rock rating:>=4")
    assert Library(str(tmp_path / L.LIB_NAME)).smart == {"Best rocks": "tag:rock rating:>=4"}
    lib.delete_smart("Best rocks")
    assert Library(str(tmp_path / L.LIB_NAME)).smart == {}
    assert [t for t, _n in lib.all_tags()][0] == "rock"


def test_move_to_another_file_keeps_the_data(tmp_path):
    a = mk(tmp_path, "a.glb")
    lib = Library(str(tmp_path / L.LIB_NAME))
    lib.set_color([a], "blue")
    new = tmp_path / "elsewhere" / "lib.json"
    assert lib.move_to(str(new)) and new.is_file()
    assert Library(str(new)).get(a)["color"] == "blue"


def test_query_parsing_and_matching():
    q = parse_query('rock #hard tag:"hard surface" -tag:old color:Red rating:>=3')
    assert q["words"] == ["rock"] and q["tags"] == ["hard", "hard surface"] and q["not_tags"] == ["old"]
    assert q["colors"] == ["red"] and q["rating"] == (">=", 3)
    meta = {"tags": ["Hard", "hard surface"], "color": "red", "rating": 4}
    assert matches(q, "big_rock.glb", meta)
    assert not matches(q, "big_rock.glb", {**meta, "rating": 2})
    assert not matches(q, "tree.glb", meta)
    assert matches(parse_query("rating:3+"), "x", {"rating": 3})
    assert matches(parse_query("color:none"), "x", None) and not matches(parse_query("rating:1+"), "x", None)
    assert L.query_is_empty(parse_query("   "))
    assert matches(parse_query("tre"), "a.glb", {"tags": ["tree"]})     # bare words also match tags


def test_resolve_library_path(tmp_path):
    base, fb = tmp_path / "app", tmp_path / "data"
    base.mkdir()
    assert L.resolve_library_path(str(base), str(fb)) == str(base / L.LIB_NAME)
    assert L.resolve_library_path(str(base), str(fb), "/x/y.json") == "/x/y.json"
    assert L.resolve_library_path(str(tmp_path / "missing-readonly"), str(fb)) == str(fb / L.LIB_NAME)


# ----- favourite and recent folders -----
def test_favourites_add_remove_persist_and_cap(tmp_path):
    folders = []
    for i in range(L.MAX_FAVOURITES + 2):
        d = tmp_path / f"f{i}"
        d.mkdir()
        folders.append(str(d))
    lib = Library(str(tmp_path / L.LIB_NAME))
    assert lib.add_fav(folders[0]) == "added" and lib.add_fav(folders[0]) == "exists"
    for f in folders[1:L.MAX_FAVOURITES]:
        assert lib.add_fav(f) == "added"
    assert lib.add_fav(folders[-1]) == "full" and len(lib.fav_paths()) == L.MAX_FAVOURITES
    again = Library(str(tmp_path / L.LIB_NAME))
    assert again.fav_paths()[0] == os.path.normpath(folders[0]) and again.is_fav(folders[3])
    assert again.remove_fav(folders[0]) and not again.remove_fav(folders[0])
    assert not Library(str(tmp_path / L.LIB_NAME)).is_fav(folders[0])


def test_favourites_survive_other_saves_and_merge(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    f = mk(tmp_path)
    path = str(tmp_path / L.LIB_NAME)
    one, two = Library(path), Library(path)
    one.add_fav(str(a))
    os.utime(path, (os.path.getmtime(path) + 5, os.path.getmtime(path) + 5))
    two.set_rating([f], 3)                              # two never saw the favourite, and must not drop it
    fresh = Library(path)
    assert fresh.is_fav(str(a)) and fresh.get(f)["rating"] == 3


def test_favourites_follow_a_moved_library_file(tmp_path):
    d = tmp_path / "models"
    d.mkdir()
    lib = Library(str(tmp_path / L.LIB_NAME))
    lib.add_fav(str(d))
    new = tmp_path / "elsewhere" / "lib.json"
    assert lib.move_to(str(new))
    assert Library(str(new)).fav_paths() == [os.path.normpath(str(d))]


def test_push_recent_newest_first_no_duplicates_and_limit():
    items = []
    for i in range(14):
        items = L.push_recent(items, f"/m/f{i}")
    assert len(items) == L.MAX_RECENT and items[0] == os.path.normpath("/m/f13")
    items = L.push_recent(items, "/m/f10/")             # an older one moves to the front, not duplicated
    assert items[0] == os.path.normpath("/m/f10") and len(items) == L.MAX_RECENT
    assert len([p for p in items if p.endswith("f10")]) == 1
