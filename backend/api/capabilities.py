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
    }
