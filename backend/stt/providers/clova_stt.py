"""NAVER CLOVA Speech 전사 제공자 (화자 분리 지원).

한국어 회의 녹음에 가장 적합한 선택지다.
- 화자 분리(diarization)를 지원해 발언자별로 구간이 나뉜다
- 긴 파일을 직접 업로드할 수 있어 OpenAI의 25MB 제약을 받지 않는다
- REST API라 새 패키지가 필요 없다(httpx는 openai가 이미 가져온다)

필요한 환경변수 (NAVER Cloud Platform 콘솔에서 발급)
- `CLOVA_SPEECH_INVOKE_URL` : 도메인별 호출 URL
- `CLOVA_SPEECH_SECRET`     : 도메인 시크릿 키

화자 분리로 얻는 라벨은 `화자 1`·`화자 2` 같은 **익명 식별자**다. 실제 이름 매핑은
계획서가 후속 과제로 미룬 항목이므로 여기서 추측하지 않는다.
"""
from __future__ import annotations

import json
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

NAME = "clova"
SUPPORTED_SUFFIXES = frozenset({
    ".mp3", ".mp4", ".m4a", ".wav", ".aac", ".ac3", ".ogg", ".flac", ".wma",
})
# CLOVA Speech는 대용량 파일을 받지만, 서버 메모리와 처리 시간을 감안해 상한을 둔다.
MAX_AUDIO_BYTES = 200 * 1024 * 1024
SUPPORTS_DIARIZATION = True

_DEFAULT_TIMEOUT_SECONDS = 600.0  # 긴 녹음을 다루므로 OpenAI보다 넉넉하게


def _credentials() -> tuple[str, str]:
    invoke_url = os.getenv("CLOVA_SPEECH_INVOKE_URL")
    secret = os.getenv("CLOVA_SPEECH_SECRET")
    if not invoke_url or not secret:
        raise TranscriptionError(
            ErrorCode.MISSING_CREDENTIALS,
            "CLOVA Speech 사용에 필요한 CLOVA_SPEECH_INVOKE_URL / "
            "CLOVA_SPEECH_SECRET이 설정되어 있지 않습니다.",
        )
    return invoke_url.rstrip("/"), secret


def _speaker_label(raw_speaker) -> Optional[str]:
    """CLOVA의 화자 정보를 사람이 읽는 라벨로 바꾼다.

    응답은 `{"label": "1", "name": "화자1"}` 형태거나 정수일 수 있다.
    실제 이름을 지어내지 않고 익명 식별자만 만든다.
    """
    if raw_speaker is None:
        return None
    if isinstance(raw_speaker, dict):
        name = raw_speaker.get("name") or raw_speaker.get("label")
        if name is None:
            return None
        raw_speaker = name
    label = str(raw_speaker).strip()
    if not label:
        return None
    return label if label.startswith("화자") else f"화자 {label}"


def _segments_from_payload(payload: dict) -> tuple[list[dict], list[TranscriptionWarning]]:
    warnings: list[TranscriptionWarning] = []
    raw_segments = payload.get("segments") or []

    if not raw_segments:
        text = (payload.get("text") or "").strip()
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
        confidence = raw.get("confidence")
        if isinstance(confidence, (int, float)) and confidence < 0.5:
            low_confidence += 1
        segments.append({
            "text": raw.get("text") or "",
            # CLOVA는 밀리초 단위로 준다.
            "start": (raw.get("start") or 0) / 1000.0,
            "end": (raw.get("end") or 0) / 1000.0,
            "speaker": _speaker_label(raw.get("speaker")),
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
    import httpx

    invoke_url, secret = _credentials()
    language = language or os.getenv("STT_LANGUAGE") or "ko-KR"

    params = {
        "language": language,
        "completion": "sync",
        # 화자 분리. speakerCountMin/Max를 지정하지 않으면 CLOVA가 자동 추정한다.
        "diarization": {"enable": True},
        "wordAlignment": False,
        "fullText": True,
    }
    speaker_count = os.getenv("CLOVA_SPEAKER_COUNT")
    if speaker_count and speaker_count.isdigit():
        params["diarization"].update({
            "speakerCountMin": int(speaker_count),
            "speakerCountMax": int(speaker_count),
        })

    timeout = float(os.getenv("STT_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
    try:
        response = httpx.post(
            f"{invoke_url}/recognizer/upload",
            headers={"X-CLOVASPEECH-API-KEY": secret},
            files={
                "media": (Path(filename).name, data),
                "params": (None, json.dumps(params), "application/json"),
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        # 응답 본문에 요청 세부가 섞일 수 있어 로그에만 남긴다.
        logger.warning("CLOVA 전사 실패 source=%s", filename, exc_info=True)
        raise TranscriptionError(
            ErrorCode.PROVIDER_ERROR,
            "음성 전사에 실패했습니다. 파일이 손상되었거나 서비스가 일시적으로 "
            "불가능할 수 있습니다.",
            source=filename,
        ) from exc

    if payload.get("result") not in (None, "COMPLETED"):
        raise TranscriptionError(
            ErrorCode.PROVIDER_ERROR,
            f"음성 전사가 완료되지 않았습니다(상태: {payload.get('result')}).",
            source=filename,
        )

    raw_segments, warnings = _segments_from_payload(payload)
    return assemble(
        source=filename,
        raw_segments=raw_segments,
        provider=NAME,
        model=model or "clova-speech",
        language=language,
        duration=None,
        warnings=warnings,
    )
