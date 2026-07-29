"""NAVER CLOVA Speech 전사 제공자 (화자 분리 지원).

한국어 회의 녹음에 가장 적합한 선택지다.
- 화자 분리(diarization)를 지원해 발언자별로 구간이 나뉜다
- 긴 파일을 직접 업로드할 수 있어 OpenAI의 25MB 제약을 받지 않는다
- REST API라 새 패키지가 필요 없다(httpx는 openai가 이미 가져온다)

필요한 환경변수 (NAVER Cloud Platform 콘솔 → CLOVA Speech → 도메인 상세)
- `CLOVA_SPEECH_INVOKE_URL` : 도메인별 호출 URL.
  `https://clovaspeech-gw.ncloud.com/external/v1/{도메인ID}/{키}` 형태여야 한다.
  호스트만 적거나 gRPC 포트(`:50051`)를 적으면 동작하지 않는다 — gRPC는
  스트리밍(단문) API이고 여기서 쓰는 긴 문장 인식은 REST다.
- `CLOVA_SPEECH_SECRET`     : 도메인 Secret Key.
  **CSR(단문 인식) 시크릿과 다르다.** CSR은 화자 분리를 지원하지 않으므로
  이 제공자에는 쓸 수 없다.

> **검증 완료**: 합성 회의록(화자 4명·발화 9개)을 실제 서비스로 왕복 검증했다.
> 구간 9개·화자 4명(A~D)이 정확히 분리됐고, 밀리초→초 변환과 화자 라벨 매핑이
> 의도대로 동작했다. 추출 단계에서 6개 항목의 owner가 모두 올바른 화자로 귀속됐다.

화자 분리로 얻는 라벨은 `화자 1`·`화자 2` 같은 **익명 식별자**다. 실제 이름 매핑은
계획서가 후속 과제로 미룬 항목이므로 여기서 추측하지 않는다.

## 알려진 한계 — 영어 기술 용어 음차

한국어 발화에 섞인 영어 용어의 일부가 한글로 음차된다. `enko` 모드와 `boostings`를
적용한 뒤에도 남는 현상이다(실측).

    MySQL    → "마이세ql"
    ChromaDB → "크로마 DB"

`FastAPI`처럼 철자는 살아 있고 대소문자만 다른 경우(`fastapi`)는 **문제가 아니다.**
이 저장소의 검색 경로가 모두 대소문자를 정규화하기 때문이다 — BM25는
`qa_engine._tokenize_ko()`가 `.lower()`를 적용하고, MySQL은 기본 collation이
case-insensitive이며, Chroma는 임베딩 기반이다.

철자 자체가 깨지는 음차는 **교정하지 않는다.** 단어별 치환표를 두면 프로젝트·발음마다
패턴이 달라 끝없이 늘어나는 부채가 되고, 실사용 데이터 없이 만든 목록은 관리 비용만
남긴다. 벡터 검색은 음차된 청크도 의미상 근접하게 잡으므로 실질 손실이 크지 않다.
정확한 철자가 반드시 필요하면 화자 분리를 포기하고 openai 제공자를 쓴다.
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
# 어휘 목록은 제공자와 무관하게 같아야 한다 — 제공자를 바꿨다고 용어 표기가
# 달라지면 같은 문서가 검색에서 다르게 잡힌다.
from .openai_stt import _DEFAULT_VOCABULARY

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
    # "ko-KR"은 순수 한국어 인식 모드라 출력이 한글로 제약되고, 그 결과 영어
    # 기술 용어가 전부 한글 음차로 강제 변환된다(실측: FastAPI → "패스트 API").
    # "enko"는 한국어 발화에 섞인 영어를 그대로 인식하도록 만들어진 전용 모드다
    # (NCP 공식 문서, ai-application-service-clovaspeech-longsentence).
    # 회의 녹음은 기본적으로 영어 기술 용어가 섞이므로 enko를 기본값으로 한다.
    language = language or os.getenv("STT_LANGUAGE") or "enko"

    params = {
        "language": language,
        "completion": "sync",
        # 화자 분리. speakerCountMin/Max를 지정하지 않으면 CLOVA가 자동 추정한다.
        "diarization": {"enable": True},
        "wordAlignment": False,
        "fullText": True,
    }
    # 도메인 어휘 부스팅. 음차를 완전히 막지는 못하지만(모듈 상단 "알려진 한계"),
    # 붙이지 않는 것보다는 인식 정확도가 높다. weight는 문서 기준 형식을 따른다.
    vocabulary = os.getenv("STT_VOCABULARY", _DEFAULT_VOCABULARY).strip()
    if vocabulary:
        words = ", ".join(w.strip() for w in vocabulary.split(",") if w.strip())
        if words:
            params["boostings"] = [{"words": words, "weight": 5}]

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
        # invoke URL itself may contain a domain key. Exception repr/traceback can therefore
        # disclose credentials, so log only the exception type and the normalized source.
        logger.warning(
            "CLOVA 전사 실패 source=%s error_type=%s",
            Path(filename).name,
            type(exc).__name__,
        )
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
