"""Create a self-contained HTML comparison report."""

from __future__ import annotations

import html
import os
from datetime import datetime

from comparison import CRITERIA, Comparison, Snapshot


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def _tree(snapshot: Snapshot, unique_paths: set[str], shared_paths: set[str]) -> str:
    folders = set(snapshot.folders)
    children: dict[str | None, list[str]] = {}
    for folder in folders:
        parent = os.path.dirname(folder)
        children.setdefault(parent if parent in folders else None, []).append(folder)
    files: dict[str | None, list[str]] = {}
    for path in snapshot.files:
        parent = os.path.dirname(path)
        files.setdefault(parent if parent in folders else None, []).append(path)

    def render(parent: str | None) -> str:
        parts = ["<ul>"]
        for folder in sorted(children.get(parent, []), key=str.casefold):
            parts.append(
                f"<li><details><summary>📁 {_escape(os.path.basename(folder) or folder)}"
                f" <small>{_escape(folder)}</small></summary>{render(folder)}</details></li>"
            )
        for path in sorted(files.get(parent, []), key=str.casefold):
            state = "nur hier" if path in unique_paths else "geteilt" if path in shared_paths else "nicht geprüft"
            parts.append(
                f"<li>📄 {_escape(os.path.basename(path))} "
                f"<small>{_escape(path)} · {_escape(state)}</small></li>"
            )
        parts.append("</ul>")
        return "".join(parts)

    return render(None)


def make_html_report(comparison: Comparison, created: datetime | None = None) -> str:
    created = created or datetime.now().astimezone()
    options = comparison.options
    criteria = ", ".join(CRITERIA[item] for item in options.criteria) or "keine Metadaten"
    sha_mode = "aktiv" if options.sha256 else "aus"
    size_filter = "aktiv" if options.sha256 and options.size_prefilter else "aus"
    threshold_value = options.sha256_threshold_bytes
    threshold_label = (f"{threshold_value // (1024 * 1024)} MiB"
                       if threshold_value is not None and threshold_value % (1024 * 1024) == 0
                       else f"{threshold_value} Byte")
    if options.sha256 and threshold_value is not None:
        if options.sha256_threshold_direction == "at_least":
            threshold = f"ab {threshold_label} (einschließlich); darunter nur Größe und übrige Kriterien"
        else:
            threshold = f"bis {threshold_label} (einschließlich); darüber nur Größe und übrige Kriterien"
    else:
        threshold = "aus; SHA-256 für alle Dateien"
    sections = [
        "<!doctype html><html lang='de'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        "<title>Vergleichsbericht</title>",
        "<style>body{font:15px/1.5 system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;"
        "color:#202733;background:#fff}h1,h2{color:#17365a}table{border-collapse:collapse;width:100%;margin:1rem 0}"
        "th,td{border:1px solid #c9d1da;padding:.45rem;text-align:left;vertical-align:top}"
        "th{background:#eaf0f7}td{overflow-wrap:anywhere}small{color:#58677a}ul{list-style:none;padding-left:1.3rem}"
        "li{margin:.25rem 0}summary{cursor:pointer}section{margin:2rem 0}"
        "@media(prefers-color-scheme:dark){body{color:#e7edf5;background:#171c24}h1,h2{color:#a8cfff}"
        "th{background:#283546}th,td{border-color:#48566a}small{color:#aebdd0}}</style></head><body>",
        "<h1>Vergleichsbericht</h1><section><h2>Allgemeine Informationen</h2>",
        f"<p>Erstellt: {_escape(created.strftime('%d.%m.%Y %H:%M:%S %Z'))}<br>"
        f"Kriterien (alle müssen übereinstimmen): {_escape(criteria)}<br>"
        f"SHA-256: {_escape(sha_mode)}<br>"
        f"Größenprüfung vor SHA-256: {_escape(size_filter)}<br>"
        f"SHA-256-Schwellenwert: {_escape(threshold if options.sha256 else 'aus')}<br>"
        f"Per SHA-256 geprüfte Dateien: {comparison.hashed_files}</p>",
        "<table><thead><tr><th>Liste</th><th>Ausgewählte Pfade</th><th>Dateien</th><th>Ordner</th></tr></thead><tbody>",
    ]
    for index, snapshot in enumerate(comparison.snapshots, 1):
        paths = "<br>".join(_escape(path) for path in snapshot.roots) or "–"
        sections.append(
            f"<tr><td>Liste {index}</td><td>{paths}</td><td>{len(snapshot.files)}</td>"
            f"<td>{len(snapshot.folders)}</td></tr>"
        )
    sections.append("</tbody></table></section><section><h2>Schnellüberblick der Ergebnisse</h2><ul>")
    for index, entries in enumerate(comparison.unique, 1):
        sections.append(f"<li>Nur in Liste {index}: {len(entries)} Dateien</li>")
    shared_keys = {entry.key for _, entry in comparison.shared}
    sections.append(f"<li>In beiden Listen: {len(shared_keys)} Vergleichsgruppen / {len(comparison.shared)} Dateien</li>")
    sections.append(f"<li>Lesefehler: {len(comparison.errors)}</li></ul></section>")

    for index, entries in enumerate(comparison.unique, 1):
        sections.append(f"<section><h2>Nur in Liste {index} ({len(entries)})</h2>")
        if entries:
            sections.append("<table><thead><tr><th>Dateiname</th><th>Pfad</th>")
            if comparison.sha256:
                sections.append("<th>SHA-256</th>")
            sections.append("</tr></thead><tbody>")
            for entry in entries:
                sections.append(
                    f"<tr><td>{_escape(os.path.basename(entry.path))}</td><td>{_escape(entry.path)}</td>"
                    + (f"<td>{_escape(entry.digest or 'nicht gehasht')}</td>" if comparison.sha256 else "") + "</tr>"
                )
            sections.append("</tbody></table>")
        else:
            sections.append("<p>Keine Dateien.</p>")
        sections.append("</section>")

    sections.append("<section><h2>Baumansichten der Verzeichnisse</h2>")
    for index, snapshot in enumerate(comparison.snapshots):
        sections.append(f"<h3>Liste {index + 1}</h3>")
        unique_paths = {entry.path for entry in comparison.unique[index]}
        shared_paths = {entry.path for owner, entry in comparison.shared if owner == index}
        sections.append(_tree(snapshot, unique_paths, shared_paths))
    sections.append("</section>")
    if comparison.errors:
        sections.append("<section><h2>Lesefehler</h2><ul>")
        sections.extend(f"<li>{_escape(error)}</li>" for error in comparison.errors)
        sections.append("</ul></section>")
    sections.append("</body></html>")
    return "".join(sections)
