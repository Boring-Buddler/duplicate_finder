"""Desktop interface for comparing files in two lists."""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
import sys
import tkinter as tk
from tkinter import colorchooser, filedialog, messagebox, ttk

from comparison import CRITERIA, CompareOptions, Comparison, FileResult, Snapshot, compare, scan_paths
from report import make_html_report
from sync import apply_sync_plan, plan_sync

DEFAULT_CRITERION_COLORS = {
    "name": "#e63946", "extension": "#f4a261", "size": "#2a9d8f",
    "mtime": "#8d5fd3", "path": "#2f80ed", "author": "#d97706",
    "sha256": "#ec4899",
}

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False


def _resource(relative: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


class InputPanel(ttk.LabelFrame):
    def __init__(self, parent: tk.Widget, number: int, app: "DuplicateFinderApp") -> None:
        super().__init__(parent, text=f"LISTE {number}")
        self.app = app
        self.paths: list[str] = []
        self.snapshot = Snapshot((), (), ())
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)

        buttons = ttk.Frame(self)
        buttons.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        ttk.Button(buttons, text="Ordner wählen", command=self._pick_folder).pack(side="left", padx=2)
        ttk.Button(buttons, text="Dateien wählen", command=self._pick_files).pack(side="left", padx=2)
        ttk.Button(buttons, text="Leeren", command=self.clear).pack(side="left", padx=2)

        drop_text = "Dateien oder Ordner hier ablegen" if DND_AVAILABLE else "Drag-and-drop benötigt tkinterdnd2"
        self.drop_label = tk.Label(self, text=drop_text, relief="groove", height=2, cursor="hand2")
        self.drop_label.grid(row=1, column=0, sticky="ew", padx=7, pady=3)
        self.app.register_tk_widget(self.drop_label, "drop")

        paths_box = ttk.LabelFrame(self, text="Geladene Pfade")
        paths_box.grid(row=2, column=0, sticky="ew", padx=7, pady=3)
        paths_box.columnconfigure(0, weight=1)
        self.path_list = tk.Listbox(paths_box, height=3, font=("Segoe UI", 9))
        self.path_list.grid(row=0, column=0, sticky="ew")
        self.app.register_tk_widget(self.path_list, "list")
        path_scrollbar = ttk.Scrollbar(paths_box, command=self.path_list.yview)
        path_scrollbar.grid(row=0, column=1, sticky="ns")
        self.path_list.configure(yscrollcommand=path_scrollbar.set)
        ttk.Button(paths_box, text="Ausgewählten Pfad entfernen", command=self._remove_path).grid(
            row=1, column=0, columnspan=2, sticky="e", pady=2
        )

        content = ttk.Frame(self)
        content.grid(row=3, column=0, sticky="nsew", padx=7, pady=5)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)
        self.count_var = tk.StringVar(value="Dateien gefunden: 0")
        ttk.Label(content, textvariable=self.count_var).grid(row=0, column=0, sticky="w")
        self.tree = ttk.Treeview(content, columns=("path",), show="tree headings")
        self.tree.heading("#0", text="Verzeichnis / Datei")
        self.tree.heading("path", text="Pfad")
        self.tree.column("#0", width=160, minwidth=100)
        self.tree.column("path", width=250, minwidth=120)
        self.tree.grid(row=1, column=0, sticky="nsew")
        ttk.Scrollbar(content, orient="vertical", command=self.tree.yview).grid(row=1, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(content, orient="horizontal", command=self.tree.xview)
        horizontal.grid(row=2, column=0, sticky="ew")
        self.tree.configure(xscrollcommand=horizontal.set)

        if DND_AVAILABLE:
            for widget in (self.drop_label, self.path_list, self.tree, self):
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)

    def add_paths(self, paths: list[str]) -> None:
        added = 0
        existing = {os.path.normcase(path) for path in self.paths}
        for raw_path in paths:
            path = os.path.abspath(os.path.normpath(raw_path))
            key = os.path.normcase(path)
            if os.path.exists(path) and key not in existing:
                self.paths.append(path)
                self.path_list.insert("end", path)
                existing.add(key)
                added += 1
        if added:
            self._rescan()
        elif paths:
            self.app.set_status("Keine neuen gültigen Pfade gefunden.")

    def clear(self) -> None:
        self.paths.clear()
        self.path_list.delete(0, "end")
        self._rescan()

    def _pick_folder(self) -> None:
        path = filedialog.askdirectory(title="Ordner wählen")
        if path:
            self.add_paths([path])

    def _pick_files(self) -> None:
        paths = filedialog.askopenfilenames(title="Dateien wählen")
        if paths:
            self.add_paths(list(paths))

    def _remove_path(self) -> None:
        selected = self.path_list.curselection()
        if selected:
            del self.paths[selected[0]]
            self.path_list.delete(selected[0])
            self._rescan()

    def _on_drop(self, event: object) -> str:
        # DND_FILES is a Tcl list; splitlist respects braces, spaces and special characters.
        paths = list(self.tk.splitlist(event.data))
        self.add_paths(paths)
        return "copy"

    def _rescan(self) -> None:
        self.app.set_status("Scanne Dateien …")
        self.snapshot = scan_paths(self.paths)
        self.tree.delete(*self.tree.get_children())
        folder_ids: dict[str, str] = {}
        for folder in sorted(self.snapshot.folders, key=lambda path: (path.count(os.sep), path.casefold())):
            parent = folder_ids.get(os.path.dirname(folder), "")
            folder_ids[folder] = self.tree.insert(
                parent, "end", text="📁 " + (os.path.basename(folder) or folder), values=(folder,)
            )
        for path in self.snapshot.files:
            parent = folder_ids.get(os.path.dirname(path), "")
            self.tree.insert(parent, "end", text=os.path.basename(path), values=(path,))
        self.count_var.set(f"Dateien gefunden: {len(self.snapshot.files)}")
        self.app.results.clear()
        self.app.set_status("Bereit")


class ResultsFrame(ttk.Frame):
    def __init__(self, parent: tk.Widget, app: "DuplicateFinderApp") -> None:
        super().__init__(parent)
        self.app = app
        self.comparison: Comparison | None = None
        self.row_entries: dict[ttk.Treeview, dict[str, tuple[int, FileResult]]] = {}
        self.sort_state: dict[ttk.Treeview, tuple[str, bool]] = {}
        self.indicator_images: dict[tuple[str, ...], tk.PhotoImage] = {}
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)
        self.legend = ttk.Frame(self)
        self.legend.grid(row=0, column=0, sticky="w", padx=8, pady=2)
        self.notebook = ttk.Notebook(self)
        self.notebook.grid(row=1, column=0, sticky="nsew", padx=4, pady=3)
        self.trees = [self._tab(f"Nur in Liste {index} (0)") for index in (1, 2)]
        self.trees.append(self._tab("In beiden Listen (0)"))
        buttons = ttk.Frame(self)
        buttons.grid(row=2, column=0, sticky="ew", padx=4, pady=4)
        ttk.Button(buttons, text="In Zwischenablage kopieren", command=self._copy).pack(side="left", padx=3)
        ttk.Button(buttons, text="Als CSV speichern", command=self._save_csv).pack(side="left", padx=3)
        ttk.Button(buttons, text="Fehlende Dateien kopieren →", command=self._copy_files).pack(side="left", padx=3)

    def _tab(self, title: str) -> ttk.Treeview:
        frame = ttk.Frame(self.notebook)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.notebook.add(frame, text=title)
        tree = ttk.Treeview(frame, columns=("list", "name", "path", "key"), show="tree headings")
        tree.heading("#0", text="Kriterien", command=lambda t=tree: self._sort(t, "#0"))
        tree.column("#0", width=125, minwidth=75, stretch=False)
        for column, heading, width in (
            ("list", "Liste", 65), ("name", "Dateiname", 190),
            ("path", "Pfad", 400), ("key", "SHA-256", 250),
        ):
            tree.heading(column, text=heading, command=lambda c=column, t=tree: self._sort(t, c))
            tree.column(column, width=width, minwidth=60)
        tree.grid(row=0, column=0, sticky="nsew")
        ttk.Scrollbar(frame, orient="vertical", command=tree.yview).grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        tree.configure(xscrollcommand=horizontal.set)
        tree.bind("<Double-1>", lambda event, t=tree: self._open_path(event, t))
        self.row_entries[tree] = {}
        return tree

    def clear(self) -> None:
        self.comparison = None
        self.indicator_images.clear()
        self._update_legend()
        for index, tree in enumerate(self.trees):
            tree.delete(*tree.get_children())
            self.row_entries[tree].clear()
            self.sort_state.pop(tree, None)
            for key, label in {"#0": "Kriterien", "list": "Liste", "name": "Dateiname",
                               "path": "Pfad", "key": "SHA-256"}.items():
                tree.heading(key, text=label)
            label = f"Nur in Liste {index + 1} (0)" if index < 2 else "In beiden Listen (0)"
            self.notebook.tab(index, text=label)

    def populate(self, comparison: Comparison) -> None:
        self.clear()
        self.comparison = comparison
        self._update_legend()
        for index, entries in enumerate(comparison.unique):
            for entry in entries:
                self._insert(self.trees[index], index + 1, entry)
            self.notebook.tab(index, text=f"Nur in Liste {index + 1} ({len(entries)})")
        for owner, entry in comparison.shared:
            self._insert(self.trees[2], owner + 1, entry)
        self.notebook.tab(2, text=f"In beiden Listen ({len(comparison.shared)})")
        self.notebook.select(next((index for index, entries in enumerate(comparison.unique) if entries), 2))

    def _insert(self, tree: ttk.Treeview, number: int, entry: FileResult) -> None:
        image = self._indicator_image(entry.matched_criteria)
        item = tree.insert("", "end", image=image,
                           values=(number, os.path.basename(entry.path), entry.path, entry.digest or ""))
        self.row_entries[tree][item] = (number - 1, entry)

    def _indicator_image(self, criteria: tuple[str, ...]) -> tk.PhotoImage | str:
        if not criteria:
            return ""
        colors = tuple(self.app.criterion_colors[item] for item in criteria)
        if colors not in self.indicator_images:
            image = tk.PhotoImage(master=self, width=len(colors) * 18 + 4, height=16)
            for index, color in enumerate(colors):
                center_x = index * 18 + 10
                for y in range(3, 14):
                    for x in range(center_x - 5, center_x + 6):
                        if (x - center_x) ** 2 + (y - 8) ** 2 <= 25:
                            image.put(color, (x, y))
            self.indicator_images[colors] = image
        return self.indicator_images[colors]

    def _update_legend(self) -> None:
        for child in self.legend.winfo_children():
            child.destroy()
        if self.comparison is None:
            return
        selected = (*self.comparison.options.criteria,
                    *(("sha256",) if self.comparison.options.sha256 else ()))
        ttk.Label(self.legend, text="Punkte für Treffer:").pack(side="left", padx=(0, 6))
        for item in selected:
            label = "SHA-256" if item == "sha256" else CRITERIA[item]
            ttk.Label(self.legend, text="●", foreground=self.app.criterion_colors[item]).pack(side="left")
            ttk.Label(self.legend, text=label).pack(side="left", padx=(1, 9))

    def _sort(self, tree: ttk.Treeview, column: str) -> None:
        previous = self.sort_state.get(tree)
        descending = previous is not None and previous[0] == column and not previous[1]
        self.sort_state[tree] = (column, descending)
        headings = {"#0": "Kriterien", "list": "Liste", "name": "Dateiname",
                    "path": "Pfad", "key": "SHA-256"}
        for key, label in headings.items():
            tree.heading(key, text=label + (" ▼" if descending else " ▲") if key == column else label)
        items = list(tree.get_children())
        def sort_key(item: str) -> int | str:
            if column == "#0":
                return len(self.row_entries[tree][item][1].matched_criteria)
            value = tree.set(item, column)
            return int(value) if column == "list" else value.casefold()
        items.sort(key=sort_key, reverse=descending)
        for position, item in enumerate(items):
            tree.move(item, "", position)

    def _open_path(self, event: tk.Event, tree: ttk.Treeview) -> None:
        if tree.identify_region(event.x, event.y) != "cell" or tree.identify_column(event.x) != "#3":
            return
        item = tree.identify_row(event.y)
        if not item or item not in self.row_entries[tree]:
            return
        owner, entry = self.row_entries[tree][item]
        paths = [entry.path]
        if tree is self.trees[2]:
            counterpart = next((other.path for other_owner, other in self.row_entries[tree].values()
                                if other_owner != owner and other.key == entry.key), None)
            if counterpart and counterpart != entry.path:
                paths.append(counterpart)
        for path in paths:
            if not os.path.exists(path):
                messagebox.showwarning("Datei fehlt", f"Datei nicht gefunden:\n{path}")
                continue
            try:
                subprocess.Popen(["explorer.exe", "/select,", path])
            except OSError as exc:
                messagebox.showerror("Explorer", f"Explorer konnte nicht geöffnet werden:\n{exc}")

    def _active_rows(self) -> list[tuple[str, ...]]:
        tree = self.trees[self.notebook.index(self.notebook.select())]
        return [tuple(str(value) for value in tree.item(item, "values")) for item in tree.get_children()]

    def _copy(self) -> None:
        rows = self._active_rows()
        if rows:
            self.clipboard_clear()
            self.clipboard_append("\n".join("\t".join(row) for row in rows))

    def _save_csv(self) -> None:
        rows = self._active_rows()
        if not rows:
            messagebox.showinfo("Leer", "Keine Daten zum Speichern vorhanden.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV-Dateien", "*.csv")], title="CSV speichern")
        if path:
            try:
                with open(path, "w", newline="", encoding="utf-8-sig") as target:
                    writer = csv.writer(target, delimiter=";")
                    writer.writerow(("Liste", "Dateiname", "Pfad", "SHA-256"))
                    writer.writerows(rows)
                messagebox.showinfo("Gespeichert", f"CSV gespeichert:\n{path}")
            except OSError as exc:
                messagebox.showerror("Fehler", f"CSV konnte nicht gespeichert werden:\n{exc}")

    def _copy_files(self) -> None:
        index = self.notebook.index(self.notebook.select())
        if index == 2 or self.comparison is None:
            messagebox.showinfo("Hinweis", "Bitte einen 'Nur in Liste'-Tab auswählen.")
            return
        entries = self.comparison.unique[index]
        if not entries:
            messagebox.showinfo("Hinweis", "Keine fehlenden Dateien vorhanden.")
            return
        destination = filedialog.askdirectory(title=f"Zielordner für Dateien aus Liste {index + 1} wählen")
        if not destination:
            return
        if not messagebox.askyesno("Bestätigung", f"{len(entries)} Datei(en) nach\n{destination}\nkopieren?"):
            return
        copied = 0
        errors: list[str] = []
        for entry in entries:
            target = os.path.join(destination, os.path.basename(entry.path))
            if os.path.exists(target):
                errors.append(f"{target}: Zieldatei existiert bereits")
                continue
            try:
                shutil.copy2(entry.path, target)
                copied += 1
            except OSError as exc:
                errors.append(f"{entry.path}: {exc}")
        if errors:
            messagebox.showwarning("Teilerfolg", f"{copied} Datei(en) kopiert.\n\n" + "\n".join(errors[:10]))
        else:
            messagebox.showinfo("Fertig", f"{copied} Datei(en) kopiert.")


class DuplicateFinderApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.tk_widgets: list[tuple[tk.Widget, str]] = []
        root.title("Datei-Duplikat-Finder")
        root.minsize(1100, 700)
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        self.sha256_var = tk.BooleanVar(value=False)
        self.criteria = ("name",)
        self.size_prefilter = False
        self.sha256_threshold_bytes: int | None = None
        self.sha256_threshold_direction = "at_least"
        self.criterion_colors = dict(DEFAULT_CRITERION_COLORS)
        self.report_var = tk.BooleanVar(value=False)
        self.dark_var = tk.BooleanVar(value=False)
        menu = tk.Menu(root)
        comparison_menu = tk.Menu(menu, tearoff=False)
        comparison_menu.add_command(label="Vergleichskriterien …", command=self._show_criteria)
        comparison_menu.add_separator()
        comparison_menu.add_command(label="Vergleichen", command=self._run_compare)
        menu.add_cascade(label="Vergleich", menu=comparison_menu)
        root.configure(menu=menu)
        options = ttk.Frame(root)
        options.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(options, text="Vergleichskriterien …", command=self._show_criteria).pack(side="left", padx=8)
        self.criteria_label = ttk.Label(options, text="Aktiv: Dateiname")
        self.criteria_label.pack(side="left", padx=8)
        ttk.Checkbutton(options, text="Bericht erstellen", variable=self.report_var).pack(side="left", padx=8)
        ttk.Checkbutton(options, text="Dunkelmodus", variable=self.dark_var, command=self._apply_theme).pack(side="left", padx=8)
        ttk.Button(options, text="Vergleichen", command=self._run_compare).pack(side="right", padx=8)

        main = ttk.PanedWindow(root, orient="vertical")
        main.grid(row=1, column=0, sticky="nsew", padx=6, pady=3)
        top = ttk.PanedWindow(main, orient="horizontal")
        main.add(top, weight=2)
        results_outer = ttk.LabelFrame(main, text="ERGEBNISSE")
        results_outer.columnconfigure(0, weight=1)
        results_outer.rowconfigure(0, weight=1)
        self.results = ResultsFrame(results_outer, self)
        self.results.grid(row=0, column=0, sticky="nsew")
        main.add(results_outer, weight=1)
        left = InputPanel(top, 1, self)
        center = ttk.Frame(top)
        ttk.Button(center, text="⇄\nSynchronisieren", command=self._show_sync).pack(expand=True, padx=5)
        right = InputPanel(top, 2, self)
        self.panels = (left, right)
        top.add(left, weight=1)
        top.add(center, weight=0)
        top.add(right, weight=1)

        self.status_var = tk.StringVar(value="Bereit")
        ttk.Label(root, textvariable=self.status_var, relief="sunken", anchor="w").grid(row=2, column=0, sticky="ew")
        self._apply_theme()

    def register_tk_widget(self, widget: tk.Widget, kind: str) -> None:
        self.tk_widgets.append((widget, kind))

    def set_status(self, value: str) -> None:
        self.status_var.set(value)
        self.root.update_idletasks()

    def _show_sync(self) -> None:
        roots = [[path for path in panel.paths if os.path.isdir(path)] for panel in self.panels]
        if not all(roots):
            messagebox.showinfo("Synchronisieren", "Bitte in beiden Listen mindestens einen Ordner laden.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Ordnerinhalte synchronisieren")
        dialog.geometry("850x650")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(dialog, text="Ordner mit ☑ werden samt Unterordnern in die jeweils andere Liste kopiert. "
                  "Vorhandene Dateien werden nicht überschrieben.", wraplength=800).grid(
            row=0, column=0, sticky="ew", padx=12, pady=10)
        trees_frame = ttk.Frame(dialog)
        trees_frame.grid(row=1, column=0, sticky="nsew", padx=10)
        trees_frame.rowconfigure(0, weight=1)
        trees_frame.columnconfigure(0, weight=1)
        trees_frame.columnconfigure(1, weight=1)
        selected: list[set[str]] = [set(), set()]
        root_vars: list[tk.StringVar] = []

        for index, panel in enumerate(self.panels):
            box = ttk.LabelFrame(trees_frame, text=f"Liste {index + 1}")
            box.grid(row=0, column=index, sticky="nsew", padx=5)
            box.columnconfigure(0, weight=1)
            box.rowconfigure(1, weight=1)
            root_var = tk.StringVar(value=roots[index][0])
            root_vars.append(root_var)
            picker = ttk.Combobox(box, values=roots[index], textvariable=root_var, state="readonly")
            picker.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
            tree = ttk.Treeview(box, show="tree", selectmode="none")
            tree.grid(row=1, column=0, sticky="nsew", padx=(5, 0), pady=5)
            scrollbar = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
            scrollbar.grid(row=1, column=1, sticky="ns", pady=5)
            tree.configure(yscrollcommand=scrollbar.set)
            item_paths: dict[str, str] = {}

            def fill(_event: object = None, *, n: int = index, widget: ttk.Treeview = tree,
                     mapping: dict[str, str] = item_paths, variable: tk.StringVar = root_var) -> None:
                selected[n].clear()
                widget.delete(*widget.get_children())
                mapping.clear()
                root_path = variable.get()
                folder_ids: dict[str, str] = {}
                folders = []
                for path in self.panels[n].snapshot.folders:
                    try:
                        if os.path.normcase(os.path.commonpath((root_path, path))) == os.path.normcase(root_path):
                            folders.append(path)
                    except ValueError:  # Different Windows drives.
                        pass
                for path in sorted(folders, key=lambda value: (value.count(os.sep), value.casefold())):
                    parent = folder_ids.get(os.path.dirname(path), "")
                    item = widget.insert(parent, "end", text="☐ " + (os.path.basename(path) or path), open=not parent)
                    folder_ids[path] = item
                    mapping[item] = path

            def toggle(event: tk.Event, *, n: int = index, widget: ttk.Treeview = tree,
                       mapping: dict[str, str] = item_paths) -> None:
                item = widget.identify_row(event.y)
                if not item or widget.identify_region(event.x, event.y) != "tree":
                    return
                if widget.identify_element(event.x, event.y) == "Treeitem.indicator":
                    return
                path = mapping[item]
                if path in selected[n]:
                    selected[n].remove(path)
                    mark = "☐ "
                else:
                    selected[n].add(path)
                    mark = "☑ "
                widget.item(item, text=mark + (os.path.basename(path) or path))

            picker.bind("<<ComboboxSelected>>", fill)
            tree.bind("<ButtonRelease-1>", toggle)
            fill()

        preview = tk.Text(dialog, height=9, wrap="none", state="disabled")
        preview.grid(row=2, column=0, sticky="ew", padx=15, pady=8)

        def calculate():
            try:
                plan = plan_sync((root_vars[0].get(), root_vars[1].get()),
                                 (selected[0], selected[1]))
            except ValueError as exc:
                messagebox.showerror("Synchronisieren", str(exc), parent=dialog)
                return None
            lines = [f"Neue Ordner: {sum(action.is_directory for action in plan.actions)}",
                     f"Neue Dateien: {sum(not action.is_directory for action in plan.actions)}",
                     f"Bereits vorhandene Dateien: {plan.existing_files}",
                     f"Pfadkonflikte: {len(plan.conflicts)}", ""]
            lines.extend(f"{action.source}  →  {action.target}" for action in plan.actions)
            lines.extend(f"Konflikt: {path}" for path in plan.conflicts)
            preview.configure(state="normal")
            preview.delete("1.0", "end")
            preview.insert("1.0", "\n".join(lines))
            preview.configure(state="disabled")
            return plan

        def execute() -> None:
            plan = calculate()
            if plan is None or not plan.actions:
                messagebox.showinfo("Synchronisieren", "Keine neuen Dateien oder Ordner ausgewählt.", parent=dialog)
                return
            count = sum(not action.is_directory for action in plan.actions)
            if not messagebox.askyesno("Synchronisieren", f"{count} neue Datei(en) und "
                                       f"{len(plan.actions) - count} Ordner kopieren?", parent=dialog):
                return
            folders, files, errors = apply_sync_plan(plan)
            for panel in self.panels:
                panel._rescan()
            self.set_status(f"Synchronisiert: {files} Dateien, {folders} Ordner; {len(errors)} Fehler")
            if errors:
                messagebox.showwarning("Teilerfolg", "\n".join(errors[:10]), parent=dialog)
            else:
                messagebox.showinfo("Fertig", f"{files} Dateien und {folders} Ordner kopiert.", parent=dialog)
            dialog.destroy()

        buttons = ttk.Frame(dialog)
        buttons.grid(row=3, column=0, sticky="e", padx=12, pady=8)
        ttk.Button(buttons, text="Vorschau", command=calculate).pack(side="left", padx=4)
        ttk.Button(buttons, text="Synchronisieren", command=execute).pack(side="left", padx=4)
        ttk.Button(buttons, text="Abbrechen", command=dialog.destroy).pack(side="left", padx=4)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())

    def _show_criteria(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Vergleichskriterien")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Dateien gelten als gleich, wenn alle ausgewählten Kriterien übereinstimmen.",
                  wraplength=480).pack(anchor="w", pady=(0, 8))
        choices = {key: tk.BooleanVar(value=key in self.criteria) for key in CRITERIA}
        colors = dict(self.criterion_colors)

        def color_button(parent: tk.Widget, key: str) -> None:
            swatch = tk.Label(parent, background=colors[key], width=2, relief="solid", borderwidth=1)
            swatch.pack(side="right", padx=(5, 0))
            def choose() -> None:
                chosen = colorchooser.askcolor(color=colors[key], parent=dialog, title="Kriterienfarbe wählen")[1]
                if chosen:
                    colors[key] = chosen
                    swatch.configure(background=chosen)
            ttk.Button(parent, text="Farbe …", command=choose).pack(side="right")

        for key, label in CRITERIA.items():
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=2)
            ttk.Checkbutton(row, text=label, variable=choices[key]).pack(side="left")
            color_button(row, key)
        ttk.Label(frame, text="Pfad = Pfad innerhalb des gewählten Ordners; Änderungsdatum = sekundengenau.",
                  wraplength=480).pack(anchor="w", pady=(5, 8))

        hash_var = tk.BooleanVar(value=self.sha256_var.get())
        prefilter_var = tk.BooleanVar(value=self.size_prefilter)
        threshold_var = tk.BooleanVar(value=self.sha256_threshold_bytes is not None)
        direction_var = tk.StringVar(value=self.sha256_threshold_direction)
        threshold_mib = tk.StringVar(value=str(self.sha256_threshold_bytes // (1024 * 1024))
                                     if self.sha256_threshold_bytes is not None else "10")
        hash_row = ttk.Frame(frame)
        hash_row.pack(fill="x", pady=(5, 2))
        hash_check = ttk.Checkbutton(hash_row, text="Dateiinhalt per SHA-256 vergleichen", variable=hash_var)
        hash_check.pack(side="left")
        color_button(hash_row, "sha256")
        prefilter_check = ttk.Checkbutton(frame, text="Vor SHA-256 zuerst Dateigröße prüfen (spart Hashes)",
                                         variable=prefilter_var)
        prefilter_check.pack(anchor="w", padx=18, pady=2)
        threshold_check = ttk.Checkbutton(frame, text="SHA-256 nach Dateigröße begrenzen:", variable=threshold_var)
        threshold_check.pack(anchor="w", padx=18, pady=2)
        threshold_entry = ttk.Entry(frame, textvariable=threshold_mib, width=10)
        threshold_entry.pack(anchor="w", padx=38)
        ttk.Label(frame, text="MiB (Grenzwert eingeschlossen)",
                  wraplength=460).pack(anchor="w", padx=38, pady=(0, 8))
        at_least_radio = ttk.Radiobutton(frame, text="SHA-256 ab dieser Größe (≥)",
                                         variable=direction_var, value="at_least")
        at_least_radio.pack(anchor="w", padx=38)
        at_most_radio = ttk.Radiobutton(frame, text="SHA-256 bis zu dieser Größe (≤)",
                                        variable=direction_var, value="at_most")
        at_most_radio.pack(anchor="w", padx=38, pady=(0, 3))
        ttk.Label(frame, text="Dateien außerhalb des gewählten Bereichs werden nur nach Größe und den übrigen Kriterien verglichen.",
                  wraplength=460).pack(anchor="w", padx=38, pady=(0, 8))

        def refresh(*_args: object) -> None:
            state = "normal" if hash_var.get() else "disabled"
            prefilter_check.configure(state=state)
            threshold_check.configure(state=state)
            threshold_state = "normal" if hash_var.get() and threshold_var.get() else "disabled"
            threshold_entry.configure(state=threshold_state)
            at_least_radio.configure(state=threshold_state)
            at_most_radio.configure(state=threshold_state)

        hash_var.trace_add("write", refresh)
        threshold_var.trace_add("write", refresh)
        refresh()

        def save() -> None:
            selected = tuple(key for key in CRITERIA if choices[key].get())
            try:
                threshold = None
                if hash_var.get() and threshold_var.get():
                    mib = int(threshold_mib.get())
                    if mib < 0:
                        raise ValueError("Der Schwellenwert muss mindestens 0 MiB betragen.")
                    threshold = mib * 1024 * 1024
                configured = CompareOptions(selected, hash_var.get(),
                                            hash_var.get() and prefilter_var.get(), threshold,
                                            direction_var.get())
            except ValueError as exc:
                messagebox.showerror("Ungültige Einstellung", str(exc), parent=dialog)
                return
            previous = self.results.comparison
            previous_options = (CompareOptions(self.criteria, self.sha256_var.get(),
                                               self.size_prefilter, self.sha256_threshold_bytes,
                                               self.sha256_threshold_direction))
            self.criteria = configured.criteria
            self.sha256_var.set(configured.sha256)
            self.size_prefilter = configured.size_prefilter
            self.sha256_threshold_bytes = configured.sha256_threshold_bytes
            self.sha256_threshold_direction = configured.sha256_threshold_direction
            self.criterion_colors = colors
            summary = ", ".join(CRITERIA[item] for item in self.criteria)
            if configured.sha256:
                summary += (", " if summary else "") + "SHA-256"
            self.criteria_label.configure(text="Aktiv: " + summary)
            if previous is not None and configured == previous_options:
                self.results.populate(previous)
            else:
                self.results.clear()
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(5, 0))
        ttk.Button(buttons, text="Übernehmen", command=save).pack(side="right", padx=3)
        ttk.Button(buttons, text="Abbrechen", command=dialog.destroy).pack(side="right", padx=3)
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.wait_visibility()
        dialog.focus_set()

    def _apply_theme(self) -> None:
        dark = self.dark_var.get()
        bg, surface, fg, selected = (
            ("#171c24", "#242c38", "#e8edf5", "#345276") if dark
            else ("#f3f6fa", "#ffffff", "#202733", "#cfe2fa")
        )
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", background=bg, foreground=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabelframe", background=bg, foreground=fg)
        style.configure("TLabelframe.Label", background=bg, foreground=fg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.map("TCheckbutton", background=[("active", bg)], foreground=[("active", fg)])
        style.configure("TButton", background=surface, foreground=fg)
        style.map("TButton", background=[("active", selected)], foreground=[("active", fg)])
        style.configure("Treeview", background=surface, fieldbackground=surface, foreground=fg)
        style.map("Treeview", background=[("selected", selected)], foreground=[("selected", fg)])
        style.configure("Treeview.Heading", background=bg, foreground=fg)
        style.configure("TNotebook", background=bg)
        style.configure("TNotebook.Tab", background=surface, foreground=fg)
        style.map("TNotebook.Tab", background=[("selected", selected), ("active", selected)], foreground=[("selected", fg)])
        self.root.configure(background=bg)
        for widget, kind in self.tk_widgets:
            if kind == "list":
                widget.configure(background=surface, foreground=fg, selectbackground=selected)
            else:
                widget.configure(background=selected, foreground=fg)

    def _run_compare(self) -> None:
        snapshots = tuple(panel.snapshot for panel in self.panels)
        if not any(snapshot.files for snapshot in snapshots):
            messagebox.showinfo("Hinweis", "Bitte zuerst Dateien oder Ordner in die Listen laden.")
            return
        options = CompareOptions(self.criteria, self.sha256_var.get(),
                                 self.size_prefilter, self.sha256_threshold_bytes,
                                 self.sha256_threshold_direction)
        use_sha256 = options.sha256
        self.set_status("Prüfe Dateien …" if use_sha256 else "Vergleiche Dateinamen …")

        def progress(done: int, total: int) -> None:
            if done == total or done % 25 == 0:
                self.set_status(f"SHA-256: {done} / {total} Dateien geprüft …")

        comparison = compare(snapshots, options=options, progress=progress if use_sha256 else None)
        self.results.populate(comparison)
        counts = "  |  ".join(f"Nur in Liste {index}: {len(entries)}" for index, entries in enumerate(comparison.unique, 1))
        self.set_status(f"{counts}  |  In beiden Listen: {len(comparison.shared)}  |  Lesefehler: {len(comparison.errors)}")
        if comparison.errors:
            details = "\n".join(comparison.errors[:5])
            messagebox.showwarning(
                "Lesefehler",
                f"{len(comparison.errors)} Datei(en) konnten nicht geprüft werden:\n\n{details}",
            )
        if self.report_var.get():
            path = filedialog.asksaveasfilename(
                title="Vergleichsbericht speichern", defaultextension=".html",
                filetypes=[("HTML-Bericht", "*.html"), ("Alle Dateien", "*.*")],
            )
            if path:
                try:
                    with open(path, "w", encoding="utf-8") as target:
                        target.write(make_html_report(comparison))
                    messagebox.showinfo("Gespeichert", f"Bericht gespeichert:\n{path}")
                except OSError as exc:
                    messagebox.showerror("Fehler", f"Bericht konnte nicht gespeichert werden:\n{exc}")


def _apply_icon(root: tk.Tk) -> None:
    try:
        root.iconbitmap(default=_resource(os.path.join("assets", "kirschke.ico")))
    except tk.TclError:
        pass
    try:
        image = tk.PhotoImage(file=_resource(os.path.join("assets", "favicon.png")))
        root.wm_iconphoto(True, image)
        root._app_icon = image
    except tk.TclError:
        pass


def main() -> None:
    root = TkinterDnD.Tk() if DND_AVAILABLE else tk.Tk()
    _apply_icon(root)
    DuplicateFinderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
