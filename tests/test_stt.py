"""음성 전사(STT) → Project Memory 회귀 테스트.

외부 API는 stable boundary(OpenAI 클라이언트)에서만 mock하고, 그 아래 계약
변환·타임스탬프 보존·오류 분류는 실제 코드로 검증한다.
"""
from unittest.mock import MagicMock, patch

import pytest

from backend.stt import (
    ErrorCode,
    MAX_AUDIO_BYTES,
    Transcript,
    TranscriptionError,
    WarningCode,
    is_supported,
    supported_suffixes,
    transcribe,
)
from backend.stt.base import Segment, assemble


# ─── 입력 검증 (외부 호출 전에 걸러야 하는 것) ─────────────────────────────

def test_supported_audio_formats():
    assert {".mp3", ".m4a", ".wav", ".webm"} <= supported_suffixes()
    assert is_supported("회의녹음.M4A")  # 확장자 대소문자 무관


def test_unsupported_format_rejected_before_api_call():
    """지원하지 않는 형식은 과금되는 외부 호출 전에 거절한다."""
    with patch("backend.stt.transcriber._require_client") as client:
        with pytest.raises(TranscriptionError) as exc:
            transcribe("회의.aac", b"data")
    assert exc.value.code == ErrorCode.UNSUPPORTED_FORMAT
    client.assert_not_called()


def test_empty_audio_rejected():
    with patch("backend.stt.transcriber._require_client") as client:
        with pytest.raises(TranscriptionError) as exc:
            transcribe("회의.mp3", b"")
    assert exc.value.code == ErrorCode.EMPTY_AUDIO
    client.assert_not_called()


def test_oversized_audio_rejected_before_api_call():
    """상한 초과는 호출해봐야 거절되므로 미리 막는다."""
    with patch("backend.stt.transcriber._require_client") as client:
        with pytest.raises(TranscriptionError) as exc:
            transcribe("긴회의.mp3", b"x" * (MAX_AUDIO_BYTES + 1))
    assert exc.value.code == ErrorCode.FILE_TOO_LARGE
    assert "나눠서" in exc.value.message  # 조치 안내가 있어야 한다
    client.assert_not_called()


def test_missing_credentials_has_distinct_code(monkeypatch):
    """키 없음은 전사 실패와 구분돼야 한다 — 운영 설정 문제이지 파일 문제가 아니다."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(TranscriptionError) as exc:
        transcribe("회의.mp3", b"audio-bytes")
    assert exc.value.code == ErrorCode.MISSING_CREDENTIALS


# ─── 전사 응답 → Transcript 계약 ───────────────────────────────────────────

def _fake_response(segments, language="ko", duration=12.0):
    response = MagicMock()
    response.segments = segments
    response.language = language
    response.duration = duration
    return response


def _transcribe_with(response, filename="회의녹음.m4a", **kwargs):
    client = MagicMock()
    client.audio.transcriptions.create.return_value = response
    with patch("backend.stt.transcriber._require_client", return_value=client):
        return transcribe(filename, b"audio-bytes", **kwargs), client


def test_segments_preserve_timestamps():
    """구간별 시각이 보존돼야 '몇 분에 나온 결정인가'를 되짚을 수 있다."""
    transcript, _ = _transcribe_with(_fake_response([
        {"text": "기술 스택은 FastAPI로 갑니다.", "start": 0.0, "end": 4.2},
        {"text": "배포는 다음 주에 하겠습니다.", "start": 4.2, "end": 9.8},
    ]))

    assert [s.index for s in transcript.segments] == [0, 1]
    assert transcript.segments[0].start == 0.0
    assert transcript.segments[1].end == 9.8
    assert transcript.language == "ko"


def test_transcript_text_carries_timestamps_for_llm():
    """LLM 입력에 시각이 포함돼야 추출 결과에 시각 근거가 남는다."""
    transcript, _ = _transcribe_with(_fake_response([
        {"text": "첫 발언", "start": 0.0, "end": 3.0},
        {"text": "둘째 발언", "start": 65.0, "end": 70.0},
    ]))

    assert "[00:00] 첫 발언" in transcript.text
    assert "[01:05] 둘째 발언" in transcript.text
    # 순수 전사문도 따로 얻을 수 있어야 한다.
    assert transcript.plain_text == "첫 발언 둘째 발언"


def test_timestamp_format_handles_hours():
    assert Segment(0, "x", 3725.0, 3730.0).timestamp == "1:02:05"
    assert Segment(0, "x", 59.0, 60.0).timestamp == "00:59"


def test_speaker_labels_preserved_when_provided():
    """제공자가 화자를 주면 보존한다. 다만 이름을 추측하지는 않는다."""
    transcript, _ = _transcribe_with(_fake_response([
        {"text": "제안합니다.", "start": 0.0, "end": 2.0, "speaker": "화자 1"},
        {"text": "동의합니다.", "start": 2.0, "end": 4.0, "speaker": "화자 2"},
    ]))

    assert transcript.has_speakers()
    assert "화자 1: 제안합니다." in transcript.text
    # 화자가 있으면 "화자 정보 없음" 경고는 나오지 않는다.
    assert WarningCode.NO_SPEAKER_LABELS not in {w.code for w in transcript.warnings}


def test_missing_speaker_labels_warns():
    """화자 정보가 없다는 사실을 알린다 — 조용히 비우면 구분됐다고 오해한다."""
    transcript, _ = _transcribe_with(_fake_response([
        {"text": "발언 내용", "start": 0.0, "end": 2.0},
    ]))
    assert WarningCode.NO_SPEAKER_LABELS in {w.code for w in transcript.warnings}


def test_response_without_segments_falls_back_with_warning():
    """타임스탬프를 못 받아도 전사문 자체는 살린다."""
    response = MagicMock()
    response.segments = None
    response.text = "구간 정보 없는 전체 전사문"
    response.language = "ko"
    response.duration = 5.0

    transcript, _ = _transcribe_with(response)
    assert len(transcript.segments) == 1
    assert "구간 정보 없는" in transcript.text
    assert WarningCode.NO_TIMESTAMPS in {w.code for w in transcript.warnings}


def test_silent_audio_raises_no_speech():
    """무음은 빈 성공이 아니라 명시적 오류다."""
    response = MagicMock()
    response.segments = []
    response.text = ""
    with pytest.raises(TranscriptionError) as exc:
        _transcribe_with(response)
    assert exc.value.code == ErrorCode.NO_SPEECH


def test_provider_failure_is_normalized_and_does_not_leak_detail():
    """제공자 오류 원문에는 요청 세부가 섞일 수 있어 그대로 노출하지 않는다."""
    client = MagicMock()
    client.audio.transcriptions.create.side_effect = RuntimeError(
        "api_key=sk-secret-value rejected"
    )
    with patch("backend.stt.transcriber._require_client", return_value=client):
        with pytest.raises(TranscriptionError) as exc:
            transcribe("회의.mp3", b"audio-bytes")

    assert exc.value.code == ErrorCode.PROVIDER_ERROR
    assert "sk-secret-value" not in exc.value.message


def test_language_is_passed_through_when_specified():
    """언어를 지정하면 추정에 맡기지 않고 그대로 넘긴다."""
    _, client = _transcribe_with(
        _fake_response([{"text": "안녕하세요", "start": 0.0, "end": 1.0}]),
        language="ko",
    )
    kwargs = client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["language"] == "ko"
    assert kwargs["response_format"] == "verbose_json"


def test_language_guess_is_reported():
    """언어를 지정하지 않으면 추정했다는 사실을 알린다."""
    transcript, _ = _transcribe_with(
        _fake_response([{"text": "hello", "start": 0.0, "end": 1.0}], language="en")
    )
    assert WarningCode.LANGUAGE_GUESSED in {w.code for w in transcript.warnings}


def test_object_style_segments_are_supported():
    """실제 SDK는 dict가 아니라 객체를 돌려준다 — 양쪽 모두 다뤄야 한다."""
    class SegmentObject:
        def __init__(self, text, start, end):
            self.text, self.start, self.end = text, start, end

    transcript, _ = _transcribe_with(_fake_response([
        SegmentObject("객체 구간 하나", 0.0, 3.0),
        SegmentObject("객체 구간 둘", 3.0, 7.0),
    ]))

    assert len(transcript.segments) == 2
    assert transcript.segments[1].start == 3.0
    assert "[00:03] 객체 구간 둘" in transcript.text


def test_api_call_has_timeout():
    """타임아웃 없이 호출하면 제공자가 멈췄을 때 워커가 SDK 기본 10분간 묶인다."""
    _, client = _transcribe_with(
        _fake_response([{"text": "내용", "start": 0.0, "end": 1.0}])
    )
    kwargs = client.audio.transcriptions.create.call_args.kwargs
    assert "timeout" in kwargs
    assert 0 < kwargs["timeout"] <= 600


def test_source_filename_is_normalized_to_basename():
    """source는 memory_sources.source_path로 저장되므로 경로가 섞이면 안 된다."""
    transcript, _ = _transcribe_with(
        _fake_response([{"text": "내용", "start": 0.0, "end": 1.0}]),
        filename="../../etc/passwd.mp3",
    )
    assert transcript.source == "passwd.mp3"


def test_negative_and_reversed_timestamps_are_clamped():
    """제공자가 음수·역전 시각을 줘도 데이터가 오염되지 않아야 한다."""
    transcript, _ = _transcribe_with(_fake_response([
        {"text": "역전", "start": 10.0, "end": 2.0},
        {"text": "음수", "start": -5.0, "end": 1.0},
    ], duration=None))

    for segment in transcript.segments:
        assert segment.start >= 0
        assert segment.end >= segment.start
    # duration은 마지막 구간이 아니라 최대 end를 따라야 한다.
    assert transcript.duration == 10.0


def test_blank_segments_are_dropped():
    transcript, _ = _transcribe_with(_fake_response([
        {"text": "   ", "start": 0.0, "end": 1.0},
        {"text": "실제 내용", "start": 1.0, "end": 2.0},
    ]))
    assert len(transcript.segments) == 1
    assert transcript.segments[0].index == 0


# ─── Project Memory 연결 ───────────────────────────────────────────────────

def _sample_transcript() -> Transcript:
    return assemble(
        source="회의녹음.m4a",
        raw_segments=[
            {"text": "기술 스택은 FastAPI로 결정했습니다.", "start": 0.0, "end": 4.0},
            {"text": "김동휘님이 명세서를 작성하겠습니다.", "start": 4.0, "end": 8.0},
        ],
        provider="openai",
        model="whisper-1",
        language="ko",
    )


def test_ingest_transcript_feeds_extractor_and_ingestor():
    """전사문이 추출·적재 파이프라인으로 흘러가야 한다 (STT의 실제 완료 조건)."""
    from backend.stt import ingest_transcript

    with patch("backend.stt.pipeline.extract", return_value=[]) as mock_extract, \
         patch("backend.stt.pipeline.ingest") as mock_ingest:
        summary = ingest_transcript(1, _sample_transcript(), date="2026-07-28")

    # 추출에는 타임스탬프가 붙은 텍스트가 들어간다.
    extract_text = mock_extract.call_args.args[0]
    assert "[00:00]" in extract_text and "FastAPI" in extract_text
    assert mock_extract.call_args.kwargs["source_kind"] == "transcript"

    # 적재는 전사 출처로 기록된다.
    kwargs = mock_ingest.call_args.kwargs
    assert kwargs["project_id"] == 1
    assert kwargs["doc_type"] == "meeting"
    assert kwargs["source_metadata"]["source_kind"] == "transcript"
    assert kwargs["source_metadata"]["source_ref"] == "openai:whisper-1"

    assert summary["segments"] == 2
    assert summary["language"] == "ko"


def test_source_kind_fits_database_column():
    """memory_sources.source_kind는 VARCHAR(20)이다."""
    from backend.stt import SOURCE_KIND

    assert len(SOURCE_KIND) <= 20


def test_ingest_transcript_rejects_empty_transcript():
    from backend.stt import ingest_transcript

    empty = Transcript(source="빈.m4a", segments=[])
    with patch("backend.stt.pipeline.extract") as mock_extract:
        with pytest.raises(ValueError):
            ingest_transcript(1, empty)
    mock_extract.assert_not_called()


def test_ingest_failure_propagates_not_swallowed():
    """적재 실패를 성공으로 위장하지 않는다."""
    from backend.stt import ingest_transcript

    with patch("backend.stt.pipeline.extract", return_value=[]), \
         patch("backend.stt.pipeline.ingest", side_effect=RuntimeError("DB down")):
        with pytest.raises(RuntimeError):
            ingest_transcript(1, _sample_transcript())


def test_transcribe_and_ingest_wires_both_stages():
    from backend.stt import transcribe_and_ingest

    with patch("backend.stt.transcriber.transcribe", return_value=_sample_transcript()), \
         patch("backend.stt.pipeline.extract", return_value=[]), \
         patch("backend.stt.pipeline.ingest"):
        summary = transcribe_and_ingest(1, "회의녹음.m4a", b"audio", date="2026-07-28")

    assert summary["segments"] == 2
    assert summary["source"] == "회의녹음.m4a"
