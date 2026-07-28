"""음성 전사(STT) 공통 계약.

전사기는 오디오 바이트를 받아 `Transcript` 하나를 돌려주고, 후속 단계
(extractor·ingestor)는 어떤 STT 제공자를 썼는지 알 필요가 없다.

평문 대신 Segment 목록을 넘기는 이유는 출처 추적성 때문이다. 회의 녹음에서
"이 결정이 몇 분 몇 초에 나왔는가"는 문서의 페이지 번호에 해당하는 정보이고,
전사 텍스트를 하나로 이어 붙이는 순간 되돌릴 수 없다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Optional


class ErrorCode:
    """전사 실패 코드. 사용자에게 "왜 실패했는지"를 명시적으로 알린다."""
    UNSUPPORTED_FORMAT = "unsupported_audio_format"
    MISSING_DEPENDENCY = "missing_dependency"
    MISSING_CREDENTIALS = "missing_credentials"
    FILE_TOO_LARGE = "audio_too_large"
    EMPTY_AUDIO = "empty_audio"
    NO_SPEECH = "no_speech"
    PROVIDER_ERROR = "stt_provider_error"


class WarningCode:
    """전사 경고. 전사는 성공했지만 품질·완전성에 유의할 점이 있음을 알린다."""
    LOW_CONFIDENCE = "low_confidence_segment"
    NO_TIMESTAMPS = "no_timestamps"
    NO_SPEAKER_LABELS = "no_speaker_labels"
    LANGUAGE_GUESSED = "language_guessed"


class TranscriptionError(Exception):
    """전사 실패. 호출자가 사용자에게 사유를 그대로 전달할 수 있어야 한다."""

    def __init__(self, code: str, message: str, source: Optional[str] = None):
        self.code = code
        self.message = message
        self.source = source
        super().__init__(f"[{code}] {message}")

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "source": self.source}


@dataclass(frozen=True)
class TranscriptionWarning:
    code: str
    message: str
    location: Optional[str] = None

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "location": self.location}


@dataclass(frozen=True)
class Segment:
    """전사의 최소 단위. 보통 한 문장 또는 한 발화 구간.

    speaker는 제공자가 화자 분리를 지원할 때만 채워진다. **화자 이름 자동 매핑은
    이번 범위에서 제외**이므로, 여기 담기는 값은 실제 사람 이름이 아니라 제공자가
    붙인 익명 라벨(`화자 1`)이다. 추측으로 이름을 채우지 않는다.
    """
    index: int
    text: str
    start: float                       # 시작 시각(초)
    end: float                         # 종료 시각(초)
    speaker: Optional[str] = None

    @property
    def timestamp(self) -> str:
        """[MM:SS] 형태의 사람이 읽는 시각 표기."""
        return _format_timestamp(self.start)


@dataclass
class Transcript:
    """전사기의 유일한 출력."""
    source: str                        # 원본 파일명
    segments: list[Segment]
    language: Optional[str] = None
    duration: Optional[float] = None   # 전체 길이(초)
    provider: str = ""
    model: str = ""
    warnings: list[TranscriptionWarning] = field(default_factory=list)

    @property
    def text(self) -> str:
        """extractor(LLM)에 넘길 평문.

        각 줄 앞에 타임스탬프(와 있으면 화자)를 붙인다. LLM이 "언제 나온 발언인지"를
        읽을 수 있어야 추출된 항목에 시각 근거를 남길 수 있다.
        """
        lines = []
        for segment in self.segments:
            prefix = f"[{segment.timestamp}]"
            if segment.speaker:
                prefix = f"{prefix} {segment.speaker}:"
            lines.append(f"{prefix} {segment.text}")
        return "\n".join(lines)

    @property
    def plain_text(self) -> str:
        """타임스탬프 없는 순수 전사문."""
        return " ".join(s.text for s in self.segments)

    def warning_dicts(self) -> list[dict]:
        return [w.to_dict() for w in self.warnings]

    def has_speakers(self) -> bool:
        return any(s.speaker for s in self.segments)


def _format_timestamp(seconds: float) -> str:
    """초를 MM:SS(1시간 이상이면 H:MM:SS)로 표기한다."""
    if seconds is None or seconds < 0:
        seconds = 0.0
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def assemble(
    source: str,
    raw_segments: list[dict],
    provider: str,
    model: str,
    language: Optional[str] = None,
    duration: Optional[float] = None,
    warnings: Optional[list[TranscriptionWarning]] = None,
) -> Transcript:
    """제공자별 응답을 최종 Transcript로 확정한다.

    index 부여와 빈 구간 제거를 여기 한 곳에 모아, 제공자를 추가해도 후속 단계가
    보는 모양이 달라지지 않게 한다.
    """
    # 파일명은 여기서 한 번만 정규화한다. source는 memory_sources.source_path로
    # 그대로 저장되므로, 경로 구분자가 섞인 값이 DB에 들어가면 문서 업로드 경로가
    # safe_upload_name()으로 지키는 규약과 어긋난다.
    source = PurePosixPath(source.replace("\\", "/")).name or source

    segments: list[Segment] = []
    collected: list[TranscriptionWarning] = list(warnings or [])

    for raw in raw_segments:
        text = (raw.get("text") or "").strip()
        if not text:
            continue
        # 제공자가 음수·역전 시각을 주는 경우가 있어 방어한다. 표시만 보정하고
        # 데이터에 그대로 두면 시각 기반 정렬·계산이 조용히 틀어진다.
        start = max(float(raw.get("start") or 0.0), 0.0)
        end = max(float(raw.get("end") or start), start)
        speaker = raw.get("speaker") or None
        segments.append(Segment(
            index=len(segments),
            text=text,
            start=start,
            end=end,
            speaker=speaker,
        ))

    if not segments:
        raise TranscriptionError(
            ErrorCode.NO_SPEECH,
            "오디오에서 인식된 음성이 없습니다. 무음이거나 잡음만 있는 파일일 수 있습니다.",
            source=source,
        )

    if not any(s.speaker for s in segments):
        # 화자 정보가 없다는 사실을 알린다. 조용히 비워 두면 사용자는 전사가
        # 화자를 구분했다고 오해할 수 있다. (화자 이름 매핑은 범위 밖 후속 과제)
        collected.append(TranscriptionWarning(
            WarningCode.NO_SPEAKER_LABELS,
            "화자 구분 정보가 없습니다. 발언자별 구분이 필요하면 수동으로 확인해야 합니다.",
        ))

    # 같은 코드·메시지·위치의 경고는 한 번만 남긴다.
    collected = list(dict.fromkeys(collected))

    return Transcript(
        source=source,
        segments=segments,
        language=language,
        # 마지막 구간의 end를 쓰면 구간 순서가 뒤섞인 응답에서 길이가 틀어진다.
        duration=duration if duration is not None else max(s.end for s in segments),
        provider=provider,
        model=model,
        warnings=collected,
    )
