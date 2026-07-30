"""전사 진입점.

제공자 선택과 사전 검증만 담당하고, 실제 호출은 `providers/`의 모듈이 한다.
검증을 제공자보다 앞에 두는 이유는 전사가 **과금되는 외부 호출**이기 때문이다.
형식·크기 위반은 보내기 전에 거른다.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from . import providers
from .base import ErrorCode, Transcript, TranscriptionError

# 상한·지원 형식은 제공자마다 다르므로(openai 25MB vs clova 200MB) 모듈 상수로
# 고정하지 않는다. import 시점의 기본 제공자 값으로 굳으면, STT_PROVIDER를 바꾼
# 뒤에도 옛 값을 돌려줘 호출자의 사전 검증이 멀쩡한 파일을 거절한다.
# 필요하면 max_audio_bytes()/supported_suffixes()를 호출한다.


def current_provider_name() -> str:
    """STT_PROVIDER 환경변수로 제공자를 고른다. 미지정이면 기본값."""
    return (os.getenv("STT_PROVIDER") or providers.DEFAULT_PROVIDER).strip().lower()


def _resolve(name: Optional[str] = None):
    provider_name = (name or current_provider_name()).lower()
    try:
        return providers.get(provider_name)
    except KeyError:
        raise TranscriptionError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"알 수 없는 STT 제공자입니다: {provider_name} "
            f"(사용 가능: {' / '.join(providers.available())})",
        ) from None


def supported_suffixes(provider: Optional[str] = None) -> frozenset[str]:
    return _resolve(provider).SUPPORTED_SUFFIXES


def max_audio_bytes(provider: Optional[str] = None) -> int:
    return _resolve(provider).MAX_AUDIO_BYTES


def supports_diarization(provider: Optional[str] = None) -> bool:
    return bool(getattr(_resolve(provider), "SUPPORTS_DIARIZATION", False))


def is_supported(filename: str, provider: Optional[str] = None) -> bool:
    return Path(filename).suffix.lower() in supported_suffixes(provider)


def _validate(filename: str, data: bytes, module) -> None:
    """외부 호출 전에 거를 수 있는 것은 전부 여기서 거른다."""
    suffix = Path(filename).suffix.lower()
    if suffix not in module.SUPPORTED_SUFFIXES:
        raise TranscriptionError(
            ErrorCode.UNSUPPORTED_FORMAT,
            f"{module.NAME} 제공자가 지원하지 않는 오디오 형식입니다. ("
            + " / ".join(sorted(module.SUPPORTED_SUFFIXES)) + ")",
            source=filename,
        )
    if not data:
        raise TranscriptionError(
            ErrorCode.EMPTY_AUDIO,
            "오디오 파일이 비어 있습니다.",
            source=filename,
        )
    if len(data) > module.MAX_AUDIO_BYTES:
        limit_mb = module.MAX_AUDIO_BYTES // (1024 * 1024)
        raise TranscriptionError(
            ErrorCode.FILE_TOO_LARGE,
            f"오디오 크기는 {limit_mb} MB를 초과할 수 없습니다. "
            "긴 녹음은 나눠서 올리거나 화자 분리를 지원하는 clova 제공자를 사용하세요.",
            source=filename,
        )


def transcribe(
    filename: str,
    data: bytes,
    language: Optional[str] = None,
    model: Optional[str] = None,
    provider: Optional[str] = None,
) -> Transcript:
    """오디오 바이트를 Transcript로 전사한다.

    provider를 지정하지 않으면 `STT_PROVIDER`(기본 openai)를 쓴다. 화자 구분이
    필요한 회의 녹음은 `clova`(한국어 권장)를 선택한다.

    language를 지정하지 않으면 제공자가 추정한다. 회의 녹음은 대개 한국어라
    `STT_LANGUAGE`로 기본값을 고정해 두면 오인식이 줄어든다.
    """
    module = _resolve(provider)
    _validate(filename, data, module)
    language = language or os.getenv("STT_LANGUAGE") or None
    return module.transcribe(filename, data, language=language, model=model)
