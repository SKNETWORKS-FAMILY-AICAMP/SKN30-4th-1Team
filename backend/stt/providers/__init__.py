"""전사 제공자 레지스트리.

제공자를 바꿔도 호출자(`backend.stt.transcribe`)와 후속 단계는 수정하지 않는다.
새 제공자를 추가하는 방법은 모듈 하나를 만들고 아래 `_PROVIDERS`에 등록하는 것뿐이다.

각 제공자 모듈은 다음을 선언한다.
- `NAME`                 : 선택자 이름
- `SUPPORTED_SUFFIXES`   : 받는 확장자
- `MAX_AUDIO_BYTES`      : 업로드 상한
- `SUPPORTS_DIARIZATION` : 화자 분리 지원 여부
- `transcribe(filename, data, language, model) -> Transcript`
"""
from __future__ import annotations

from types import ModuleType

from . import clova_stt, google_stt, openai_stt

# 화자 분리가 필요하면 clova(한국어 회의 권장) 또는 google을 쓴다.
_PROVIDERS: dict[str, ModuleType] = {
    openai_stt.NAME: openai_stt,
    clova_stt.NAME: clova_stt,
    google_stt.NAME: google_stt,
}

DEFAULT_PROVIDER = openai_stt.NAME


def available() -> tuple[str, ...]:
    return tuple(_PROVIDERS)


def get(name: str) -> ModuleType:
    """이름으로 제공자 모듈을 얻는다. 없으면 KeyError."""
    return _PROVIDERS[name]


def diarizing_providers() -> tuple[str, ...]:
    """화자 분리를 지원하는 제공자 목록."""
    return tuple(
        name for name, module in _PROVIDERS.items()
        if getattr(module, "SUPPORTS_DIARIZATION", False)
    )


__all__ = ["DEFAULT_PROVIDER", "available", "diarizing_providers", "get"]
