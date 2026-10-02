from __future__ import annotations

from datetime import datetime, timezone

from comparison import CompareOptions, compare, scan_paths
from report import make_html_report


def test_filename_and_sha256_modes_across_two_lists(tmp_path):
    directories = [tmp_path / f"list {index}" for index in (1, 2)]
    for directory in directories:
        directory.mkdir()
    (directories[0] / "same.txt").write_text("alpha", encoding="utf-8")
    (directories[1] / "same.txt").write_text("beta", encoding="utf-8")
    (directories[1] / "different.txt").write_text("alpha", encoding="utf-8")
    snapshots = tuple(scan_paths([str(directory)]) for directory in directories)

    names = compare(snapshots)
    assert [len(entries) for entries in names.unique] == [0, 1]
    assert len(names.shared) == 2

    hashes = compare(snapshots, sha256=True)
    assert [len(entries) for entries in hashes.unique] == [0, 1]
    assert len(hashes.shared) == 2
    assert len(hashes.shared[0][1].key) == 64


def test_report_sections_and_escaped_paths(tmp_path):
    folder = tmp_path / "a & b"
    folder.mkdir()
    (folder / "unique & more.txt").write_text("sample", encoding="utf-8")
    snapshots = (scan_paths([str(folder)]), scan_paths([]))
    report = make_html_report(compare(snapshots, sha256=True), datetime(2026, 10, 1, tzinfo=timezone.utc))

    headings = [
        "Allgemeine Informationen", "Schnellüberblick der Ergebnisse",
        "Nur in Liste 1", "Nur in Liste 2",
        "Baumansichten der Verzeichnisse",
    ]
    assert [report.index(heading) for heading in headings] == sorted(report.index(heading) for heading in headings)
    assert "unique &amp; more.txt" in report
    assert "a &amp; b" in report
    assert "SHA-256" in report
    assert "<details>" in report
    assert "Liste 3" not in report


def test_size_prefilter_and_threshold(tmp_path, monkeypatch):
    import comparison as module

    folders = [tmp_path / f"list{number}" for number in (1, 2)]
    for folder in folders:
        folder.mkdir()
    (folders[0] / "a.txt").write_bytes(b"aaaa")
    (folders[1] / "b.txt").write_bytes(b"bbbb")
    (folders[1] / "c.txt").write_bytes(b"cccccc")
    snapshots = tuple(scan_paths([str(folder)]) for folder in folders)
    calls = []
    original = module.file_sha256

    def tracking(path):
        calls.append(path)
        return original(path)

    monkeypatch.setattr(module, "file_sha256", tracking)
    options = CompareOptions((), sha256=True, size_prefilter=True)
    result = compare(snapshots, options=options)
    assert result.hashed_files == 2  # The unique six-byte size needs no hash.
    assert len(calls) == 2
    assert [len(entries) for entries in result.unique] == [1, 2]

    calls.clear()
    options = CompareOptions((), sha256=True, sha256_threshold_bytes=5)
    result = compare(snapshots, options=options)
    assert result.hashed_files == 1
    assert len(result.shared) == 2  # Four-byte files are compared by size only.
    report = make_html_report(result)
    assert "ab 5 Byte" in report
    assert "Per SHA-256 geprüfte Dateien: 1" in report

    calls.clear()
    options = CompareOptions((), sha256=True, sha256_threshold_bytes=5,
                             sha256_threshold_direction="at_most")
    result = compare(snapshots, options=options)
    assert result.hashed_files == 2
    assert len(result.shared) == 0  # Equal-size, different-content files now get hashed.
    assert "bis 5 Byte" in make_html_report(result)

    options = CompareOptions((), sha256=True, sha256_threshold_bytes=4,
                             sha256_threshold_direction="at_most")
    assert compare(snapshots, options=options).hashed_files == 2  # Inclusive boundary.
    options = CompareOptions((), sha256=True, sha256_threshold_bytes=4,
                             sha256_threshold_direction="at_least")
    assert compare(snapshots, options=options).hashed_files == 3


def test_combined_criteria_and_office_author(tmp_path):
    import zipfile

    folders = [tmp_path / f"list{number}" for number in (1, 2)]
    for folder in folders:
        folder.mkdir()
    (folders[0] / "same.txt").write_bytes(b"abc")
    (folders[1] / "same.txt").write_bytes(b"abcd")
    snapshots = tuple(scan_paths([str(folder)]) for folder in folders)
    assert len(compare(snapshots, options=CompareOptions(("name",))).shared) == 2
    assert len(compare(snapshots, options=CompareOptions(("name", "size"))).shared) == 0

    for folder, author in zip(folders[:2], ("Ada", "ADA")):
        with zipfile.ZipFile(folder / "paper.docx", "w") as archive:
            archive.writestr("docProps/core.xml",
                             '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
                             'xmlns:dc="http://purl.org/dc/elements/1.1/">'
                             f"<dc:creator>{author}</dc:creator></cp:coreProperties>")
    snapshots = tuple(scan_paths([str(folder)]) for folder in folders)
    result = compare(snapshots, options=CompareOptions(("author",)))
    assert len(result.shared) == 2
    assert len(result.errors) == 2  # TXT files have no Office author.


def test_individual_criterion_matches_are_visible_for_partial_results(tmp_path):
    folders = [tmp_path / "a", tmp_path / "b"]
    for folder in folders:
        folder.mkdir()
    (folders[0] / "same.txt").write_bytes(b"alpha")
    (folders[1] / "same.txt").write_bytes(b"bravo")
    snapshots = tuple(scan_paths([str(folder)]) for folder in folders)
    result = compare(snapshots, options=CompareOptions(("name", "size"), sha256=True))
    assert not result.shared
    assert all(entry.matched_criteria == ("name", "size") for group in result.unique for entry in group)
