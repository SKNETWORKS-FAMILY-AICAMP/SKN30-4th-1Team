"""회의록 스크립트 → 음성 파일 파이프라인 (STT 왕복 검증용).

STT는 실제 오디오 없이는 검증할 수 없는데, 실제 회의 녹음은 개인정보 때문에
저장소에 둘 수 없다. 그래서 합성 스크립트를 TTS로 읽혀 검증용 오디오를 만든다.
화자마다 다른 목소리를 써서 화자 분리(diarization) 검증에도 쓸 수 있다.

**이 스크립트는 유료 API를 호출하므로 테스트 수집 대상이 아니다.** 필요할 때
사람이 직접 실행한다.

    OPENAI_API_KEY=... uv run python -m tests.tools.make_meeting_audio out.mp3

`--speaker-gap` 으로 발화 사이 무음을 넣으면 화자 경계가 뚜렷해져 분리 정확도가
올라간다. 기본값 0.4초.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .meeting_script import SCRIPT, SPEAKERS

# 44.1kHz 스테레오 128kbps MP3 무음 프레임 1개(약 26ms). 발화 사이에 끼워
# 화자 경계를 만든다. mp3는 프레임 단위 스트림이라 이어붙이기가 성립한다.
_SILENT_FRAME = bytes.fromhex(
    "fffb90c4000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
) + bytes(380)
_FRAME_SECONDS = 0.026


def _client():
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai 패키지가 필요합니다: uv add openai")
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        sys.exit("OPENAI_API_KEY가 설정되어 있지 않습니다.")
    return OpenAI(api_key=key)


def synthesize(output: Path, gap_seconds: float = 0.4, model: str = "tts-1") -> Path:
    """스크립트를 발화 단위로 합성해 하나의 mp3로 잇는다."""
    client = _client()
    silence = _SILENT_FRAME * max(int(gap_seconds / _FRAME_SECONDS), 0)

    chunks: list[bytes] = []
    for index, utterance in enumerate(SCRIPT, start=1):
        response = client.audio.speech.create(
            model=model,
            voice=utterance.voice,
            input=utterance.text,
            response_format="mp3",
        )
        chunks.append(response.content)
        if silence and index < len(SCRIPT):
            chunks.append(silence)
        print(f"  [{index}/{len(SCRIPT)}] {utterance.speaker}({utterance.voice}) "
              f"{len(response.content):,} bytes")

    audio = b"".join(chunks)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(audio)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description="합성 회의록을 음성 파일로 만든다")
    parser.add_argument("output", type=Path, help="출력 mp3 경로")
    parser.add_argument("--speaker-gap", type=float, default=0.4,
                        help="발화 사이 무음(초). 화자 경계를 뚜렷하게 한다")
    parser.add_argument("--model", default="tts-1", help="TTS 모델")
    args = parser.parse_args()

    print(f"화자 {len(SPEAKERS)}명 / 발화 {len(SCRIPT)}개 합성")
    path = synthesize(args.output, args.speaker_gap, args.model)
    size = path.stat().st_size
    print(f"완료: {path} ({size:,} bytes, {size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
