import os
import asyncio
import json
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pymysql
import pytest
import chromadb
from fastapi import HTTPException

from backend.pipeline.converters import Block, ConvertedDocument
from backend.pipeline.ingestor import ingest
from backend.pipeline.models import MemoryItem
from backend.pipeline import ingestor as ingestor_module
from backend.api.project import delete_project
from backend.api import project as project_module
from backend.api.upload import _process_upload_locked
from backend.api import health as health_api
from backend.api.suggestion import _suggestion_or_404
from backend.api.repository import _set_repo_status
from backend import quota as quota_module
from backend.quota import (
    abandon_reservation,
    cleanup_pending,
    cleanup_failed_reservation,
    finalize_document,
    fail_stale_document,
    processing_owned,
    reserve_document,
    transfer_document_to_cleanup,
)
from backend.startup import (
    ensure_schema_v9,
    ensure_schema_v10,
    recover_quota_tasks,
    recover_stale_tasks,
)
from backend.storage import write_reserved_file


def connection():
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ["DB_PORT"]),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def v8_connection():
    return pymysql.connect(
        host="127.0.0.1",
        port=int(os.environ["V8_DB_PORT"]),
        user="root",
        password=os.environ["DB_PASSWORD"],
        database=os.environ["V8_DB_NAME"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


def apply_v9_sql_to_v8():
    sql_path = Path(__file__).parents[3] / "backend" / "db" / "migrate_v9.sql"
    process_env = os.environ.copy()
    process_env["MYSQL_PWD"] = os.environ["DB_PASSWORD"]
    subprocess.run(
        [
            "mysql", "--protocol=tcp", "-h", "127.0.0.1",
            "-P", os.environ["V8_DB_PORT"], "-u", "root", os.environ["V8_DB_NAME"],
        ],
        input=sql_path.read_bytes(),
        env=process_env,
        check=True,
        capture_output=True,
    )


def reset_v8_schema():
    schema_path = Path(__file__).with_name("schema_v8.sql")
    database = os.environ["V8_DB_NAME"]
    process_env = os.environ.copy()
    process_env["MYSQL_PWD"] = os.environ["DB_PASSWORD"]
    sql = (
        f"DROP DATABASE IF EXISTS `{database}`; CREATE DATABASE `{database}`; USE `{database}`;\n".encode()
        + schema_path.read_bytes()
    )
    subprocess.run(
        [
            "mysql", "--protocol=tcp", "-h", "127.0.0.1",
            "-P", os.environ["V8_DB_PORT"], "-u", "root",
        ],
        input=sql,
        env=process_env,
        check=True,
        capture_output=True,
    )


@pytest.fixture(autouse=True)
def reset_database(monkeypatch, tmp_path):
    monkeypatch.setenv("PROJECT_STORAGE_QUOTA_BYTES", "10")
    monkeypatch.setenv("USER_STORAGE_QUOTA_BYTES", "15")
    monkeypatch.setenv("PROJECT_FILE_COUNT_QUOTA", "2")
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    conn = connection()
    try:
        with conn.cursor() as cursor:
            for table in (
                "storage_cleanup_pending",
                "upload_quota_reservations",
                "memory_sources",
                "memory_suggestions",
                "memory",
                "documents",
                "repositories",
                "project_members",
                "projects",
                "users",
            ):
                cursor.execute(f"DELETE FROM {table}")
            cursor.execute("INSERT INTO users(id,email,name) VALUES (1,'one@test','one'),(2,'two@test','two')")
            cursor.execute("INSERT INTO projects(id,name,owner_user_id) VALUES (1,'p1',1),(2,'p2',1)")
        conn.commit()
    finally:
        conn.close()
    ensure_schema_v9()


def scalar(sql, params=()):
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return next(iter(cursor.fetchone().values()))
    finally:
        conn.close()


def test_v9_is_idempotent_and_manifest_is_closed():
    ensure_schema_v9()
    ensure_schema_v9()
    assert scalar(
        "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()"
        " AND TABLE_NAME='documents' AND COLUMN_NAME IN"
        " ('size_bytes','uploaded_by','processing_token','lease_expires_at')"
    ) == 4
    assert scalar("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME IN ('upload_quota_reservations','storage_cleanup_pending')") == 2


def test_v10_views_follow_published_generation_and_allow_locking_reads():
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO repositories"
                " (id,project_id,provider,repository_url,branch,status,active_sync_run_id)"
                " VALUES (1,1,'github','https://github.com/o/r','main','indexed','run-a')"
            )
            cursor.execute(
                "INSERT INTO memory(project_id,repo_id,repo_sync_run_id,category,content)"
                " VALUES (1,1,'run-a','decision','generation A')"
            )
            generation_a = cursor.lastrowid
            cursor.execute(
                "INSERT INTO memory(project_id,repo_id,repo_sync_run_id,category,content)"
                " VALUES (1,1,'run-b','decision','generation B')"
            )
            generation_b = cursor.lastrowid
            cursor.execute(
                "INSERT INTO memory(project_id,category,content,superseded_by)"
                " VALUES (1,'decision','document decision',%s)",
                (generation_b,),
            )
            document_memory = cursor.lastrowid
            cursor.execute(
                "INSERT INTO memory_suggestions"
                " (project_id,memory_id,kind,evidence,rationale,confidence,status)"
                " VALUES (1,%s,'supersede',%s,'test','high','pending')",
                (
                    generation_a,
                    json.dumps(
                        {
                            "type": "supersede",
                            "superseding_memory_id": document_memory,
                        }
                    ),
                ),
            )
            suggestion_id = cursor.lastrowid
        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM published_memory WHERE project_id=1 ORDER BY id"
            )
            assert [row["id"] for row in cursor.fetchall()] == [
                generation_a,
                document_memory,
            ]
            cursor.execute(
                "SELECT id FROM active_memory WHERE project_id=1 ORDER BY id"
            )
            assert [row["id"] for row in cursor.fetchall()] == [
                generation_a,
                document_memory,
            ]
            cursor.execute(
                "SELECT id FROM active_memory WHERE id=%s FOR UPDATE",
                (document_memory,),
            )
            assert cursor.fetchone()["id"] == document_memory
            assert _suggestion_or_404(cursor, 1, suggestion_id)["id"] == suggestion_id
            cursor.execute(
                "UPDATE repositories SET active_sync_run_id='run-b' WHERE id=1"
            )
        conn.commit()

        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM active_memory WHERE project_id=1 ORDER BY id"
            )
            assert [row["id"] for row in cursor.fetchall()] == [generation_b]
    finally:
        conn.close()


def test_v10_publish_fence_switches_generation_and_retires_old_derivatives():
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO repositories"
                " (id,project_id,provider,repository_url,branch,status,"
                "  active_sync_run_id,current_sync_run_id)"
                " VALUES (1,1,'github','https://github.com/o/r','main',"
                " 'syncing','run-old','run-new')"
            )
            cursor.execute(
                "INSERT INTO memory(project_id,repo_id,repo_sync_run_id,category,content)"
                " VALUES (1,1,'run-old','decision','old generation')"
            )
            old_memory = cursor.lastrowid
            cursor.execute(
                "INSERT INTO memory(project_id,category,content,superseded_by)"
                " VALUES (1,'decision','published predecessor',%s)",
                (old_memory,),
            )
            predecessor = cursor.lastrowid
            cursor.execute(
                "INSERT INTO memory_suggestions"
                " (project_id,memory_id,kind,evidence,rationale,confidence,status)"
                " VALUES (1,%s,'supersede',%s,'test','high','pending')",
                (
                    old_memory,
                    json.dumps(
                        {
                            "type": "supersede",
                            "superseding_memory_id": predecessor,
                        }
                    ),
                ),
            )
            suggestion_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    published, previous = _set_repo_status(
        1,
        "run-new",
        "indexed",
        commit_sha="abc123",
        indexed_files=4,
        last_error=None,
    )
    assert published is True
    assert previous == "run-old"

    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT status,active_sync_run_id,current_sync_run_id,commit_sha"
                " FROM repositories WHERE id=1"
            )
            repository = cursor.fetchone()
            cursor.execute(
                "SELECT superseded_by FROM memory WHERE id=%s",
                (predecessor,),
            )
            predecessor_row = cursor.fetchone()
            cursor.execute(
                "SELECT status,resolved_at FROM memory_suggestions WHERE id=%s",
                (suggestion_id,),
            )
            suggestion = cursor.fetchone()
    finally:
        conn.close()

    assert repository == {
        "status": "indexed",
        "active_sync_run_id": "run-new",
        "current_sync_run_id": None,
        "commit_sha": "abc123",
    }
    assert predecessor_row["superseded_by"] is None
    assert suggestion["status"] == "rejected"
    assert suggestion["resolved_at"] is not None


def test_real_v8_upgrade_backfills_and_resumes_after_interruption(monkeypatch, tmp_path):
    reset_v8_schema()
    upload = tmp_path / "v8-uploads"
    project_one = upload / "1"
    project_two = upload / "2"
    project_one.mkdir(parents=True)
    project_two.mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep")
    unsafe = project_one / "unsafe.txt"
    unsafe.symlink_to(outside)
    physical = project_one / "physical.txt"
    failed = project_one / "failed.txt"
    ownerless = project_two / "ownerless.txt"
    physical.write_bytes(b"12345")
    failed.write_bytes(b"remove-me")
    ownerless.write_bytes(b"ownerless")

    conn = v8_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO users(id,email,name) VALUES (1,'legacy@test','legacy')")
            cursor.execute(
                "INSERT INTO projects(id,name,owner_user_id) VALUES"
                " (1,'owned',1),(2,'ownerless',NULL)"
            )
            cursor.execute(
                "INSERT INTO documents(project_id,filename,status,file_path) VALUES"
                " (1,'unsafe','uploaded',%s),(1,'physical','uploaded',%s),"
                " (1,'virtual','uploaded',NULL),(1,'failed','failed',%s),"
                " (2,'ownerless','uploaded',%s)",
                (str(unsafe), str(physical), str(failed), str(ownerless)),
            )
        conn.commit()
    finally:
        conn.close()

    apply_v9_sql_to_v8()
    monkeypatch.setenv("DB_HOST", "127.0.0.1")
    monkeypatch.setenv("DB_PORT", os.environ["V8_DB_PORT"])
    monkeypatch.setenv("DB_NAME", os.environ["V8_DB_NAME"])
    monkeypatch.setenv("UPLOAD_DIR", str(upload))

    with pytest.raises(ValueError):
        ensure_schema_v9()
    conn = v8_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS count FROM documents WHERE size_bytes IS NULL")
            assert cursor.fetchone()["count"] == 5
    finally:
        conn.close()
    assert outside.read_text() == "keep"

    unsafe.unlink()
    unsafe.write_bytes(b"safe")
    ensure_schema_v9()
    apply_v9_sql_to_v8()
    apply_v9_sql_to_v8()
    ensure_schema_v9()
    ensure_schema_v9()

    conn = v8_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT filename,size_bytes,uploaded_by,file_path FROM documents ORDER BY id"
            )
            rows = {row["filename"]: row for row in cursor.fetchall()}
            cursor.execute(
                "SELECT IS_NULLABLE FROM information_schema.COLUMNS"
                " WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents'"
                " AND COLUMN_NAME='size_bytes'"
            )
            assert cursor.fetchone()["IS_NULLABLE"] == "NO"
    finally:
        conn.close()
    assert rows["unsafe"]["size_bytes"] == 4
    assert rows["physical"]["size_bytes"] == 5
    assert rows["physical"]["uploaded_by"] == 1
    assert rows["virtual"]["size_bytes"] == 0
    assert rows["failed"]["size_bytes"] == 0 and rows["failed"]["file_path"] is None
    assert rows["ownerless"]["size_bytes"] == len(b"ownerless")
    assert rows["ownerless"]["uploaded_by"] is None
    assert not failed.exists()


def test_legacy_backfill_uses_real_file_size_owner_and_failed_cleanup(tmp_path):
    upload = tmp_path / "uploads" / "1"
    upload.mkdir(parents=True, exist_ok=True)
    physical = upload / "physical.txt"
    failed = upload / "failed.txt"
    physical.write_bytes(b"12345")
    failed.write_bytes(b"remove-me")
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("ALTER TABLE documents MODIFY size_bytes BIGINT UNSIGNED NULL")
            cursor.execute(
                "INSERT INTO documents(project_id,filename,status,file_path,size_bytes) VALUES"
                " (1,'physical','uploaded',%s,NULL),(1,'virtual','uploaded',NULL,NULL),"
                " (1,'failed','failed',%s,NULL)",
                (str(physical), str(failed)),
            )
        conn.commit()
    finally:
        conn.close()
    ensure_schema_v9()
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT filename,size_bytes,uploaded_by,file_path FROM documents ORDER BY id")
            rows = {row["filename"]: row for row in cursor.fetchall()}
    finally:
        conn.close()
    assert rows["physical"]["size_bytes"] == 5 and rows["physical"]["uploaded_by"] == 1
    assert rows["virtual"]["size_bytes"] == 0 and rows["virtual"]["uploaded_by"] == 1
    assert rows["failed"]["size_bytes"] == 0 and rows["failed"]["file_path"] is None
    assert not failed.exists()


def test_legacy_backfill_rejects_symlink_without_touching_target(tmp_path):
    upload = tmp_path / "uploads" / "1"
    upload.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "outside.txt"
    target.write_text("keep")
    link = upload / "link.txt"
    link.symlink_to(target)
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("ALTER TABLE documents MODIFY size_bytes BIGINT UNSIGNED NULL")
            cursor.execute(
                "INSERT INTO documents(project_id,filename,status,file_path,size_bytes)"
                " VALUES (1,'link','uploaded',%s,NULL)",
                (str(link),),
            )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(ValueError):
        ensure_schema_v9()
    assert target.read_text() == "keep"
    assert scalar("SELECT COUNT(*) FROM documents WHERE size_bytes IS NULL") == 1


def test_project_bytes_and_count_boundaries_are_atomic():
    first = reserve_document(1, 1, 9, "virtual")
    finalize_document(first["reservation_id"], "one.txt", "git")
    second = reserve_document(1, 1, 1, "virtual")
    finalize_document(second["reservation_id"], "two.txt", "git")
    with pytest.raises(HTTPException) as exc_info:
        reserve_document(1, 1, 1, "virtual")
    assert exc_info.value.status_code == 413
    assert exc_info.value.detail["code"] == "UPLOAD_QUOTA_EXCEEDED"
    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations") == 0
    assert scalar("SELECT COUNT(*) FROM documents") == 2


def test_user_quota_cannot_be_bypassed_with_multiple_projects():
    first = reserve_document(1, 1, 10, "virtual")
    finalize_document(first["reservation_id"], "one.txt", "git")
    second = reserve_document(2, 1, 5, "virtual")
    finalize_document(second["reservation_id"], "two.txt", "git")
    with pytest.raises(HTTPException) as exc_info:
        reserve_document(2, 1, 1, "virtual")
    assert exc_info.value.status_code == 413


def test_two_connections_serialize_same_user_quota():
    barrier = threading.Barrier(3)
    results = []

    def worker(project_id):
        barrier.wait()
        try:
            results.append(reserve_document(project_id, 1, 10, "virtual")["reservation_id"])
        except HTTPException as exc:
            results.append(exc.status_code)

    threads = [threading.Thread(target=worker, args=(project_id,)) for project_id in (1, 2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
    assert sorted(isinstance(value, str) for value in results) == [False, True]
    assert 413 in results
    assert scalar("SELECT COALESCE(SUM(size_bytes),0) FROM upload_quota_reservations") == 10


def test_two_users_serialize_on_same_project_quota_lock():
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO project_members(project_id,user_id,role) VALUES (1,2,'member')"
            )
        conn.commit()
    finally:
        conn.close()

    a_project_locked = threading.Event()
    release_a = threading.Event()
    b_user_locked = threading.Event()
    b_project_attempted = threading.Event()
    closed = {"quota-project-a": False, "quota-project-b": False}
    results = {}
    real_get_connection = quota_module.get_connection

    class LockTracingCursor:
        def __init__(self, inner, worker_name):
            self.inner = inner
            self.worker_name = worker_name

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def execute(self, sql, args=None):
            normalized = " ".join(sql.upper().split())
            if self.worker_name == "quota-project-b" and normalized.startswith(
                "SELECT ID FROM USERS WHERE ID=%S FOR UPDATE"
            ):
                result = self.inner.execute(sql, args)
                b_user_locked.set()
                return result
            if normalized.startswith("SELECT ID FROM PROJECTS WHERE ID=%S FOR UPDATE"):
                if self.worker_name == "quota-project-a":
                    result = self.inner.execute(sql, args)
                    a_project_locked.set()
                    if not release_a.wait(timeout=5):
                        raise TimeoutError("project lock barrier was not released")
                    return result
                if self.worker_name == "quota-project-b":
                    b_project_attempted.set()
            return self.inner.execute(sql, args)

    class LockTracingConnection:
        def __init__(self, inner, worker_name):
            self.inner = inner
            self.worker_name = worker_name

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def cursor(self, *args, **kwargs):
            return LockTracingCursor(self.inner.cursor(*args, **kwargs), self.worker_name)

        def close(self):
            self.inner.close()
            closed[self.worker_name] = True

    def controlled_connection():
        inner = real_get_connection()
        worker_name = threading.current_thread().name
        if worker_name in closed:
            return LockTracingConnection(inner, worker_name)
        return inner

    def reserve(user_id):
        try:
            results[user_id] = reserve_document(1, user_id, 6, "virtual")
        except BaseException as exc:
            results[user_id] = exc

    threads = [
        threading.Thread(target=reserve, args=(1,), name="quota-project-a"),
        threading.Thread(target=reserve, args=(2,), name="quota-project-b"),
    ]
    try:
        with patch.object(quota_module, "get_connection", side_effect=controlled_connection):
            threads[0].start()
            assert a_project_locked.wait(timeout=2)
            threads[1].start()
            assert b_user_locked.wait(timeout=2)
            assert b_project_attempted.wait(timeout=2)
            assert threads[1].is_alive()
            assert 2 not in results
            release_a.set()
            for thread in threads:
                thread.join(timeout=5)

        assert not any(thread.is_alive() for thread in threads)
        successful = [value for value in results.values() if isinstance(value, dict)]
        rejected = [value for value in results.values() if isinstance(value, HTTPException)]
        assert len(successful) == 1
        assert len(rejected) == 1
        assert rejected[0].status_code == 413
        assert rejected[0].detail["code"] == "UPLOAD_QUOTA_EXCEEDED"
        assert scalar(
            "SELECT COALESCE(SUM(size_bytes),0) FROM upload_quota_reservations"
            " WHERE project_id=1"
        ) == 6
        assert scalar(
            "SELECT COUNT(*) FROM upload_quota_reservations WHERE project_id=1"
        ) == 1
    finally:
        release_a.set()
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=5)
        for value in results.values():
            if isinstance(value, dict):
                abandon_reservation(value["reservation_id"])
        cleanup_pending()

    assert not any(thread.is_alive() for thread in threads)
    assert closed == {"quota-project-a": True, "quota-project-b": True}
    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations") == 0
    assert scalar("SELECT COUNT(*) FROM documents") == 0
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    upload_root = Path(os.environ["UPLOAD_DIR"])
    assert not upload_root.exists() or list(upload_root.rglob("*")) == []


def test_general_connection_waits_past_readiness_deadline_for_project_lock():
    lock_conn = connection()
    with lock_conn.cursor() as cursor:
        cursor.execute("SELECT id FROM projects WHERE id=1 FOR UPDATE")
        cursor.fetchone()
    result = []

    def reserve():
        try:
            result.append(reserve_document(1, 1, 1, "virtual"))
        except BaseException as exc:
            result.append(exc)

    thread = threading.Thread(target=reserve)
    thread.start()
    time.sleep(2.2)
    assert thread.is_alive()
    lock_conn.rollback()
    lock_conn.close()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert isinstance(result[0], dict)
    abandon_reservation(result[0]["reservation_id"])
    cleanup_pending()


def test_quota_recovery_runs_when_stale_watchdog_is_disabled(monkeypatch):
    reservation = reserve_document(1, 1, 2, "virtual")
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE upload_quota_reservations SET expires_at='2000-01-01'"
                " WHERE reservation_id=%s",
                (reservation["reservation_id"],),
            )
            cursor.execute(
                "INSERT INTO storage_cleanup_pending"
                " (cleanup_id,source_kind,source_id,user_id,project_id,size_bytes,count_units,needs_chroma)"
                " VALUES ('preexisting','reservation','old',1,1,2,1,0)"
            )
            cursor.execute(
                "INSERT INTO documents(project_id,filename,status,size_bytes,uploaded_by,processing_token,lease_expires_at)"
                " VALUES (1,'stale','processing',1,1,'stale-token','2000-01-01')"
            )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("BACKGROUND_TASK_STALE_MINUTES", "0")

    assert recover_quota_tasks()
    recover_stale_tasks()

    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations") == 0
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    assert scalar("SELECT COUNT(*) FROM documents WHERE filename='stale' AND status='processing'") == 1


def test_schema_probe_rejects_stale_active_memory_view():
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "CREATE OR REPLACE VIEW active_memory AS SELECT id,project_id FROM memory"
            )
        conn.commit()
    finally:
        conn.close()
    try:
        with pytest.raises(RuntimeError, match="schema manifest mismatch"):
            health_api._schema_probe()
    finally:
        ensure_schema_v10()
    health_api._schema_probe()


def test_expired_reservation_cannot_finalize_and_ledger_releases_after_cleanup():
    reservation = reserve_document(1, 1, 4, "virtual")
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE upload_quota_reservations SET expires_at=%s WHERE reservation_id=%s",
                (datetime(2000, 1, 1), reservation["reservation_id"]),
            )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(RuntimeError):
        finalize_document(reservation["reservation_id"], "late.txt", "git")
    abandon_reservation(reservation["reservation_id"])
    assert scalar("SELECT COUNT(*) FROM documents") == 0
    assert scalar("SELECT COALESCE(SUM(size_bytes),0) FROM storage_cleanup_pending") == 4
    cleanup_pending()
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0


def test_fenced_document_ingest_cannot_commit_with_stale_token():
    reservation = reserve_document(1, 1, 1, "virtual")
    document = finalize_document(reservation["reservation_id"], "fenced.txt", "git")
    with pytest.raises(RuntimeError, match="FENCE_LOST"):
        ingest(
            project_id=1,
            doc_id=document["doc_id"],
            items=[],
            raw_text="",
            source="fenced",
            date="",
            doc_type="git",
            processing_token="wrong-token",
        )
    assert scalar("SELECT COUNT(*) FROM documents WHERE status='indexed'") == 0


class BarrierCollection:
    def __init__(self, collection, barrier_point=None):
        self.collection = collection
        self.barrier_point = barrier_point
        self.entered = threading.Event()
        self.release = threading.Event()

    @staticmethod
    def _embeddings(ids):
        return [[float(index + 1), 0.5, 0.25] for index, _ in enumerate(ids)]

    def _wait(self, point):
        if self.barrier_point == point:
            self.entered.set()
            self.release.wait(timeout=5)

    def upsert(self, *, ids, documents, metadatas):
        self._wait("before_chroma")
        return self.collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=self._embeddings(ids),
        )

    def add(self, *, ids, documents, metadatas):
        result = self.collection.add(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=self._embeddings(ids),
        )
        self._wait("after_chroma")
        return result

    def __getattr__(self, name):
        return getattr(self.collection, name)


class CancelAfterAddCollection(BarrierCollection):
    def add(self, *, ids, documents, metadatas):
        super().add(ids=ids, documents=documents, metadatas=metadatas)
        raise asyncio.CancelledError()


def actual_chroma_collection(tmp_path, barrier_point=None):
    name = "task012b_fence"
    os.environ["CHROMA_COLLECTION_NAME"] = name
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    collection = client.get_or_create_collection(name, embedding_function=None)
    return BarrierCollection(collection, barrier_point)


def _run_real_ingest(document, collection, results):
    item = MemoryItem(category="issue", content="fenced integration item")
    try:
        with patch("backend.pipeline.ingestor.get_collection", return_value=collection), patch(
            "backend.retriever.memory_vector.get_collection", return_value=collection
        ):
            ingest(
                project_id=1,
                doc_id=document["doc_id"],
                items=[item],
                raw_text="actual chroma document",
                source="race.txt",
                date="",
                doc_type="git",
                processing_token=document["processing_token"],
            )
        results.append("indexed")
    except BaseException as exc:
        results.append(exc)


@pytest.mark.parametrize("barrier_point", ["before_chroma", "after_chroma"])
def test_actual_chroma_barrier_serializes_stale_recovery(tmp_path, barrier_point):
    reservation = reserve_document(1, 1, 1, "virtual")
    document = finalize_document(reservation["reservation_id"], "race.txt", "git")
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE documents SET lease_expires_at='2000-01-01' WHERE id=%s",
                (document["doc_id"],),
            )
        conn.commit()
    finally:
        conn.close()
    collection = actual_chroma_collection(tmp_path, barrier_point)
    ingest_results = []
    recovery_results = []
    ingest_thread = threading.Thread(
        target=_run_real_ingest,
        args=(document, collection, ingest_results),
    )
    ingest_thread.start()
    assert collection.entered.wait(timeout=3)

    def recover():
        try:
            fail_stale_document(document["doc_id"], document["processing_token"])
            recovery_results.append("done")
        except BaseException as exc:
            recovery_results.append(exc)

    recovery_thread = threading.Thread(target=recover)
    recovery_thread.start()
    time.sleep(0.1)
    assert recovery_thread.is_alive()
    collection.release.set()
    ingest_thread.join(timeout=5)
    recovery_thread.join(timeout=5)
    assert not ingest_thread.is_alive() and not recovery_thread.is_alive()
    assert ingest_results == ["indexed"]
    assert recovery_results == ["done"]
    assert scalar("SELECT COUNT(*) FROM documents WHERE id=%s AND status='indexed'", (document["doc_id"],)) == 1
    assert scalar("SELECT COUNT(*) FROM memory WHERE doc_id=%s", (document["doc_id"],)) == 1
    assert scalar("SELECT COUNT(*) FROM memory_sources WHERE doc_id=%s", (document["doc_id"],)) == 1
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    assert len(collection.get(where={"doc_id": document["doc_id"]})["ids"]) == 2


def test_stale_recovery_wins_before_real_ingest_and_leaves_no_artifacts(tmp_path):
    reservation = reserve_document(1, 1, 1, "virtual")
    document = finalize_document(reservation["reservation_id"], "stale-first.txt", "git")
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE documents SET lease_expires_at='2000-01-01' WHERE id=%s",
                (document["doc_id"],),
            )
        conn.commit()
    finally:
        conn.close()
    fail_stale_document(document["doc_id"], document["processing_token"])
    collection = actual_chroma_collection(tmp_path)
    results = []
    _run_real_ingest(document, collection, results)
    assert len(results) == 1 and isinstance(results[0], RuntimeError)
    assert scalar("SELECT COUNT(*) FROM documents WHERE id=%s AND status='failed'", (document["doc_id"],)) == 1
    assert scalar("SELECT COUNT(*) FROM memory WHERE doc_id=%s", (document["doc_id"],)) == 0
    assert collection.get(where={"doc_id": document["doc_id"]})["ids"] == []


def test_stale_recovery_after_real_ingest_commit_is_noop(tmp_path):
    reservation = reserve_document(1, 1, 1, "virtual")
    document = finalize_document(reservation["reservation_id"], "commit-first.txt", "git")
    collection = actual_chroma_collection(tmp_path)
    results = []
    _run_real_ingest(document, collection, results)
    assert results == ["indexed"]
    fail_stale_document(document["doc_id"], document["processing_token"])
    assert scalar("SELECT COUNT(*) FROM documents WHERE id=%s AND status='indexed'", (document["doc_id"],)) == 1
    assert len(collection.get(where={"doc_id": document["doc_id"]})["ids"]) == 2


def test_post_finalize_cancel_at_first_memory_insert_releases_lock_and_accounting():
    reservation = reserve_document(1, 1, 4, "physical", filename="cancel-insert.txt")
    write_reserved_file(reservation["temp_path"], reservation["target_path"], b"data")
    document = finalize_document(reservation["reservation_id"], "cancel-insert.txt", "meeting")
    real_get_connection = ingestor_module.get_connection
    document_locked = threading.Event()
    connection_closed = threading.Event()

    class CancellingCursor:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def execute(self, sql, args=None):
            normalized = " ".join(sql.upper().split())
            if normalized.startswith(
                "SELECT STATUS,PROCESSING_TOKEN FROM DOCUMENTS WHERE ID=%S FOR UPDATE"
            ):
                result = self.inner.execute(sql, args)
                document_locked.set()
                return result
            if normalized.startswith("INSERT INTO MEMORY"):
                assert document_locked.is_set()
                raise asyncio.CancelledError()
            return self.inner.execute(sql, args)

    class CancellingConnection:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def cursor(self, *args, **kwargs):
            return CancellingCursor(self.inner.cursor(*args, **kwargs))

        def close(self):
            self.inner.close()
            connection_closed.set()

    def controlled_connection():
        return CancellingConnection(real_get_connection())

    item = MemoryItem(category="issue", content="cancel at mysql insert")
    with patch("backend.api.upload.extract", return_value=[item]), patch.object(
        ingestor_module, "get_connection", side_effect=controlled_connection
    ):
        with pytest.raises(asyncio.CancelledError):
            _process_upload_locked(
                project_id=1,
                doc_id=document["doc_id"],
                old_doc_ids=[],
                document=ConvertedDocument(
                    source="cancel-insert.txt", format="text",
                    blocks=[Block(order=0, kind="paragraph",
                                  text="cancelled physical upload")],
                ),
                filename="cancel-insert.txt",
                date="",
                doc_type="meeting",
                file_path=document["file_path"],
                processing_token=document["processing_token"],
            )

    assert document_locked.is_set()
    assert connection_closed.is_set()
    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations") == 0
    assert scalar("SELECT COUNT(*) FROM documents WHERE status='processing'") == 0
    assert scalar(
        "SELECT COUNT(*) FROM documents"
        " WHERE id=%s AND status='failed' AND size_bytes=0 AND file_path IS NULL"
        " AND processing_token IS NULL",
        (document["doc_id"],),
    ) == 1
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    assert scalar("SELECT COUNT(*) FROM memory WHERE doc_id=%s", (document["doc_id"],)) == 0
    assert not os.path.exists(reservation["target_path"])


def test_post_finalize_cancel_after_actual_chroma_write_removes_partial_vectors(tmp_path):
    reservation = reserve_document(1, 1, 4, "physical", filename="cancel-chroma.txt")
    write_reserved_file(reservation["temp_path"], reservation["target_path"], b"data")
    document = finalize_document(reservation["reservation_id"], "cancel-chroma.txt", "meeting")
    base_collection = actual_chroma_collection(tmp_path)
    collection = CancelAfterAddCollection(base_collection.collection)
    item = MemoryItem(category="issue", content="cancel after chroma write")

    with patch("backend.api.upload.extract", return_value=[item]), patch(
        "backend.pipeline.ingestor.get_collection", return_value=collection
    ), patch("backend.retriever.memory_vector.get_collection", return_value=collection):
        with pytest.raises(asyncio.CancelledError):
            _process_upload_locked(
                project_id=1,
                doc_id=document["doc_id"],
                old_doc_ids=[],
                document=ConvertedDocument(
                    source="cancel-chroma.txt", format="text",
                    blocks=[Block(order=0, kind="paragraph",
                                  text="actual chroma cancellation")],
                ),
                filename="cancel-chroma.txt",
                date="",
                doc_type="meeting",
                file_path=document["file_path"],
                processing_token=document["processing_token"],
            )

    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations") == 0
    assert scalar("SELECT COUNT(*) FROM documents WHERE status='processing'") == 0
    assert scalar(
        "SELECT COUNT(*) FROM documents"
        " WHERE id=%s AND status='failed' AND size_bytes=0 AND file_path IS NULL",
        (document["doc_id"],),
    ) == 1
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    assert scalar("SELECT COUNT(*) FROM memory WHERE doc_id=%s", (document["doc_id"],)) == 0
    assert scalar("SELECT COUNT(*) FROM memory_sources WHERE doc_id=%s", (document["doc_id"],)) == 0
    assert collection.get(where={"doc_id": document["doc_id"]})["ids"] == []
    assert not os.path.exists(reservation["target_path"])


def test_document_to_ledger_transfer_never_undercounts():
    reservation = reserve_document(1, 1, 7, "virtual")
    document = finalize_document(reservation["reservation_id"], "failed.txt", "git")
    transfer_document_to_cleanup(document["doc_id"], "INGEST_FAILED")
    assert scalar("SELECT size_bytes FROM documents WHERE id=%s", (document["doc_id"],)) == 0
    assert scalar("SELECT size_bytes FROM storage_cleanup_pending") == 7
    cleanup_pending()
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0


def test_late_snapshot_cannot_recreate_cleaned_ledger():
    reservation = reserve_document(1, 1, 7, "virtual")
    document = finalize_document(reservation["reservation_id"], "late.txt", "git")
    snapshot_read = threading.Event()
    resume_late = threading.Event()
    errors = []
    real_get_connection = quota_module.get_connection
    wrapped = {"done": False}

    class PausingConnection:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def close(self):
            self.inner.close()
            snapshot_read.set()
            resume_late.wait(timeout=5)

    def controlled_connection():
        if threading.current_thread().name == "late-transfer" and not wrapped["done"]:
            wrapped["done"] = True
            return PausingConnection(real_get_connection())
        return real_get_connection()

    def late_transfer():
        try:
            transfer_document_to_cleanup(document["doc_id"], "LATE")
        except BaseException as exc:
            errors.append(exc)

    with patch.object(quota_module, "get_connection", side_effect=controlled_connection):
        thread = threading.Thread(target=late_transfer, name="late-transfer")
        thread.start()
        assert snapshot_read.wait(timeout=2)
        transfer_document_to_cleanup(document["doc_id"], "FIRST")
        cleanup_pending()
        assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
        resume_late.set()
        thread.join(timeout=5)
    assert not thread.is_alive()
    assert errors == []
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    assert scalar("SELECT size_bytes FROM documents WHERE id=%s", (document["doc_id"],)) == 0
    transfer_document_to_cleanup(document["doc_id"], "LATE_RETRY")
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0


def test_physical_expiry_and_cleanup_failure_keep_accounting(tmp_path):
    reservation = reserve_document(1, 1, 4, "physical", filename="physical.txt")
    write_reserved_file(reservation["temp_path"], reservation["target_path"], b"data")
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "UPDATE upload_quota_reservations SET expires_at='2000-01-01' WHERE reservation_id=%s",
                (reservation["reservation_id"],),
            )
        conn.commit()
    finally:
        conn.close()
    abandon_reservation(reservation["reservation_id"])
    with patch("backend.quota.delete_managed_file", side_effect=OSError("unlink failed")):
        cleanup_pending()
    assert scalar("SELECT size_bytes FROM storage_cleanup_pending") == 4
    assert os.path.exists(reservation["target_path"])
    cleanup_pending()
    assert not os.path.exists(reservation["target_path"])
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0


@pytest.mark.parametrize("failure_point", ["open", "partial_write", "fsync", "replace", "cancel"])
def test_physical_write_failures_converge_through_cleanup_ledger(failure_point):
    reservation = reserve_document(1, 1, 4, "physical", filename="failure.txt")
    real_open = os.open
    real_write = os.write
    write_calls = {"count": 0}

    def partial_then_fail(fd, data):
        write_calls["count"] += 1
        if write_calls["count"] == 1:
            return real_write(fd, bytes(data[:1]))
        raise OSError("partial write failed")

    target = {
        "open": ("backend.storage.os.open", OSError("open failed")),
        "partial_write": ("backend.storage.os.write", partial_then_fail),
        "fsync": ("backend.storage.os.fsync", OSError("fsync failed")),
        "replace": ("backend.storage.os.replace", OSError("rename failed")),
        "cancel": ("backend.storage.os.fsync", asyncio.CancelledError()),
    }[failure_point]
    side_effect = target[1]
    try:
        with patch(target[0], side_effect=side_effect):
            with pytest.raises(BaseException):
                write_reserved_file(
                    reservation["temp_path"], reservation["target_path"], b"data"
                )
    finally:
        cleanup_failed_reservation(reservation["reservation_id"])
    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations") == 0
    assert scalar("SELECT COUNT(*) FROM documents") == 0
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    assert not os.path.exists(reservation["temp_path"])
    assert not os.path.exists(reservation["target_path"])


@pytest.mark.parametrize("trigger_table", ["documents", "upload_quota_reservations"])
def test_finalize_statement_failure_rolls_back_and_cleans_physical_file(trigger_table):
    reservation = reserve_document(1, 1, 4, "physical", filename="finalize.txt")
    write_reserved_file(reservation["temp_path"], reservation["target_path"], b"data")
    trigger = f"task012b_fail_{trigger_table}"
    event = "INSERT" if trigger_table == "documents" else "DELETE"
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE TRIGGER {trigger} BEFORE {event} ON {trigger_table}"
                " FOR EACH ROW SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='injected failure'"
            )
        conn.commit()
    finally:
        conn.close()
    try:
        with pytest.raises(pymysql.MySQLError):
            finalize_document(reservation["reservation_id"], "finalize.txt", "meeting")
    finally:
        conn = connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"DROP TRIGGER IF EXISTS {trigger}")
            conn.commit()
        finally:
            conn.close()
        cleanup_failed_reservation(reservation["reservation_id"])
    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations") == 0
    assert scalar("SELECT COUNT(*) FROM documents") == 0
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    assert not os.path.exists(reservation["target_path"])


def test_finalize_recovers_when_commit_succeeds_but_acknowledgement_is_lost():
    reservation = reserve_document(1, 1, 1, "virtual")
    real_get_connection = quota_module.get_connection
    calls = {"count": 0}

    class LostCommitAckConnection:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def commit(self):
            self.inner.commit()
            raise pymysql.OperationalError(2013, "injected lost commit acknowledgement")

        def rollback(self):
            raise pymysql.OperationalError(2013, "connection already lost")

    def controlled_connection():
        calls["count"] += 1
        connection_value = real_get_connection()
        if calls["count"] == 2:
            return LostCommitAckConnection(connection_value)
        return connection_value

    with patch.object(quota_module, "get_connection", side_effect=controlled_connection):
        document = finalize_document(reservation["reservation_id"], "committed.txt", "git")
    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations") == 0
    assert scalar("SELECT COUNT(*) FROM documents WHERE id=%s AND status='processing'", (document["doc_id"],)) == 1
    assert document["processing_token"]


def test_finalize_commit_then_cancellation_propagates_after_cleanup():
    reservation = reserve_document(1, 1, 4, "physical", filename="cancelled.txt")
    write_reserved_file(reservation["temp_path"], reservation["target_path"], b"data")
    real_get_connection = quota_module.get_connection
    calls = {"count": 0}

    class CancelledCommitAckConnection:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def commit(self):
            self.inner.commit()
            raise asyncio.CancelledError()

        def rollback(self):
            raise pymysql.OperationalError(2013, "connection already cancelled")

    def controlled_connection():
        calls["count"] += 1
        connection_value = real_get_connection()
        if calls["count"] == 2:
            return CancelledCommitAckConnection(connection_value)
        return connection_value

    with patch.object(quota_module, "get_connection", side_effect=controlled_connection):
        with pytest.raises(asyncio.CancelledError):
            finalize_document(reservation["reservation_id"], "cancelled.txt", "meeting")

    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations") == 0
    assert scalar("SELECT COUNT(*) FROM documents WHERE status='processing'") == 0
    assert scalar("SELECT COUNT(*) FROM documents WHERE status='failed'") == 1
    assert scalar("SELECT COALESCE(SUM(size_bytes),0) FROM documents") == 0
    assert scalar("SELECT COUNT(*) FROM documents WHERE file_path IS NOT NULL") == 0
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    assert not os.path.exists(reservation["target_path"])


@pytest.mark.parametrize("cleanup_failure", ["oserror", "keyboard", "system", "cancel"])
def test_finalize_commit_cancellation_preserves_cleanup_base_exception_contract(cleanup_failure):
    reservation = reserve_document(1, 1, 1, "virtual")
    real_get_connection = quota_module.get_connection
    calls = {"count": 0}

    class CancelledCommitAckConnection:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def commit(self):
            self.inner.commit()
            raise asyncio.CancelledError("commit cancellation")

        def rollback(self):
            raise pymysql.OperationalError(2013, "connection already cancelled")

    def controlled_connection():
        calls["count"] += 1
        connection_value = real_get_connection()
        if calls["count"] == 2:
            return CancelledCommitAckConnection(connection_value)
        return connection_value

    cleanup_exc = {
        "oserror": OSError("cleanup unavailable"),
        "keyboard": KeyboardInterrupt("cleanup keyboard interrupt"),
        "system": SystemExit("cleanup system exit"),
        "cancel": asyncio.CancelledError("cleanup cancellation"),
    }[cleanup_failure]
    expected_type = {
        "oserror": asyncio.CancelledError,
        "keyboard": KeyboardInterrupt,
        "system": SystemExit,
        "cancel": asyncio.CancelledError,
    }[cleanup_failure]
    expected_message = {
        "oserror": "commit cancellation",
        "keyboard": "cleanup keyboard interrupt",
        "system": "cleanup system exit",
        "cancel": "cleanup cancellation",
    }[cleanup_failure]

    with patch.object(quota_module, "get_connection", side_effect=controlled_connection), patch.object(
        quota_module, "fail_document", side_effect=cleanup_exc
    ):
        with pytest.raises(expected_type) as exc_info:
            finalize_document(reservation["reservation_id"], "signal.txt", "git")

    assert str(exc_info.value) == expected_message
    document_id = scalar("SELECT id FROM documents WHERE status='processing'")
    quota_module.fail_document(document_id, "TEST_CLEANUP")
    assert scalar("SELECT COUNT(*) FROM documents WHERE status='processing'") == 0
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0


def test_processing_owned_zero_changed_row_fallback_is_deterministic():
    reservation = reserve_document(1, 1, 1, "virtual")
    document = finalize_document(reservation["reservation_id"], "lease.txt", "git")
    fixed_epoch = 1893456000
    real_get_connection = quota_module.get_connection
    update_rowcounts = []
    fallback_calls = []
    closed_connections = []

    setup_conn = real_get_connection()
    try:
        with setup_conn.cursor() as cursor:
            cursor.execute(f"SET timestamp={fixed_epoch}")
            cursor.execute(
                "UPDATE documents SET lease_expires_at=NOW()+INTERVAL 30 MINUTE WHERE id=%s",
                (document["doc_id"],),
            )
        setup_conn.commit()
    finally:
        setup_conn.close()

    class LeaseTracingCursor:
        def __init__(self, inner):
            self.inner = inner

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def execute(self, sql, args=None):
            result = self.inner.execute(sql, args)
            normalized = " ".join(sql.upper().split())
            if normalized.startswith("UPDATE DOCUMENTS SET LEASE_EXPIRES_AT=NOW()"):
                update_rowcounts.append(self.inner.rowcount)
            if normalized.startswith("SELECT 1 FROM DOCUMENTS") and normalized.endswith(
                "FOR UPDATE"
            ):
                fallback_calls.append(args)
            return result

    class LeaseTracingConnection:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def cursor(self, *args, **kwargs):
            return LeaseTracingCursor(self.inner.cursor(*args, **kwargs))

        def close(self):
            self.inner.close()
            closed_connections.append(True)

    def fixed_connection():
        inner = real_get_connection()
        with inner.cursor() as cursor:
            cursor.execute(f"SET timestamp={fixed_epoch}")
        return LeaseTracingConnection(inner)

    def set_status(status):
        conn = real_get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("UPDATE documents SET status=%s WHERE id=%s", (status, document["doc_id"]))
            conn.commit()
        finally:
            conn.close()

    with patch.object(quota_module, "get_connection", side_effect=fixed_connection):
        assert processing_owned(document["doc_id"], document["processing_token"], renew=True)
        assert not processing_owned(document["doc_id"], "wrong-token", renew=True)
        set_status("indexed")
        assert not processing_owned(document["doc_id"], document["processing_token"], renew=True)
        set_status("failed")
        assert not processing_owned(document["doc_id"], document["processing_token"], renew=True)

    assert update_rowcounts == [0, 0, 0, 0]
    assert len(fallback_calls) == 4
    assert len(closed_connections) == 4
    lock_check = real_get_connection()
    try:
        with lock_check.cursor() as cursor:
            cursor.execute(
                "SELECT id FROM documents WHERE id=%s FOR UPDATE NOWAIT",
                (document["doc_id"],),
            )
            assert cursor.fetchone()["id"] == document["doc_id"]
        lock_check.rollback()
    finally:
        lock_check.close()


def test_chroma_cleanup_failure_keeps_ledger_until_retry():
    reservation = reserve_document(1, 1, 3, "virtual")
    document = finalize_document(reservation["reservation_id"], "cleanup.txt", "git")
    transfer_document_to_cleanup(document["doc_id"], "FAILED")
    with patch("backend.quota._delete_doc_vectors", side_effect=OSError("chroma unavailable")):
        cleanup_pending()
    assert scalar("SELECT size_bytes FROM storage_cleanup_pending") == 3
    cleanup_pending()
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    assert scalar("SELECT size_bytes FROM documents WHERE id=%s", (document["doc_id"],)) == 0


def test_stale_recovery_waits_for_document_lock_and_cannot_revert_indexed_commit():
    reservation = reserve_document(1, 1, 1, "virtual")
    document = finalize_document(reservation["reservation_id"], "race.txt", "git")
    conn = connection()
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE documents SET lease_expires_at='2000-01-01' WHERE id=%s",
            (document["doc_id"],),
        )
    conn.commit()
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM documents WHERE id=%s FOR UPDATE", (document["doc_id"],))
        cursor.fetchone()
    started = threading.Event()

    def recover():
        started.set()
        fail_stale_document(document["doc_id"], document["processing_token"])

    thread = threading.Thread(target=recover)
    thread.start()
    started.wait(timeout=2)
    with conn.cursor() as cursor:
        cursor.execute(
            "UPDATE documents SET status='indexed',processing_token=NULL,lease_expires_at=NULL WHERE id=%s",
            (document["doc_id"],),
        )
    conn.commit()
    conn.close()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert scalar("SELECT COUNT(*) FROM documents WHERE id=%s AND status='indexed'", (document["doc_id"],)) == 1
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0


def test_project_delete_rejects_reservation_without_side_effects():
    reserve_document(1, 1, 1, "virtual")
    with patch("backend.api.project.require_project_access"):
        with pytest.raises(HTTPException) as exc_info:
            delete_project(1)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PROJECT_UPLOAD_IN_PROGRESS"
    assert scalar("SELECT COUNT(*) FROM projects WHERE id=1") == 1
    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations WHERE project_id=1") == 1


def test_project_delete_processing_probe_avoids_ingest_fk_deadlock(tmp_path):
    reservation = reserve_document(1, 1, 1, "virtual")
    document = finalize_document(reservation["reservation_id"], "deadlock.txt", "git")
    collection = actual_chroma_collection(tmp_path)
    ingest_before_memory = threading.Event()
    release_ingest = threading.Event()
    delete_project_locked = threading.Event()
    delete_probe_finished = threading.Event()
    ingest_results = []
    delete_results = []
    real_ingest_connection = ingestor_module.get_connection
    real_project_connection = project_module.get_connection

    class TracingCursor:
        def __init__(self, inner, worker_name):
            self.inner = inner
            self.worker_name = worker_name

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, *args):
            return self.inner.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def execute(self, sql, args=None):
            normalized = " ".join(sql.upper().split())
            if self.worker_name == "ingest-before-memory" and normalized.startswith(
                "INSERT INTO MEMORY"
            ):
                ingest_before_memory.set()
                if not release_ingest.wait(timeout=5):
                    raise TimeoutError("ingest barrier was not released")
            if self.worker_name == "delete-during-ingest" and normalized.startswith(
                "SELECT ID FROM PROJECTS WHERE ID=%S FOR UPDATE"
            ):
                result = self.inner.execute(sql, args)
                delete_project_locked.set()
                return result
            if self.worker_name == "delete-during-ingest" and normalized.startswith(
                "SELECT 1 FROM DOCUMENTS WHERE PROJECT_ID=%S AND STATUS='PROCESSING' LIMIT 1"
            ):
                result = self.inner.execute(sql, args)
                delete_probe_finished.set()
                return result
            return self.inner.execute(sql, args)

    class TracingConnection:
        def __init__(self, inner, worker_name):
            self.inner = inner
            self.worker_name = worker_name

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def cursor(self, *args, **kwargs):
            return TracingCursor(self.inner.cursor(*args, **kwargs), self.worker_name)

    def controlled_ingest_connection():
        return TracingConnection(real_ingest_connection(), threading.current_thread().name)

    def controlled_project_connection():
        return TracingConnection(real_project_connection(), threading.current_thread().name)

    def run_delete():
        try:
            delete_project(1)
            delete_results.append("deleted")
        except BaseException as exc:
            delete_results.append(exc)

    ingest_thread = threading.Thread(
        target=_run_real_ingest,
        args=(document, collection, ingest_results),
        name="ingest-before-memory",
    )
    delete_thread = threading.Thread(target=run_delete, name="delete-during-ingest")
    try:
        with patch.object(
            ingestor_module, "get_connection", side_effect=controlled_ingest_connection
        ), patch.object(
            project_module, "get_connection", side_effect=controlled_project_connection
        ), patch.object(project_module, "require_project_access"):
            ingest_thread.start()
            assert ingest_before_memory.wait(timeout=3)
            delete_thread.start()
            assert delete_project_locked.wait(timeout=3)
            assert delete_probe_finished.wait(timeout=3)
            delete_thread.join(timeout=3)
            assert not delete_thread.is_alive()
            assert len(delete_results) == 1
            assert isinstance(delete_results[0], HTTPException)
            assert delete_results[0].status_code == 409
            assert delete_results[0].detail["code"] == "PROJECT_UPLOAD_IN_PROGRESS"

            release_ingest.set()
            ingest_thread.join(timeout=5)
    finally:
        release_ingest.set()
        for thread in (ingest_thread, delete_thread):
            if thread.ident is not None:
                thread.join(timeout=5)

    assert not ingest_thread.is_alive() and not delete_thread.is_alive()
    assert ingest_results == ["indexed"]
    assert scalar("SELECT COUNT(*) FROM projects WHERE id=1") == 1
    assert scalar(
        "SELECT COUNT(*) FROM documents WHERE id=%s AND status='indexed'",
        (document["doc_id"],),
    ) == 1
    assert scalar("SELECT COUNT(*) FROM memory WHERE doc_id=%s", (document["doc_id"],)) == 1


def test_missing_reservation_directories_release_cleanup_and_quota():
    reservation = reserve_document(1, 1, 3, "physical", filename="missing-parent.txt")
    upload_root = Path(os.environ["UPLOAD_DIR"])
    assert not upload_root.exists()

    cleanup_failed_reservation(reservation["reservation_id"])

    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations") == 0
    assert scalar("SELECT COUNT(*) FROM storage_cleanup_pending") == 0
    assert scalar(
        "SELECT COALESCE(SUM(size_bytes),0) FROM upload_quota_reservations"
        " WHERE project_id=1"
    ) == 0
    assert not (upload_root / "1").exists()


def test_project_delete_converges_when_document_parent_is_already_missing():
    missing_file = Path(os.environ["UPLOAD_DIR"]) / "1" / "gone" / "document.txt"
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO documents"
                " (project_id,filename,doc_type,status,file_path,size_bytes,uploaded_by)"
                " VALUES (1,'missing.txt','meeting','indexed',%s,3,1)",
                (str(missing_file),),
            )
        conn.commit()
    finally:
        conn.close()

    with patch.object(project_module, "require_project_access"):
        delete_project(1)

    assert scalar("SELECT COUNT(*) FROM projects WHERE id=1") == 0
    assert scalar("SELECT COUNT(*) FROM documents WHERE project_id=1") == 0
    assert not missing_file.parent.exists()


def test_project_delete_waits_for_cleanup_ledger_then_converges():
    conn = connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO storage_cleanup_pending"
                " (cleanup_id,source_kind,source_id,user_id,project_id,document_id,file_path,size_bytes,count_units,needs_chroma)"
                " VALUES ('cleanup-1','reservation','gone',1,1,NULL,NULL,3,1,0)"
            )
        conn.commit()
    finally:
        conn.close()
    with patch("backend.api.project.require_project_access"):
        with pytest.raises(HTTPException) as exc_info:
            delete_project(1)
    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "PROJECT_STORAGE_CLEANUP_PENDING"
    assert scalar("SELECT COUNT(*) FROM projects WHERE id=1") == 1
    cleanup_pending()
    with patch("backend.api.project.require_project_access"):
        delete_project(1)
    assert scalar("SELECT COUNT(*) FROM projects WHERE id=1") == 0


def test_upload_commit_before_delete_converges_to_409():
    entered_commit = threading.Event()
    release_commit = threading.Event()
    real_get_connection = quota_module.get_connection
    results = {}

    class CommitBarrierConnection:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def commit(self):
            entered_commit.set()
            release_commit.wait(timeout=5)
            return self.inner.commit()

    def controlled_connection():
        if threading.current_thread().name == "upload-first":
            return CommitBarrierConnection(real_get_connection())
        return real_get_connection()

    def upload():
        try:
            results["upload"] = reserve_document(1, 1, 1, "virtual")
        except BaseException as exc:
            results["upload"] = exc

    def delete():
        try:
            delete_project(1)
            results["delete"] = "deleted"
        except BaseException as exc:
            results["delete"] = exc

    with patch.object(quota_module, "get_connection", side_effect=controlled_connection), patch(
        "backend.api.project.require_project_access"
    ):
        upload_thread = threading.Thread(target=upload, name="upload-first")
        upload_thread.start()
        assert entered_commit.wait(timeout=2)
        delete_thread = threading.Thread(target=delete)
        delete_thread.start()
        time.sleep(0.1)
        assert delete_thread.is_alive()
        release_commit.set()
        upload_thread.join(timeout=5)
        delete_thread.join(timeout=5)
    assert not upload_thread.is_alive() and not delete_thread.is_alive()
    assert isinstance(results["upload"], dict)
    assert isinstance(results["delete"], HTTPException)
    assert results["delete"].status_code == 409
    abandon_reservation(results["upload"]["reservation_id"])
    cleanup_pending()


def test_delete_lock_before_upload_converges_to_upload_404():
    delete_locked = threading.Event()
    release_delete = threading.Event()
    results = {}

    def blocked_chroma(_project_id, _has_data):
        delete_locked.set()
        release_delete.wait(timeout=5)

    def delete():
        try:
            delete_project(1)
            results["delete"] = "deleted"
        except BaseException as exc:
            results["delete"] = exc

    def upload():
        try:
            results["upload"] = reserve_document(1, 2, 1, "virtual")
        except BaseException as exc:
            results["upload"] = exc

    with patch("backend.api.project.require_project_access"), patch(
        "backend.api.project._delete_project_chroma", side_effect=blocked_chroma
    ):
        delete_thread = threading.Thread(target=delete)
        delete_thread.start()
        assert delete_locked.wait(timeout=2)
        upload_thread = threading.Thread(target=upload)
        upload_thread.start()
        time.sleep(0.1)
        assert upload_thread.is_alive()
        release_delete.set()
        delete_thread.join(timeout=5)
        upload_thread.join(timeout=5)
    assert not delete_thread.is_alive() and not upload_thread.is_alive()
    assert results["delete"] == "deleted"
    assert isinstance(results["upload"], HTTPException)
    assert results["upload"].status_code == 404
    assert scalar("SELECT COUNT(*) FROM projects WHERE id=1") == 0
    assert scalar("SELECT COUNT(*) FROM upload_quota_reservations WHERE project_id=1") == 0
