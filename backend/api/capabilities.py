from fastapi import APIRouter

from ..document_content import (
    PROJECT_DOCUMENT_MAX_FILE_BYTES,
    QUERY_ATTACHMENT_MAX_FILE_BYTES,
    QUERY_ATTACHMENT_MAX_TOTAL_BYTES,
    supported_extensions,
)

router = APIRouter()


@router.get("/capabilities")
def get_capabilities():
    extensions = supported_extensions()
    return {
        "schema_version": 1,
        "project_documents": {
            "extensions": extensions,
            "max_file_bytes": PROJECT_DOCUMENT_MAX_FILE_BYTES,
        },
        "query_attachments": {
            "extensions": extensions,
            "max_file_bytes": QUERY_ATTACHMENT_MAX_FILE_BYTES,
            "max_total_bytes": QUERY_ATTACHMENT_MAX_TOTAL_BYTES,
        },
        # Additive v1 capability: old desktop clients ignore unknown fields,
        # while new clients can avoid the legacy server-backed session API.
        "desktop_chat": {
            "storage": "local_only",
            "server_persistence": False,
            "legacy_session_api": "deprecated",
        },
    }
