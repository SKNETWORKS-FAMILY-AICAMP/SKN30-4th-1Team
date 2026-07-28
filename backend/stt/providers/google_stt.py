"""Google Cloud Speech-to-Text 전사 제공자 (화자 분리 지원).

REST(v1 `speech:recognize`)를 API 키로 호출해 새 패키지를 추가하지 않는다.

**중요한 제약**: 동기 `recognize`는 약 1분 이하 오디오만 받는다. 그보다 긴 회의
녹음은 Google이 비동기(`longrunningrecognize`) + GCS 업로드를 요구하므로, 여기서는
길이 초과를 명시적 오류로 되돌린다. 조용히 앞부분만 전사하면 회의록 절반이
사라진 줄 모르고 넘어간다. **긴 한국어 회의 녹음은 clova 제공자를 권장한다.**

필요한 환경변수
- `GOOGLE_STT_API_KEY` : Google Cloud 콘솔에서 발급한 API 키
"""
from __future__ import annotations

import base64
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

NAME = "google"
SUPPORTED_SUFFIXES = frozenset({".flac", ".wav", ".mp3", ".ogg", ".webm", ".m4a"})
# 동기 recognize의 실질 상한(약 1분). 인라인 오디오는 10MB 제한도 있다.
MAX_AUDIO_BYTES = 10 * 1024 * 1024
SUPPORTS_DIARIZATION = True

_ENDPOINT = "https://speech.googleapis.com/v1/speech:recognize"
_DEFAULT_TIMEOUT_SECONDS = 180.0

# 확장자 → Google encoding 힌트. 미지정이면 헤더에서 추론하게 둔다.
_ENCODINGS = {
    ".flac": "FLAC",
    ".wav": "LINEAR16",
    ".mp3": "MP3",
    ".ogg": "OGG_OPUS",
    ".webm": "WEBM_OPUS",
}


def _api_key() -> str:
    key = os.getenv("GOOGLE_STT_API_KEY")
    if not key:
        raise TranscriptionError(
            ErrorCode.MISSING_CREDENTIALS,
            "Google STT 사용에 필요한 GOOGLE_STT_API_KEY가 설정되어 있지 않습니다.",
        )
    return key


def _segments_from_payload(payload: dict) -> tuple[list[dict], list[TranscriptionWarning]]:
    """Google 응답을 구간 목록으로 바꾼다.

    화자 분리를 켜면 마지막 result에 단어별 speakerTag가 담긴다. 같은 화자가
    연속하는 단어를 하나의 구간으로 묶는다.
    """
    warnings: list[TranscriptionWarning] = []
    results = payload.get("results") or []
    if not results:
        return [], warnings

    # 화자 정보가 있는 마지막 result를 찾는다.
    words = []
    for result in results:
        alternatives = result.get("alternatives") or []
        if alternatives and alternatives[0].get("words"):
            words = alternatives[0]["words"]

    if not words:
        text = " ".join(
            (r.get("alternatives") or [{}])[0].get("transcript", "").strip()
            for r in results
        ).strip()
        if not text:
            return [], warnings
        warnings.append(TranscriptionWarning(
            WarningCode.NO_TIMESTAMPS,
            "구간별 시각 정보를 받지 못해 전체를 한 구간으로 처리했습니다.",
        ))
        return [{"text": text, "start": 0.0, "end": 0.0}], warnings

    def seconds(value) -> float:
        # Google은 "1.500s" 형태의 문자열로 준다.
        if value is None:
            return 0.0
        return float(str(value).rstrip("s") or 0.0)

    segments: list[dict] = []
    current: Optional[dict] = None
    for word in words:
        tag = word.get("speakerTag")
        speaker = f"화자 {tag}" if tag else None
        token = word.get("word", "")
        if current and current["speaker"] == speaker:
            current["text"] = f"{current['text']} {token}".strip()
            current["end"] = seconds(word.get("endTime"))
            continue
        if current:
            segments.append(current)
        current = {
            "text": token,
            "start": seconds(word.get("startTime")),
            "end": seconds(word.get("endTime")),
            "speaker": speaker,
        }
    if current:
        segments.append(current)
    return segments, warnings


def transcribe(
    filename: str,
    data: bytes,
    language: Optional[str] = None,
    model: Optional[str] = None,
) -> Transcript:
    import httpx

    key = _api_key()
    language = language or os.getenv("STT_LANGUAGE") or "ko-KR"

    config = {
        "languageCode": language,
        "enableAutomaticPunctuation": True,
        "enableWordTimeOffsets": True,
        "diarizationConfig": {
            "enableSpeakerDiarization": True,
            "minSpeakerCount": int(os.getenv("GOOGLE_MIN_SPEAKERS", "2")),
            "maxSpeakerCount": int(os.getenv("GOOGLE_MAX_SPEAKERS", "6")),
        },
    }
    encoding = _ENCODINGS.get(Path(filename).suffix.lower())
    if encoding:
        config["encoding"] = encoding
    if model:
        config["model"] = model

    timeout = float(os.getenv("STT_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS))
    try:
        response = httpx.post(
            _ENDPOINT,
            params={"key": key},
            json={"config": config, "audio": {"content": base64.b64encode(data).decode()}},
            timeout=timeout,
        )
        if response.status_code == 400:
            # 길이·인코딩 문제가 여기로 온다. 앞부분만 전사된 채 성공으로 넘어가는
            # 것보다 명시적으로 실패하는 편이 낫다.
            logger.warning("Google STT 400 source=%s", filename)
            raise TranscriptionError(
                ErrorCode.PROVIDER_ERROR,
                "Google 동기 인식이 거절했습니다. 약 1분을 넘는 녹음은 지원하지 "
                "않으니 CLOVA 제공자를 사용하거나 파일을 나눠주세요.",
                source=filename,
            )
        response.raise_for_status()
        payload = response.json()
    except TranscriptionError:
        raise
    except Exception as exc:
        logger.warning("Google 전사 실패 source=%s", filename, exc_info=True)
        raise TranscriptionError(
            ErrorCode.PROVIDER_ERROR,
            "음성 전사에 실패했습니다. 파일이 손상되었거나 서비스가 일시적으로 "
            "불가능할 수 있습니다.",
            source=filename,
        ) from exc

    raw_segments, warnings = _segments_from_payload(payload)
    return assemble(
        source=filename,
        raw_segments=raw_segments,
        provider=NAME,
        model=model or "default",
        language=language,
        duration=None,
        warnings=warnings,
    )
