import os
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.storage import (
    UnsafeUploadPathError,
    delete_managed_file,
    ensure_upload_root_safe,
    reservation_paths,
    write_reserved_file,
)


def test_reserved_file_write_is_exclusive_fsynced_and_atomic(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    temp, target = reservation_paths(1, "reservation", "folder/file.txt")
    with patch("backend.storage.os.fsync", wraps=os.fsync) as fsync:
        write_reserved_file(str(temp), str(target), b"payload")
    assert target.read_bytes() == b"payload"
    assert not temp.exists()
    fsync.assert_called_once()


def test_reserved_file_does_not_overwrite_existing_temp(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    temp, target = reservation_paths(1, "reservation", "file.txt")
    temp.parent.mkdir(parents=True)
    temp.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        write_reserved_file(str(temp), str(target), b"new")
    assert temp.read_bytes() == b"existing"
    assert not target.exists()


def test_managed_delete_rejects_outside_path_and_symlink(tmp_path, monkeypatch):
    upload = tmp_path / "uploads"
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    monkeypatch.setenv("UPLOAD_DIR", str(upload))
    with pytest.raises(ValueError):
        delete_managed_file(str(outside), 1)
    link = upload / "1" / "link.txt"
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    with pytest.raises(ValueError):
        delete_managed_file(str(link), 1)
    assert outside.read_text() == "keep"


def test_managed_delete_treats_missing_ancestors_as_already_removed(tmp_path, monkeypatch):
    upload = tmp_path / "uploads"
    upload.mkdir()
    monkeypatch.setenv("UPLOAD_DIR", str(upload))

    missing_project = upload / "1" / "missing.txt"
    delete_managed_file(str(missing_project), 1)
    assert not (upload / "1").exists()

    project = upload / "1"
    project.mkdir()
    missing_pending = project / ".pending" / "reservation.tmp"
    delete_managed_file(str(missing_pending), 1)
    assert not (project / ".pending").exists()

    missing_nested_parent = project / "nested" / "document.txt"
    delete_managed_file(str(missing_nested_parent), 1)
    assert not (project / "nested").exists()


def test_upload_root_must_be_a_real_directory(tmp_path, monkeypatch):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "uploads"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("UPLOAD_DIR", str(link))

    with pytest.raises(UnsafeUploadPathError):
        ensure_upload_root_safe(scan_tree=True)


def test_upload_tree_scan_rejects_internal_symlink_without_removing_it(tmp_path, monkeypatch):
    upload = tmp_path / "uploads"
    upload.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    link = upload / "legacy-link"
    link.symlink_to(outside)
    monkeypatch.setenv("UPLOAD_DIR", str(upload))

    with pytest.raises(UnsafeUploadPathError):
        ensure_upload_root_safe(scan_tree=True)
    assert link.is_symlink()
    assert outside.read_text() == "keep"


def test_project_directory_symlink_blocks_write_and_delete(tmp_path, monkeypatch):
    upload = tmp_path / "uploads"
    outside = tmp_path / "outside"
    upload.mkdir()
    outside.mkdir()
    project = upload / "1"
    project.symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("UPLOAD_DIR", str(upload))
    temp, target = reservation_paths(1, "reservation", "file.txt")

    with pytest.raises(UnsafeUploadPathError):
        write_reserved_file(str(temp), str(target), b"payload")
    external = outside / "existing.txt"
    external.write_text("keep")
    with pytest.raises(UnsafeUploadPathError):
        delete_managed_file(str(project / "existing.txt"), 1)

    assert external.read_text() == "keep"
    assert project.is_symlink()


def test_pending_directory_symlink_blocks_write(tmp_path, monkeypatch):
    upload = tmp_path / "uploads"
    project = upload / "1"
    outside = tmp_path / "outside"
    project.mkdir(parents=True)
    outside.mkdir()
    (project / ".pending").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("UPLOAD_DIR", str(upload))
    temp, target = reservation_paths(1, "reservation", "file.txt")

    with pytest.raises(UnsafeUploadPathError):
        write_reserved_file(str(temp), str(target), b"payload")
    assert list(outside.iterdir()) == []
