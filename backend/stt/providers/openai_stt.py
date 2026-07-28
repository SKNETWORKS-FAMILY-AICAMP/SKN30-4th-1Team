"""OpenAI 전사 제공자.

기본 제공자. 한국어 인식 품질이 좋고 SDK가 이미 의존성에 있어 추가 설치가 없다.
**화자 분리는 지원하지 않는다** — 발언자 구분이 필요하면 clova/google을 쓴다.
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional

from ..base import (
    ErrorCode,
    Transcript,
    TranscriptionError,
    TranscriptionWarning,
    WarningCode,
    assemble,
)

logger = logging.getLogger(__name__)

NAME = "openai"
SUPPORTED_SUFFIXES = frozenset({
    ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg", ".flac",
})
MAX_AUDIO_BYTES = 25 * 1024 * 1024
SUPPORTS_DIARIZATION = False

_DEFAULT_MODEL = "whisper-1"
_DEFAULT_TIMEOUT_SECONDS = 180.0

# 구간 신뢰도 판정 임계값. whisper는 구간마다 no_speech_prob(무음일 확률)과
# avg_logprob(평균 로그확률)을 준다. 잡음·음악 구간에서 그럴듯한 오인식이 나오므로,
# 확실히 낮은 구간은 사용자에게 알린다.
_NO_SPEECH_THRESHOLD = 0.6
_AVG_LOGPROB_THRESHOLD = -1.0

# 한국어 발화에 섞인 영어 기술 용어의 표기를 고정하기 위한 어휘 힌트.
# 프로젝트마다 다르므로 STT_VOCABULARY로 덮어쓸 수 있다.
_DEFAULT_VOCABULARY = (
    "FastAPI, ChromaDB, MySQL, Docker, Tauri, React, JWT, API, RAG, LLM, "
    "PostgreSQL, Redis, Kubernetes, CI/CD, PR, QA"
)


def _require_client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise TranscriptionError(
            ErrorCode.MISSING_DEPENDENCY,
            "음성 전사에 필요한 openai 패키지가 설치되어 있지 않습니다.",
        ) from exc

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise TranscriptionError(
            ErrorCode.MISSING_CREDENTIALS,
            "음성 전사에 필요한 OPENAI_API_KEY가 설정되어 있지 않습니다.",
        )
    return OpenAI(api_key=api_key)


def _read(raw, key, default=None):
    """SDK 버전에 따라 구간이 dict 또는 객체로 온다."""
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(raw, key, default)


def _segments_from_response(response) -> tuple[list[dict], list[TranscriptionWarning]]:
    warnings: list[TranscriptionWarning] = []
    raw_segments = getattr(response, "segments", None)

    if not raw_segments:
        text = (getattr(response, "text", "") or "").strip()
        if not text:
            return [], warnings
        warnings.append(TranscriptionWarning(
            WarningCode.NO_TIMESTAMPS,
            "구간별 시각 정보를 받지 못해 전체를 한 구간으로 처리했습니다.",
        ))
        return [{"text": text, "start": 0.0, "end": 0.0}], warnings

    segments: list[dict] = []
    low_confidence = 0
    for raw in raw_segments:
        text = _read(raw, "text", "") or ""
        no_speech = _read(raw, "no_speech_prob", None)
        avg_logprob = _read(raw, "avg_logprob", None)
        if (no_speech is not None and no_speech > _NO_SPEECH_THRESHOLD) or (
            avg_logprob is not None and avg_logprob < _AVG_LOGPROB_THRESHOLD
        ):
            low_confidence += 1
        segments.append({
            "text": text,
            "start": _read(raw, "start", 0.0) or 0.0,
            "end": _read(raw, "end", 0.0) or 0.0,
            "speaker": _read(raw, "speaker", None),
        })

    if low_confidence:
        warnings.append(TranscriptionWarning(
            WarningCode.LOW_CONFIDENCE,
            f"인식 신뢰도가 낮은 구간이 {low_confidence}개 있습니다. "
            "잡음이 섞였거나 발음이 불명확한 부분일 수 있으니 원본 확인을 권합니다.",
        ))
    return segments, warnings


def transcribe(
    filename: str,
    data: bytes,
    language: Optional[str] = None,
    model: Optional[str] = None,
) -> Transcript:
    client = _require_client()
    model = model or os.getenv("STT_MODEL", _DEFAULT_MODEL)

    audio = io.BytesIO(data)
    audio.name = Path(filename).name  # SDK가 확장자로 컨테이너를 판별한다

    request = {
        "model": model,
        "file": audio,
        "response_format": "verbose_json",  # 구간별 타임스탬프를 받기 위한 형식
        # 타임아웃을 명시하지 않으면 SDK 기본 10분이 걸려, 제공자가 멈췄을 때
        # 호출한 워커가 그만큼 점유된다.
        "timeout": float(os.getenv("STT_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)),
    }
    if language:
        request["language"] = language

    # 도메인 어휘 힌트. whisper는 한국어 발화 속 영어 기술 용어를 음차하는 경향이
    # 있어(실측: "ChromaDB" → "크로마 디비") 그대로 두면 키워드 검색이 어긋난다.
    # prompt에 용어를 넣어 표기를 고정한다.
    vocabulary = os.getenv("STT_VOCABULARY", _DEFAULT_VOCABULARY).strip()
    if vocabulary:
        request["prompt"] = vocabulary

    try:
        response = client.audio.transcriptions.create(**request)
    except Exception as exc:
        # 제공자 오류 원문에는 요청 세부(키 포함)가 섞일 수 있으므로 로그에만 남기고,
        # 사용자에게는 조치 가능한 문장만 전달한다.
        logger.warning("STT 전사 실패 source=%s model=%s", filename, model, exc_info=True)
        raise TranscriptionError(
            ErrorCode.PROVIDER_ERROR,
            "음성 전사에 실패했습니다. 파일이 손상되었거나 서비스가 일시적으로 "
            "불가능할 수 있습니다.",
            source=filename,
        ) from exc

    raw_segments, warnings = _segments_from_response(response)
    detected = getattr(response, "language", None)
    if not language and detected:
        warnings.append(TranscriptionWarning(
            WarningCode.LANGUAGE_GUESSED,
            f"언어를 지정하지 않아 '{detected}'로 추정해 전사했습니다.",
        ))

    return assemble(
        source=filename,
        raw_segments=raw_segments,
        provider=NAME,
        model=model,
        language=language or detected,
        duration=getattr(response, "duration", None),
        warnings=warnings,
    )
