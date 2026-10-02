from __future__ import annotations

from sync import apply_sync_plan, plan_sync


def test_selected_subtree_syncs_both_ways_without_overwriting(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    (left / "chapter").mkdir(parents=True)
    (right / "chapter").mkdir(parents=True)
    (left / "chapter" / "left.txt").write_text("left", encoding="utf-8")
    (right / "chapter" / "right.txt").write_text("right", encoding="utf-8")
    (left / "chapter" / "shared.txt").write_text("left version", encoding="utf-8")
    (right / "chapter" / "shared.txt").write_text("right version", encoding="utf-8")
    (left / "outside.txt").write_text("outside", encoding="utf-8")
    plan = plan_sync((str(left), str(right)), ({str(left / "chapter")}, {str(right / "chapter")}))
    assert sum(not action.is_directory for action in plan.actions) == 2
    assert plan.existing_files == 2
    folders, files, errors = apply_sync_plan(plan)
    assert (folders, files, errors) == (0, 2, ())
    assert (right / "chapter" / "left.txt").read_text() == "left"
    assert (left / "chapter" / "right.txt").read_text() == "right"
    assert (right / "chapter" / "shared.txt").read_text() == "right version"
    assert not (right / "outside.txt").exists()


def test_selected_folder_preserves_nested_structure(tmp_path):
    left, right = tmp_path / "left", tmp_path / "right"
    (left / "selected" / "deep").mkdir(parents=True)
    right.mkdir()
    (left / "selected" / "deep" / "file.txt").write_text("nested", encoding="utf-8")
    plan = plan_sync((str(left), str(right)), ({str(left / "selected")}, set()))
    assert sum(action.is_directory for action in plan.actions) == 2
    assert apply_sync_plan(plan) == (2, 1, ())
    assert (right / "selected" / "deep" / "file.txt").read_text() == "nested"
