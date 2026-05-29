from __future__ import annotations

import csv
import os
import re
import shutil
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Dict, List, Tuple


def _resource(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_OK = True
except ImportError:
    _DND_OK = False


# ---------------------------------------------------------------------------
# File scanning
# ---------------------------------------------------------------------------

def _scan_paths(paths: List[str]) -> Dict[str, List[str]]:
    """Return {filename_lower: [full_path, ...]} for all files under paths."""
    result: Dict[str, List[str]] = {}
    for root_path in paths:
        root_path = root_path.strip()
        if os.path.isfile(root_path):
            name = os.path.basename(root_path).lower()
            result.setdefault(name, []).append(root_path)
        elif os.path.isdir(root_path):
            for dirpath, dirnames, filenames in os.walk(root_path):
                dirnames[:] = [d for d in dirnames if not d.startswith(".")]
                for fname in filenames:
                    if fname.startswith("."):
                        continue
                    name = fname.lower()
                    full = os.path.join(dirpath, fname)
                    result.setdefault(name, []).append(full)
    return result


def _compare(
    names_a: Dict[str, List[str]],
    names_b: Dict[str, List[str]],
) -> Tuple[List[str], List[str], List[str]]:
    keys_a = set(names_a.keys())
    keys_b = set(names_b.keys())
    return sorted(keys_a & keys_b), sorted(keys_a - keys_b), sorted(keys_b - keys_a)


# ---------------------------------------------------------------------------
# Reusable panel
# ---------------------------------------------------------------------------

class _PanelFrame(ttk.LabelFrame):
    def __init__(self, parent: tk.Widget, label: str, app: "DuplicateFinderApp") -> None:
        super().__init__(parent, text=label)
        self._app = app
        self._paths: List[str] = []
        self._file_map: Dict[str, List[str]] = {}

        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        # Buttons row
        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 2))
        ttk.Button(btn_frame, text="Ordner wählen", command=self._pick_folder).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Dateien wählen", command=self._pick_files).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Leeren", command=self.clear).pack(side="left", padx=2)

        # Drop zone
        self._drop_lbl = tk.Label(
            self,
            text="Dateien oder Ordner hier ablegen",
            relief="groove",
            bg="#eef2fa",
            fg="#444",
            font=("Segoe UI", 9),
            height=2,
            cursor="hand2",
        )
        self._drop_lbl.grid(row=1, column=0, sticky="ew", padx=6, pady=4)

        if _DND_OK:
            self.after(0, self._setup_dnd)

        # Loaded paths list
        path_outer = ttk.LabelFrame(self, text="Geladene Pfade")
        path_outer.grid(row=2, column=0, sticky="ew", padx=6, pady=2)
        path_outer.columnconfigure(0, weight=1)

        self._path_lb = tk.Listbox(path_outer, height=3, font=("Segoe UI", 8), selectmode="single")
        self._path_lb.grid(row=0, column=0, sticky="ew", padx=(2, 0))
        sb = ttk.Scrollbar(path_outer, orient="vertical", command=self._path_lb.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self._path_lb.configure(yscrollcommand=sb.set)

        ttk.Button(path_outer, text="Ausgewählten Pfad entfernen", command=self._remove_path).grid(
            row=1, column=0, columnspan=2, sticky="e", padx=2, pady=1
        )

        # File count + treeview
        self._count_var = tk.StringVar(value="Dateien gefunden: 0")
        ttk.Label(self, textvariable=self._count_var, font=("Segoe UI", 9)).grid(
            row=3, column=0, sticky="w", padx=6, pady=(4, 0)
        )

        tv_frame = ttk.Frame(self)
        tv_frame.grid(row=4, column=0, sticky="nsew", padx=6, pady=(2, 6))
        tv_frame.columnconfigure(0, weight=1)
        tv_frame.rowconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        self._tree = ttk.Treeview(tv_frame, columns=("name", "path"), show="headings", selectmode="browse")
        self._tree.heading("name", text="Dateiname")
        self._tree.heading("path", text="Pfad")
        self._tree.column("name", width=180, minwidth=100)
        self._tree.column("path", width=260, minwidth=120)
        self._tree.grid(row=0, column=0, sticky="nsew")

        ttk.Scrollbar(tv_frame, orient="vertical", command=self._tree.yview).grid(row=0, column=1, sticky="ns")
        sb_h = ttk.Scrollbar(tv_frame, orient="horizontal", command=self._tree.xview)
        sb_h.grid(row=1, column=0, sticky="ew")
        self._tree.configure(xscrollcommand=sb_h.set)

    # ------------------------------------------------------------------
    def add_paths(self, paths: List[str]) -> None:
        for p in paths:
            p = p.strip().strip("{}")
            if p and p not in self._paths:
                self._paths.append(p)
                self._path_lb.insert("end", p)
        self._rescan()

    def clear(self) -> None:
        self._paths.clear()
        self._path_lb.delete(0, "end")
        self._file_map.clear()
        self._tree.delete(*self._tree.get_children())
        self._count_var.set("Dateien gefunden: 0")

    def get_file_map(self) -> Dict[str, List[str]]:
        return self._file_map

    def _pick_folder(self) -> None:
        folder = filedialog.askdirectory(title="Ordner wählen")
        if folder:
            self.add_paths([folder])

    def _pick_files(self) -> None:
        files = filedialog.askopenfilenames(title="Dateien wählen")
        if files:
            self.add_paths(list(files))

    def _remove_path(self) -> None:
        sel = self._path_lb.curselection()
        if not sel:
            return
        idx = sel[0]
        self._path_lb.delete(idx)
        del self._paths[idx]
        self._rescan()

    def _setup_dnd(self) -> None:
        registered = False
        for widget in (self._drop_lbl, self._tree, self):
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
                registered = True
            except Exception:
                pass
        if registered:
            self._drop_lbl.configure(
                text="Dateien oder Ordner hier ablegen  (Drag & Drop aktiv)",
                bg="#dff0d8",
            )

    def _on_drop(self, event) -> None:
        paths = [t.strip("{}") for t in re.findall(r"\{[^}]+\}|\S+", event.data)]
        self.add_paths(paths)

    def _rescan(self) -> None:
        self._app.set_status("Scanne…")
        self._file_map = _scan_paths(self._paths)
        self._tree.delete(*self._tree.get_children())
        for name_lower, full_paths in sorted(self._file_map.items()):
            for fp in full_paths:
                self._tree.insert("", "end", values=(os.path.basename(fp), fp))
        total = sum(len(v) for v in self._file_map.values())
        self._count_var.set(f"Dateien gefunden: {total}")
        self._app.set_status("Bereit")


# ---------------------------------------------------------------------------
# Results notebook
# ---------------------------------------------------------------------------

class _ResultsFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget, on_copy_missing=None) -> None:
        super().__init__(parent)
        self._on_copy_missing = on_copy_missing
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        self._nb = ttk.Notebook(self)
        self._nb.grid(row=0, column=0, sticky="nsew", padx=4, pady=2)

        self._tree_only_a = self._make_tab(
            "Nur in Liste 1 (0)",
            ("name", "path"),
            ("Dateiname", "Pfad"),
        )
        self._tree_only_b = self._make_tab(
            "Nur in Liste 2 (0)",
            ("name", "path"),
            ("Dateiname", "Pfad"),
        )
        self._tree_dupes = self._make_tab(
            "Duplikate (0)",
            ("name", "p1", "p2"),
            ("Dateiname", "Pfad in Liste 1", "Pfad in Liste 2"),
        )

        btn_frame = ttk.Frame(self)
        btn_frame.grid(row=1, column=0, sticky="ew", padx=4, pady=(2, 4))
        ttk.Button(btn_frame, text="In Zwischenablage kopieren", command=self._copy).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Als CSV speichern", command=self._save_csv).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Fehlende Dateien kopieren →", command=self._trigger_copy).pack(side="left", padx=4)

        self._data_dupes: List[Tuple] = []
        self._data_only_a: List[Tuple] = []
        self._data_only_b: List[Tuple] = []

    def _make_tab(self, title: str, cols: tuple, headings: tuple) -> ttk.Treeview:
        frame = ttk.Frame(self._nb)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self._nb.add(frame, text=title)

        tree = ttk.Treeview(frame, columns=cols, show="headings", selectmode="browse")
        for col, h in zip(cols, headings):
            tree.heading(col, text=h)
            tree.column(col, width=220, minwidth=80)
        tree.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(frame, orient="vertical", command=tree.yview).grid(row=0, column=1, sticky="ns")
        sb_h = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        sb_h.grid(row=1, column=0, sticky="ew")
        tree.configure(xscrollcommand=sb_h.set)
        return tree

    def populate(
        self,
        dupes: List[str],
        only_a: List[str],
        only_b: List[str],
        map_a: Dict[str, List[str]],
        map_b: Dict[str, List[str]],
    ) -> None:
        for tree in (self._tree_dupes, self._tree_only_a, self._tree_only_b):
            tree.delete(*tree.get_children())
        self._data_dupes.clear()
        self._data_only_a.clear()
        self._data_only_b.clear()

        for name in dupes:
            for pa in map_a.get(name, [""]):
                for pb in map_b.get(name, [""]):
                    display = os.path.basename(pa) if pa else name
                    self._tree_dupes.insert("", "end", values=(display, pa, pb))
                    self._data_dupes.append((display, pa, pb))

        for name in only_a:
            for p in map_a.get(name, [""]):
                display = os.path.basename(p) if p else name
                self._tree_only_a.insert("", "end", values=(display, p))
                self._data_only_a.append((display, p))

        for name in only_b:
            for p in map_b.get(name, [""]):
                display = os.path.basename(p) if p else name
                self._tree_only_b.insert("", "end", values=(display, p))
                self._data_only_b.append((display, p))

        tabs = self._nb.tabs()
        self._nb.tab(tabs[0], text=f"Nur in Liste 1 ({len(self._data_only_a)})")
        self._nb.tab(tabs[1], text=f"Nur in Liste 2 ({len(self._data_only_b)})")
        self._nb.tab(tabs[2], text=f"Duplikate ({len(self._data_dupes)})")

        if self._data_only_a:
            self._nb.select(tabs[0])
        elif self._data_only_b:
            self._nb.select(tabs[1])
        else:
            self._nb.select(tabs[2])

    def _trigger_copy(self) -> None:
        if self._on_copy_missing:
            self._on_copy_missing(self._nb.index(self._nb.select()))

    def _active_data(self) -> List[Tuple]:
        idx = self._nb.index(self._nb.select())
        return [self._data_only_a, self._data_only_b, self._data_dupes][idx]

    def _copy(self) -> None:
        data = self._active_data()
        if not data:
            return
        text = "\n".join("\t".join(str(c) for c in row) for row in data)
        self.clipboard_clear()
        self.clipboard_append(text)

    def _save_csv(self) -> None:
        data = self._active_data()
        if not data:
            messagebox.showinfo("Leer", "Keine Daten zum Speichern vorhanden.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV-Dateien", "*.csv"), ("Alle Dateien", "*.*")],
            title="CSV speichern",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f, delimiter=";").writerows(data)
        messagebox.showinfo("Gespeichert", f"CSV gespeichert:\n{path}")


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class DuplicateFinderApp:
    def __init__(self, root: tk.Tk) -> None:
        self._root = root
        root.title("Datei-Duplikat-Finder")
        root.minsize(1100, 700)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)

        # PanedWindow splits panels (top) from results (bottom)
        pw = ttk.PanedWindow(root, orient="vertical")
        pw.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)

        # ── Top: two panels + compare button ──────────────────────────
        top = ttk.Frame(pw)
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, minsize=140)
        top.columnconfigure(2, weight=1)
        top.rowconfigure(0, weight=1)

        self._panel_a = _PanelFrame(top, "LISTE 1", self)
        self._panel_a.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=4)

        center = ttk.Frame(top)
        center.grid(row=0, column=1, sticky="ns")
        ttk.Button(
            center,
            text="▶  VERGLEICHEN",
            command=self._run_compare,
            width=14,
        ).pack(expand=True, pady=0, padx=6)

        self._panel_b = _PanelFrame(top, "LISTE 2", self)
        self._panel_b.grid(row=0, column=2, sticky="nsew", padx=(4, 0), pady=4)

        pw.add(top, weight=2)

        # ── Bottom: results ───────────────────────────────────────────
        results_outer = ttk.LabelFrame(pw, text="ERGEBNISSE")
        results_outer.columnconfigure(0, weight=1)
        results_outer.rowconfigure(0, weight=1)

        self._results = _ResultsFrame(results_outer, on_copy_missing=self._copy_missing_files)
        self._results.grid(row=0, column=0, sticky="nsew")

        pw.add(results_outer, weight=1)

        # Status bar
        self._status_var = tk.StringVar(value="Bereit")
        ttk.Label(root, textvariable=self._status_var, relief="sunken", anchor="w").grid(
            row=1, column=0, sticky="ew"
        )

    def set_status(self, text: str) -> None:
        self._status_var.set(text)
        self._root.update_idletasks()

    def _copy_missing_files(self, tab_idx: int) -> None:
        if tab_idx == 0:
            data = self._results._data_only_a
            dest_hint = [p for p in self._panel_b._paths if os.path.isdir(p)]
            label = "Liste 1 → Liste 2"
        elif tab_idx == 1:
            data = self._results._data_only_b
            dest_hint = [p for p in self._panel_a._paths if os.path.isdir(p)]
            label = "Liste 2 → Liste 1"
        else:
            messagebox.showinfo("Hinweis", "Bitte einen 'Nur in Liste'-Tab auswählen.")
            return

        if not data:
            messagebox.showinfo("Hinweis", "Keine fehlenden Dateien vorhanden.")
            return

        initial = dest_hint[0] if len(dest_hint) == 1 else None
        dest_dir = filedialog.askdirectory(title=f"Zielordner wählen ({label})", initialdir=initial)
        if not dest_dir:
            return

        if not messagebox.askyesno("Bestätigung", f"{len(data)} Datei(en) nach\n{dest_dir}\nkopieren?"):
            return

        errors: List[str] = []
        copied = 0
        for name, src in data:
            if src and os.path.isfile(src):
                try:
                    shutil.copy2(src, dest_dir)
                    copied += 1
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
            else:
                errors.append(f"{name}: Quelldatei nicht gefunden")

        if errors:
            detail = "\n".join(errors[:10]) + ("…" if len(errors) > 10 else "")
            messagebox.showwarning("Teilerfolg", f"{copied} von {len(data)} Datei(en) kopiert.\n\nFehler:\n{detail}")
        else:
            messagebox.showinfo("Fertig", f"{copied} Datei(en) erfolgreich kopiert.")

    def _run_compare(self) -> None:
        map_a = self._panel_a.get_file_map()
        map_b = self._panel_b.get_file_map()
        if not map_a and not map_b:
            messagebox.showinfo(
                "Hinweis", "Bitte zuerst Dateien oder Ordner in die Listen laden."
            )
            return
        self.set_status("Vergleiche…")
        dupes, only_a, only_b = _compare(map_a, map_b)
        self._results.populate(dupes, only_a, only_b, map_a, map_b)
        self.set_status(
            f"{len(dupes)} Duplikat(e) gefunden  |  Nur in Liste 1: {len(only_a)}  |  Nur in Liste 2: {len(only_b)}"
        )


def _apply_icon(root: tk.Tk) -> None:
    ico = _resource(os.path.join("assets", "kirschke.ico"))
    png = _resource(os.path.join("assets", "favicon.png"))
    try:
        root.iconbitmap(default=ico)
    except Exception:
        pass
    try:
        img = tk.PhotoImage(file=png)
        root.wm_iconphoto(True, img)
    except Exception:
        pass


def main() -> None:
    if _DND_OK:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()
    _apply_icon(root)
    DuplicateFinderApp(root)
    root.after(0, lambda: _apply_icon(root))
    root.mainloop()


if __name__ == "__main__":
    main()
