import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..db.mysql import get_connection
from ..storage import delete_managed_file
from .auth import get_current_user_id, ensure_dev_user, require_project_access

router = APIRouter()
logger = logging.getLogger(__name__)


class ProjectCreate(BaseModel):
    name: str


class ProjectUpdate(BaseModel):
    name: str


def _delete_project_chroma(project_id: int, has_indexed_children: bool) -> None:
    """프로젝트에 속한 Chroma 벡터를 project_id 메타데이터로 한 번에 지운다."""
    if not has_indexed_children:
        return

    # get_collection()이 아니라 delete_from_existing_collection을 쓴다 — 전자는 임베딩
    # 클라이언트를 만들려고 OPENAI_API_KEY를 요구하는데, metadata 조건 삭제에는 임베딩이
    # 필요 없다. 키가 없거나 placeholder면 프로젝트 삭제가 통째로 500으로 실패했다.
    # (같은 이유로 quota.py의 문서 정리 경로는 이미 이 함수를 쓴다.)
    from ..db.chroma import delete_from_existing_collection

    delete_from_existing_collection(where={"project_id": project_id})


def _delete_project_files(project_id: int, document_rows: list[dict]) -> None:
    """documents.file_path에 기록된 원본 파일을 기존 storage 헬퍼로 삭제한다."""
    for row in document_rows:
        file_path = row.get("file_path")
        if file_path:
            delete_managed_file(file_path, project_id)


def _project_upload_users(project_id: int) -> set[int]:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT uploaded_by AS user_id FROM documents"
                " WHERE project_id=%s AND uploaded_by IS NOT NULL"
                " UNION SELECT user_id FROM upload_quota_reservations WHERE project_id=%s",
                (project_id, project_id),
            )
            return {int(row["user_id"]) for row in cursor.fetchall()}
    finally:
        conn.close()


def _delete_project_rows(cursor, project_id: int) -> None:
    """FK 제약을 피하도록 프로젝트 하위 MySQL row를 자식부터 삭제한다."""
    cursor.execute("DELETE FROM memory_suggestions WHERE project_id = %s", (project_id,))
    cursor.execute(
        "DELETE ms FROM memory_sources ms"
        " JOIN memory m ON ms.memory_id = m.id"
        " WHERE m.project_id = %s",
        (project_id,),
    )
    cursor.execute("DELETE FROM memory WHERE project_id = %s", (project_id,))
    cursor.execute(
        "DELETE FROM chat_messages WHERE session_id IN ("
        " SELECT id FROM chat_sessions WHERE project_id = %s"
        ")",
        (project_id,),
    )
    cursor.execute(
        "DELETE FROM chat_summaries WHERE session_id IN ("
        " SELECT id FROM chat_sessions WHERE project_id = %s"
        ")",
        (project_id,),
    )
    cursor.execute("DELETE FROM chat_sessions WHERE project_id = %s", (project_id,))
    cursor.execute("DELETE FROM project_memory WHERE project_id = %s", (project_id,))
    cursor.execute("DELETE FROM documents WHERE project_id = %s", (project_id,))
    cursor.execute("DELETE FROM repositories WHERE project_id = %s", (project_id,))
    cursor.execute("DELETE FROM project_members WHERE project_id = %s", (project_id,))
    cursor.execute("DELETE FROM projects WHERE id = %s", (project_id,))


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate):
    user_id = ensure_dev_user()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO projects (name, owner_user_id) VALUES (%s, %s)",
                (body.name, user_id),
            )
            project_id = cursor.lastrowid
            if user_id:
                # DEV_USER_ID 미설정(auth 없는 MVP 모드)이면 project_members 행 생략
                cursor.execute(
                    "INSERT INTO project_members (project_id, user_id, role) VALUES (%s, %s, 'owner')",
                    (project_id, user_id),
                )
        conn.commit()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, created_at FROM projects WHERE id = %s", (project_id,))
            return cursor.fetchone()
    finally:
        conn.close()


@router.get("/projects")
def list_projects():
    user_id = get_current_user_id()
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            if user_id is not None:
                # 인증 있음: 본인이 멤버로 등록된 프로젝트만 반환
                cursor.execute(
                    "SELECT p.* FROM projects p"
                    " JOIN project_members pm ON pm.project_id = p.id"
                    " WHERE pm.user_id = %s"
                    " ORDER BY p.created_at DESC",
                    (user_id,),
                )
            else:
                # 인증 없음(DEV 미설정): 전체 프로젝트 반환
                cursor.execute("SELECT * FROM projects ORDER BY created_at DESC")
            return cursor.fetchall()
    finally:
        conn.close()


@router.get("/projects/{project_id}")
def get_project(project_id: int):
    require_project_access(project_id)
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM projects WHERE id = %s", (project_id,))
            row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdate):
    require_project_access(project_id, min_role="member")
    next_name = body.name.strip()
    if not next_name:
        raise HTTPException(status_code=400, detail="Project name must not be empty")

    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id FROM projects WHERE id = %s", (project_id,))
            if not cursor.fetchone():
                raise HTTPException(status_code=404, detail="Project not found")
            cursor.execute("UPDATE projects SET name = %s WHERE id = %s", (next_name, project_id))
        conn.commit()
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, created_at FROM projects WHERE id = %s", (project_id,))
            return cursor.fetchone()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        logger.error(
            "project_update_failed",
            extra={"project_id": project_id, "code": "PROJECT_UPDATE_FAILED"},
        )
        raise HTTPException(status_code=500, detail="Project update failed")
    finally:
        conn.close()


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: int):
    # 프로젝트 삭제는 공유 멤버 전체의 데이터를 지우므로 owner 전용
    require_project_access(project_id, min_role="owner")
    user_ids = _project_upload_users(project_id)
    for _attempt in range(3):
        conn = get_connection()
        try:
            with conn.cursor() as cursor:
                for user_id in sorted(user_ids):
                    cursor.execute("SELECT id FROM users WHERE id=%s FOR UPDATE", (user_id,))
                    cursor.fetchone()
                cursor.execute("SELECT id FROM projects WHERE id=%s FOR UPDATE", (project_id,))
                if not cursor.fetchone():
                    raise HTTPException(status_code=404, detail="Project not found")
                # Document ingest owns the document row before inserting memory,
                # whose project FK then needs the project row. Waiting for every
                # document here would invert that order (project -> document) and
                # can deadlock. A consistent read sees the last committed
                # processing state without waiting for the ingest row lock.
                cursor.execute(
                    "SELECT 1 FROM documents"
                    " WHERE project_id=%s AND status='processing' LIMIT 1",
                    (project_id,),
                )
                if cursor.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "PROJECT_UPLOAD_IN_PROGRESS",
                            "message": "진행 중인 업로드가 있습니다.",
                        },
                    )
                cursor.execute(
                    "SELECT id,file_path,uploaded_by,status FROM documents"
                    " WHERE project_id=%s FOR UPDATE",
                    (project_id,),
                )
                document_rows = cursor.fetchall()
                cursor.execute(
                    "SELECT reservation_id,user_id FROM upload_quota_reservations"
                    " WHERE project_id=%s FOR UPDATE",
                    (project_id,),
                )
                reservations = cursor.fetchall()
                actual_users = {
                    int(row["uploaded_by"])
                    for row in document_rows
                    if row.get("uploaded_by") is not None
                } | {int(row["user_id"]) for row in reservations}
                if not actual_users.issubset(user_ids):
                    conn.rollback()
                    user_ids |= actual_users
                    continue
                cursor.execute(
                    "SELECT cleanup_id FROM storage_cleanup_pending"
                    " WHERE project_id=%s LIMIT 1 FOR UPDATE",
                    (project_id,),
                )
                if cursor.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "PROJECT_STORAGE_CLEANUP_PENDING",
                            "message": "저장소 정리 완료 후 프로젝트를 다시 삭제해주세요.",
                        },
                    )
                if reservations or any(row["status"] == "processing" for row in document_rows):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "PROJECT_UPLOAD_IN_PROGRESS",
                            "message": "진행 중인 업로드가 있습니다.",
                        },
                    )
                cursor.execute("SELECT id FROM repositories WHERE project_id=%s", (project_id,))
                repository_rows = cursor.fetchall()
                cursor.execute("SELECT id FROM memory WHERE project_id=%s LIMIT 1", (project_id,))
                memory_rows = cursor.fetchall()

                _delete_project_chroma(
                    project_id, bool(document_rows or repository_rows or memory_rows)
                )
                _delete_project_files(project_id, document_rows)
                _delete_project_rows(cursor, project_id)
            conn.commit()
            return
        except HTTPException:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            logger.error(
                "project_delete_failed",
                extra={"project_id": project_id, "code": "PROJECT_DELETE_FAILED"},
                # 원인 예외를 남긴다 — 없으면 500만 보이고 무엇이 터졌는지 알 수 없다.
                # 실제로 이 가드가 OPENAI_API_KEY 관련 RuntimeError를 통째로 삼키고 있었다.
                exc_info=True,
            )
            raise HTTPException(status_code=500, detail="Project delete failed")
        finally:
            conn.close()
    raise HTTPException(
        status_code=409,
        detail={"code": "PROJECT_UPLOAD_IN_PROGRESS", "message": "업로드 상태가 변경 중입니다."},
    )
