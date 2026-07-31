#!/usr/bin/env python3
"""Seed one isolated route-balanced evaluation corpus from frozen snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pymysql
from dotenv import load_dotenv
from pymysql.constants import CLIENT
from pymysql.cursors import DictCursor


CORPORA = ("modu", "csbot")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--corpus", required=True, choices=CORPORA)
    parser.add_argument("--db-host", default="127.0.0.1")
    parser.add_argument("--db-port", type=int, default=3316)
    parser.add_argument("--db-user", default="root")
    parser.add_argument("--db-password", default="eval")
    return parser.parse_args()


def database_name(corpus: str) -> str:
    return f"paim_route_eval_{corpus}"


def connect(args: argparse.Namespace, database: str | None = None, *, multi: bool = False):
    return pymysql.connect(
        host=args.db_host,
        port=args.db_port,
        user=args.db_user,
        password=args.db_password,
        database=database,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        client_flag=CLIENT.MULTI_STATEMENTS if multi else 0,
    )


def create_schema(repo: Path, args: argparse.Namespace, db_name: str) -> None:
    conn = connect(args)
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"CREATE DATABASE `{db_name}` CHARACTER SET utf8mb4")
        conn.commit()
    finally:
        conn.close()

    schema = (repo / "backend/db/schema.sql").read_text(encoding="utf-8")
    conn = connect(args, db_name, multi=True)
    try:
        with conn.cursor() as cursor:
            cursor.execute(schema)
            while cursor.nextset():
                pass
        conn.commit()
    finally:
        conn.close()


def seed_mysql(dataset_dir: Path, args: argparse.Namespace, db_name: str) -> list[dict]:
    rows = json.loads(
        (dataset_dir / "memory_snapshots" / f"{args.corpus}.json").read_text(encoding="utf-8")
    )
    overview = json.loads(
        (dataset_dir / "overview_snapshots" / f"{args.corpus}.json").read_text(encoding="utf-8")
    )
    source_paths = sorted((dataset_dir / "sources" / args.corpus).glob("*.md"))
    source_to_doc_id = {path.name: index for index, path in enumerate(source_paths, start=1)}

    conn = connect(args, db_name)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO projects (id, name) VALUES (%s, %s)",
                (1, "Modu" if args.corpus == "modu" else "CS-Bot"),
            )
            for source, doc_id in source_to_doc_id.items():
                cursor.execute(
                    "INSERT INTO documents"
                    " (id, project_id, filename, doc_type, status)"
                    " VALUES (%s, %s, %s, 'meeting', 'processed')",
                    (doc_id, 1, source),
                )

            vector_rows = []
            base_created_at = datetime(2026, 1, 1)
            for row in rows:
                doc_id = source_to_doc_id.get(row.get("source"))
                completion_status = "completed" if row.get("completed_at") else "unknown"
                completion_source = "legacy" if row.get("completed_at") else None
                cursor.execute(
                    "INSERT INTO memory"
                    " (id, project_id, doc_id, category, content, reason, topic, owner,"
                    " date, due_date, completed_at, completion_status,"
                    " completion_status_source, source, superseded_by, sort_order, created_at)"
                    " VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
                    " %s, NULL, %s, %s)",
                    (
                        row["id"],
                        doc_id,
                        row.get("category"),
                        row.get("content"),
                        row.get("reason"),
                        row.get("topic"),
                        row.get("owner"),
                        row.get("date"),
                        row.get("due_date"),
                        row.get("completed_at"),
                        completion_status,
                        completion_source,
                        row.get("source"),
                        row.get("sort_order"),
                        base_created_at + timedelta(seconds=int(row["id"])),
                    ),
                )
                if doc_id is not None:
                    cursor.execute(
                        "INSERT INTO memory_sources"
                        " (memory_id, source_kind, doc_id, source_type, source_path)"
                        " VALUES (%s, 'document', %s, 'meeting', %s)",
                        (row["id"], doc_id, row.get("source")),
                    )
                vector_rows.append({
                    **row,
                    "project_id": 1,
                    "doc_id": doc_id,
                    "repo_id": None,
                    "completion_status": completion_status,
                    "completion_status_source": completion_source,
                })

            cursor.execute(
                "INSERT INTO project_memory (project_id, summary) VALUES (1, %s)",
                (overview.get("project_memory") or "",),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return vector_rows


def seed_chroma(dataset_dir: Path, args: argparse.Namespace, vector_rows: list[dict]) -> dict:
    from backend.db.chroma import get_collection
    from backend.pipeline.ingestor import _split_text
    from backend.retriever.memory_vector import upsert_memory_vectors

    memory_count = upsert_memory_vectors(vector_rows)
    collection = get_collection()
    chunk_count = 0
    for doc_id, path in enumerate(
        sorted((dataset_dir / "sources" / args.corpus).glob("*.md")), start=1
    ):
        chunks = _split_text(path.read_text(encoding="utf-8"))
        source_hash = hashlib.md5(path.name.encode()).hexdigest()[:6]
        collection.upsert(
            ids=[f"doc{doc_id}_{source_hash}_chunk{i}" for i in range(len(chunks))],
            documents=chunks,
            metadatas=[{
                "project_id": 1,
                "doc_id": doc_id,
                "repo_id": -1,
                "source": path.name,
                "item_type": "document",
                "date": path.name[:10],
                "doc_type": "meeting",
                "source_kind": "document",
                "source_type": "meeting",
                "source_path": path.name,
                "source_ref": "",
                "source_url": "",
            } for _ in chunks],
        )
        chunk_count += len(chunks)
    return {"memory_vectors": memory_count, "document_chunks": chunk_count}


def main() -> int:
    args = parse_args()
    repo = Path(__file__).resolve().parents[1]
    dataset_dir = args.dataset_dir.resolve()
    state_dir = args.state_dir.resolve() / args.corpus
    if state_dir.exists():
        raise RuntimeError(f"state directory already exists: {state_dir}")
    state_dir.mkdir(parents=True)

    load_dotenv(repo / ".env")
    db_name = database_name(args.corpus)
    os.environ.update({
        "DB_HOST": args.db_host,
        "DB_PORT": str(args.db_port),
        "DB_USER": args.db_user,
        "DB_PASSWORD": args.db_password,
        "DB_NAME": db_name,
        "PAIM_AUTH_MODE": "dev",
        "CHROMA_PERSIST_DIR": str(state_dir / "chroma"),
    })
    os.environ.pop("DEV_USER_ID", None)
    sys.path.insert(0, str(repo))

    create_schema(repo, args, db_name)
    vector_rows = seed_mysql(dataset_dir, args, db_name)
    indexed = seed_chroma(dataset_dir, args, vector_rows)
    manifest = {
        "corpus": args.corpus,
        "database": db_name,
        "project_id": 1,
        "memory_rows": len(vector_rows),
        **indexed,
    }
    (state_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
