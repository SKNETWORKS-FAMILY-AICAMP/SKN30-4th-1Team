"""음성 전사(STT) → Project Memory 계층.

회의 녹음을 전사하고, 그 결과를 기존 추출·적재 파이프라인에 연결한다.

계획서 기준 STT는 **스트레치 항목**이며, 화자 이름 자동 매핑은 명시적 후속 과제다.
제공자가 익명 화자 라벨을 주면 보존하지만 이름을 추측해 채우지 않는다.

사용 예:

    from backend.stt import transcribe, ingest_transcript

    transcript = transcribe("회의녹음.m4a", audio_bytes)
    summary = ingest_transcript(project_id=1, transcript=transcript, date="2026-07-28")
"""
from .base import (
    ErrorCode,
    Segment,
    Transcript,
    TranscriptionError,
    TranscriptionWarning,
    WarningCode,
)
from .pipeline import SOURCE_KIND, ingest_transcript, transcribe_and_ingest
from .providers import available as available_providers, diarizing_providers
from .transcriber import (
    MAX_AUDIO_BYTES,
    current_provider_name,
    is_supported,
    max_audio_bytes,
    supported_suffixes,
    supports_diarization,
    transcribe,
)

__all__ = [
    "ErrorCode",
    "MAX_AUDIO_BYTES",
    "SOURCE_KIND",
    "Segment",
    "Transcript",
    "TranscriptionError",
    "TranscriptionWarning",
    "WarningCode",
    "available_providers",
    "current_provider_name",
    "diarizing_providers",
    "ingest_transcript",
    "is_supported",
    "max_audio_bytes",
    "supported_suffixes",
    "supports_diarization",
    "transcribe",
    "transcribe_and_ingest",
]
