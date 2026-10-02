"""Plan and perform non-overwriting folder synchronization."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass


@dataclass(frozen=True)
class SyncAction:
    source: str
    target: str
    is_directory: bool


@dataclass(frozen=True)
class SyncPlan:
    actions: tuple[SyncAction, ...]
    existing_files: int
    conflicts: tuple[str, ...]


def _inside(path: str, root: str) -> bool:
    try:
        return os.path.normcase(os.path.commonpath((os.path.realpath(path), os.path.realpath(root)))) == os.path.normcase(os.path.realpath(root))
    except ValueError:
        return False


def plan_sync(roots: tuple[str, str], selected: tuple[set[str], set[str]]) -> SyncPlan:
    """Copy selected directory subtrees to the same relative paths in the other root."""
    if len(roots) != 2 or len(selected) != 2 or any(not os.path.isdir(root) for root in roots):
        raise ValueError("Bitte je Liste einen vorhandenen Ordner als Wurzel wählen.")
    directories: dict[str, SyncAction] = {}
    files: dict[str, SyncAction] = {}
    existing: set[str] = set()
    conflicts: set[str] = set()
    for index, folders in enumerate(selected):
        source_root, target_root = roots[index], roots[1 - index]
        for folder in folders:
            if not os.path.isdir(folder) or not _inside(folder, source_root):
                raise ValueError(f"Ordner liegt nicht innerhalb der gewählten Wurzel: {folder}")
            for directory, dirnames, filenames in os.walk(folder, followlinks=False):
                dirnames[:] = [name for name in dirnames if not name.startswith(".")
                               and not os.path.islink(os.path.join(directory, name))]
                target_directory = os.path.join(target_root, os.path.relpath(directory, source_root))
                if not _inside(target_directory, target_root):
                    raise ValueError(f"Ungültiger Zielpfad: {target_directory}")
                if os.path.lexists(target_directory):
                    if not os.path.isdir(target_directory):
                        conflicts.add(target_directory)
                else:
                    directories[target_directory] = SyncAction(directory, target_directory, True)
                for name in filenames:
                    source = os.path.join(directory, name)
                    if name.startswith(".") or os.path.islink(source):
                        continue
                    target = os.path.join(target_directory, name)
                    if os.path.lexists(target):
                        if os.path.isfile(target):
                            existing.add(target)
                        else:
                            conflicts.add(target)
                    elif target not in files:
                        files[target] = SyncAction(source, target, False)
    actions = tuple(sorted(directories.values(), key=lambda action: (action.target.count(os.sep), action.target)))
    actions += tuple(sorted(files.values(), key=lambda action: action.target))
    return SyncPlan(actions, len(existing), tuple(sorted(conflicts)))


def apply_sync_plan(plan: SyncPlan) -> tuple[int, int, tuple[str, ...]]:
    folders = files = 0
    errors: list[str] = []
    for action in plan.actions:
        try:
            if action.is_directory:
                os.makedirs(action.target, exist_ok=True)
                folders += 1
            else:
                os.makedirs(os.path.dirname(action.target), exist_ok=True)
                with open(action.source, "rb") as source, open(action.target, "xb") as target:
                    try:
                        shutil.copyfileobj(source, target)
                    except OSError:
                        target.close()
                        os.unlink(action.target)
                        raise
                shutil.copystat(action.source, action.target)
                files += 1
        except OSError as exc:
            errors.append(f"{action.target}: {exc}")
    return folders, files, tuple(errors)
