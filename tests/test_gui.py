from __future__ import annotations

from types import SimpleNamespace

import pytest
import tkinter as tk

from duplicate_finder import DuplicateFinderApp


def test_drag_drop_with_spaces_and_dark_mode(tmp_path):
    dnd = pytest.importorskip("tkinterdnd2")
    try:
        root = dnd.TkinterDnD.Tk()
    except tk.TclError:
        pytest.skip("Tk display is unavailable")
    try:
        app = DuplicateFinderApp(root)
        assert len(app.panels) == 2
        assert len(app.results.trees) == 3  # Two unique tabs and one shared tab.
        folder = tmp_path / "folder with spaces"
        folder.mkdir()
        (folder / "test file.txt").write_text("example", encoding="utf-8")
        result = app.panels[0]._on_drop(SimpleNamespace(data="{" + str(folder) + "}"))
        assert result == "copy"
        assert len(app.panels[0].snapshot.files) == 1
        app.dark_var.set(True)
        app._apply_theme()
        app.sha256_var.set(True)
        app._run_compare()
        assert app.results.comparison is not None
        assert len(app.results.comparison.unique[0]) == 1
    finally:
        root.destroy()


def test_result_sort_and_open_both_paths(tmp_path, monkeypatch):
    dnd = pytest.importorskip("tkinterdnd2")
    try:
        root = dnd.TkinterDnD.Tk()
    except tk.TclError:
        pytest.skip("Tk display is unavailable")
    try:
        app = DuplicateFinderApp(root)
        folders = [tmp_path / "one", tmp_path / "two"]
        for folder in folders:
            folder.mkdir()
            for name in ("Z.txt", "A.txt"):
                (folder / name).write_text(name, encoding="utf-8")
        for panel, folder in zip(app.panels, folders):
            panel.add_paths([str(folder)])
        app._run_compare()
        tree = app.results.trees[2]
        assert len(tree.get_children()) == 4
        assert all(app.results.row_entries[tree][item][1].matched_criteria == ("name",)
                   for item in tree.get_children())
        app.results._sort(tree, "name")
        names = [tree.set(item, "name") for item in tree.get_children()]
        assert names == sorted(names)
        app.results._sort(tree, "name")
        assert [tree.set(item, "name") for item in tree.get_children()] == sorted(names, reverse=True)

        item = tree.get_children()[0]
        monkeypatch.setattr(tree, "identify_region", lambda x, y: "cell")
        monkeypatch.setattr(tree, "identify_column", lambda x: "#3")
        monkeypatch.setattr(tree, "identify_row", lambda y: item)
        calls = []
        monkeypatch.setattr("duplicate_finder.subprocess.Popen", lambda args: calls.append(args))
        app.results._open_path(SimpleNamespace(x=0, y=0), tree)
        assert len(calls) == 2
        assert {args[-1] for args in calls} == {str(folder / "Z.txt") for folder in folders}
    finally:
        root.destroy()


def test_sync_dialog_shows_folder_choices(tmp_path):
    dnd = pytest.importorskip("tkinterdnd2")
    try:
        root = dnd.TkinterDnD.Tk()
    except tk.TclError:
        pytest.skip("Tk display is unavailable")
    try:
        app = DuplicateFinderApp(root)
        for index, panel in enumerate(app.panels):
            folder = tmp_path / f"list{index}"
            (folder / "child").mkdir(parents=True)
            panel.add_paths([str(folder)])
        app._show_sync()
        dialog = next(widget for widget in root.winfo_children() if isinstance(widget, tk.Toplevel))
        assert dialog.title() == "Ordnerinhalte synchronisieren"
        assert dialog.winfo_exists()
        dialog.destroy()
    finally:
        root.destroy()
