"""File scanning and comparison, independent of the Tk interface."""

from __future__ import annotations

import hashlib
import json
import os
import zipfile
from dataclasses import dataclass, replace
from typing import Callable, Literal
from xml.etree import ElementTree

CRITERIA = {
    "name": "Dateiname",
    "extension": "Dateiendung",
    "size": "Dateigröße",
    "mtime": "Änderungsdatum (sekundengenau)",
    "path": "Relativer Pfad",
    "author": "Bearbeiter/Autor (Office-Dateien)",
}


@dataclass(frozen=True)
class CompareOptions:
    criteria: tuple[str, ...] = ("name",)
    sha256: bool = False
    size_prefilter: bool = False
    sha256_threshold_bytes: int | None = None
    sha256_threshold_direction: Literal["at_least", "at_most"] = "at_least"

    def __post_init__(self) -> None:
        if not self.criteria and not self.sha256:
            raise ValueError("Mindestens ein Vergleichskriterium muss aktiv sein.")
        if len(set(self.criteria)) != len(self.criteria) or any(item not in CRITERIA for item in self.criteria):
            raise ValueError("Ungültige Vergleichskriterien.")
        if self.sha256_threshold_bytes is not None and (not self.sha256 or self.sha256_threshold_bytes < 0):
            raise ValueError("Der SHA-256-Schwellenwert ist ungültig.")
        if self.sha256_threshold_direction not in ("at_least", "at_most"):
            raise ValueError("Die SHA-256-Schwellenrichtung ist ungültig.")


@dataclass(frozen=True)
class Snapshot:
    roots: tuple[str, ...]
    files: tuple[str, ...]
    folders: tuple[str, ...]


@dataclass(frozen=True)
class FileResult:
    path: str
    key: str
    digest: str | None = None
    criterion_values: tuple[str, ...] = ()
    matched_criteria: tuple[str, ...] = ()


@dataclass(frozen=True)
class Comparison:
    snapshots: tuple[Snapshot, Snapshot]
    unique: tuple[tuple[FileResult, ...], tuple[FileResult, ...]]
    shared: tuple[tuple[int, FileResult], ...]
    errors: tuple[str, ...]
    options: CompareOptions
    hashed_files: int = 0

    @property
    def sha256(self) -> bool:
        return self.options.sha256


def scan_paths(paths: list[str]) -> Snapshot:
    roots: list[str] = []
    files: set[str] = set()
    folders: set[str] = set()
    seen: set[str] = set()
    for raw_path in paths:
        path = os.path.abspath(os.path.normpath(raw_path))
        normalized = os.path.normcase(path)
        if normalized in seen:
            continue
        seen.add(normalized)
        if os.path.isfile(path):
            roots.append(path)
            files.add(path)
        elif os.path.isdir(path):
            roots.append(path)
            for directory, dirnames, filenames in os.walk(path):
                dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
                folders.add(directory)
                for filename in filenames:
                    if not filename.startswith("."):
                        files.add(os.path.join(directory, filename))
    return Snapshot(tuple(roots), tuple(sorted(files)), tuple(sorted(folders)))


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _author(path: str) -> str:
    if os.path.splitext(path)[1].casefold() not in {".docx", ".xlsx", ".pptx", ".docm", ".xlsm", ".pptm"}:
        raise ValueError("Bearbeiter/Autor ist nur für Office-Dateien verfügbar")
    try:
        with zipfile.ZipFile(path) as archive:
            core = ElementTree.fromstring(archive.read("docProps/core.xml"))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ValueError("Office-Autor konnte nicht gelesen werden") from exc
    author = (core.findtext("{http://schemas.openxmlformats.org/package/2006/metadata/core-properties}lastModifiedBy")
              or core.findtext("{http://purl.org/dc/elements/1.1/}creator"))
    if not author or not author.strip():
        raise ValueError("Office-Autor ist nicht hinterlegt")
    return author.strip().casefold()


def _relative_path(path: str, roots: tuple[str, ...]) -> str:
    matching = []
    for root in roots:
        if os.path.isdir(root):
            try:
                if os.path.commonpath((path, root)) == root:
                    matching.append(root)
            except ValueError:  # Different Windows drives.
                pass
    root = max(matching, key=len) if matching else None
    value = os.path.relpath(path, root) if root else os.path.basename(path)
    return value.replace("\\", "/").casefold()


def _base_values(path: str, snapshot: Snapshot, options: CompareOptions, size: int | None, mtime: int | None) -> tuple[str, ...]:
    name = os.path.basename(path)
    values = {
        "name": lambda: name.casefold(),
        "extension": lambda: os.path.splitext(name)[1].casefold(),
        "size": lambda: str(size),
        "mtime": lambda: str(mtime // 1_000_000_000),
        "path": lambda: _relative_path(path, snapshot.roots),
        "author": lambda: _author(path),
    }
    return tuple(values[item]() for item in options.criteria)


def compare(
    snapshots: tuple[Snapshot, Snapshot],
    sha256: bool = False,
    progress: Callable[[int, int], None] | None = None,
    options: CompareOptions | None = None,
) -> Comparison:
    """A file is unique when its selected properties occur in exactly one list."""
    if len(snapshots) != 2:
        raise ValueError("Der Vergleich benötigt genau zwei Listen.")
    options = options or CompareOptions(criteria=() if sha256 else ("name",), sha256=sha256)
    errors: list[str] = []
    records: list[tuple[int, str, tuple[str, ...], int | None, bool]] = []
    need_stat = options.sha256_threshold_bytes is not None or options.size_prefilter or any(
        item in options.criteria for item in ("size", "mtime")
    )
    for index, snapshot in enumerate(snapshots):
        for path in snapshot.files:
            try:
                stat = os.stat(path) if need_stat else None
                size = stat.st_size if stat else None
                mtime = stat.st_mtime_ns if stat else None
                base = _base_values(path, snapshot, options, size, mtime)
                threshold = options.sha256_threshold_bytes
                hash_eligible = options.sha256 and (
                    threshold is None
                    or (size >= threshold if options.sha256_threshold_direction == "at_least" else size <= threshold)
                )
                records.append((index, path, base, size, hash_eligible))
            except (OSError, ValueError) as exc:
                errors.append(f"{path}: {exc}")

    # A size found in only one list cannot produce a cross-list hash match.
    candidate_owners: dict[tuple[tuple[str, ...], int], set[int]] = {}
    if options.sha256 and options.size_prefilter:
        for index, _, base, size, eligible in records:
            if eligible:
                candidate_owners.setdefault((base, size), set()).add(index)

    rows: list[list[FileResult]] = [[], []]
    digest_cache: dict[str, str] = {}
    hashed_files = 0
    total = len(records)
    for done, (index, path, base, size, eligible) in enumerate(records, 1):
        try:
            digest = None
            if eligible:
                if not options.size_prefilter or len(candidate_owners[(base, size)]) > 1:
                    digest = digest_cache.get(path)
                    if digest is None:
                        digest = file_sha256(path)
                        digest_cache[path] = digest
                        hashed_files += 1
            if not options.sha256:
                identity = base
            elif not eligible:
                identity = (*base, "size-only", str(size))
            elif options.size_prefilter:
                identity = (*base, "size+sha256", str(size), digest or f"unique:{index}:{path}")
            else:
                identity = (*base, "sha256", digest)
            key = (digest if not base and eligible and not options.size_prefilter
                   and options.sha256_threshold_bytes is None else
                   identity[0] if len(identity) == 1 else json.dumps(identity, ensure_ascii=False))
            rows[index].append(FileResult(path, key, digest, base))
        except OSError as exc:
            errors.append(f"{path}: {exc}")
        if progress:
            progress(done, total)

    owners: dict[str, set[int]] = {}
    criterion_owners: list[dict[str, set[int]]] = [{} for _ in options.criteria]
    digest_owners: dict[str, set[int]] = {}
    for index, entries in enumerate(rows):
        for entry in entries:
            owners.setdefault(entry.key, set()).add(index)
            for criterion_index, value in enumerate(entry.criterion_values):
                criterion_owners[criterion_index].setdefault(value, set()).add(index)
            if entry.digest is not None:
                digest_owners.setdefault(entry.digest, set()).add(index)
    for index, entries in enumerate(rows):
        rows[index] = [replace(entry, matched_criteria=(
            tuple(criterion for criterion_index, criterion in enumerate(options.criteria)
                  if len(criterion_owners[criterion_index][entry.criterion_values[criterion_index]]) > 1)
            + (("sha256",) if entry.digest is not None and len(digest_owners[entry.digest]) > 1 else ())
        )) for entry in entries]
    unique = tuple(
        tuple(entry for entry in entries if owners[entry.key] == {index})
        for index, entries in enumerate(rows)
    )
    shared = tuple(sorted(
        ((index, entry) for index, entries in enumerate(rows) for entry in entries if len(owners[entry.key]) > 1),
        key=lambda item: (item[1].key, item[0], item[1].path),
    ))
    return Comparison(snapshots, unique, shared, tuple(errors), options, hashed_files)
