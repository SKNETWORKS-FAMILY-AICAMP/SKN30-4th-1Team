"""음성 전사기.

제공자를 갈아끼울 수 있게 얇은 경계만 두고, 기본 구현으로 OpenAI 전사 API를 쓴다.
OpenAI SDK는 이미 프로젝트 의존성에 있어 새 패키지를 추가하지 않는다.

전사는 네트워크·과금이 걸린 외부 호출이므로, 보내기 전에 형식·크기를 먼저 거른다.
"""
from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional

from .base import (
    ErrorCode,
    Transcript,
    TranscriptionError,
    TranscriptionWarning,
    WarningCode,
    assemble,
)

logger = logging.getLogger(__name__)

# OpenAI 전사 API가 받는 컨테이너. 여기 없는 확장자는 호출 전에 거른다.
SUPPORTED_SUFFIXES = frozenset({
    ".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg", ".flac",
})

# 제공자 업로드 상한(25 MB). 넘으면 호출해봐야 거절되므로 미리 막는다.
MAX_AUDIO_BYTES = 25 * 1024 * 1024

_DEFAULT_MODEL = "whisper-1"

# 전사 호출 타임아웃(초). SDK 기본값은 10분이라 제공자가 멈추면 워커가 그만큼 묶인다.
# 25MB 오디오도 통상 1~2분이면 끝나므로 넉넉하되 무한정은 아니게 잡는다.
_DEFAULT_TIMEOUT_SECONDS = 180.0


def supported_suffixes() -> frozenset[str]:
    return SUPPORTED_SUFFIXES


def is_supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in SUPPORTED_SUFFIXES


def _validate(filename: str, data: bytes) -> None:
    """외부 호출 전에 거를 수 있는 것은 전부 여기서 거른다."""
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise TranscriptionError(
            ErrorCode.UNSUPPORTED_FORMAT,
            "지원하지 않는 오디오 형식입니다. ("
            + " / ".join(sorted(SUPPORTED_SUFFIXES)) + ")",
            source=filename,
        )
    if not data:
        raise TranscriptionError(
            ErrorCode.EMPTY_AUDIO,
            "오디오 파일이 비어 있습니다.",
            source=filename,
        )
    if len(data) > MAX_AUDIO_BYTES:
        raise TranscriptionError(
            ErrorCode.FILE_TOO_LARGE,
            f"오디오 크기는 {MAX_AUDIO_BYTES // (1024 * 1024)} MB를 초과할 수 없습니다. "
            "긴 녹음은 나눠서 올려주세요.",
            source=filename,
        )


def _require_client():
    """OpenAI 클라이언트를 만든다. 키·SDK 부재를 각각 다른 코드로 구분한다."""
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


def _segments_from_response(response) -> tuple[list[dict], list[TranscriptionWarning]]:
    """제공자 응답에서 구간 목록을 뽑는다.

    타임스탬프를 못 받는 경우에도 전사 자체는 살린다 — 전문이 통째로 버려지는 것보다
    "시각 정보 없음" 경고와 함께 넘기는 편이 낫다.
    """
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
    for raw in raw_segments:
        # SDK 버전에 따라 객체 또는 dict로 온다.
        get = raw.get if isinstance(raw, dict) else lambda k, d=None: getattr(raw, k, d)
        segments.append({
            "text": get("text", "") or "",
            "start": get("start", 0.0) or 0.0,
            "end": get("end", 0.0) or 0.0,
            "speaker": get("speaker", None),
        })
    return segments, warnings


def transcribe(
    filename: str,
    data: bytes,
    language: Optional[str] = None,
    model: Optional[str] = None,
) -> Transcript:
    """오디오 바이트를 Transcript로 전사한다.

    language를 지정하지 않으면 제공자가 추정한다. 회의 녹음은 대개 한국어라
    STT_LANGUAGE 환경변수로 기본값을 고정해 두면 오인식이 줄어든다.
    """
    _validate(filename, data)
    client = _require_client()
    model = model or os.getenv("STT_MODEL", _DEFAULT_MODEL)
    language = language or os.getenv("STT_LANGUAGE") or None

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

    try:
        response = client.audio.transcriptions.create(**request)
    except Exception as exc:
        # 제공자 오류 원문에는 요청 세부가 섞일 수 있으므로 로그에만 남기고,
        # 사용자에게는 조치 가능한 문장만 전달한다.
        logger.warning("STT 전사 실패 source=%s model=%s", filename, model, exc_info=True)
        raise TranscriptionError(
            ErrorCode.PROVIDER_ERROR,
            "음성 전사에 실패했습니다. 파일이 손상되었거나 서비스가 일시적으로 "
            "불가능할 수 있습니다.",
            source=filename,
        ) from exc

    raw_segments, warnings = _segments_from_response(response)
    if not language and getattr(response, "language", None):
        warnings.append(TranscriptionWarning(
            WarningCode.LANGUAGE_GUESSED,
            f"언어를 지정하지 않아 '{response.language}'로 추정해 전사했습니다.",
        ))

    return assemble(
        source=filename,
        raw_segments=raw_segments,
        provider="openai",
        model=model,
        language=language or getattr(response, "language", None),
        duration=getattr(response, "duration", None),
        warnings=warnings,
    )
