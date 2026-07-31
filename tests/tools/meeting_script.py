"""STT 검증용 합성 회의록 스크립트.

실제 회의록을 쓰면 개인정보·기관 식별정보가 평가 저장소에 남으므로(평가 데이터 정책),
검증에는 이 합성 스크립트를 쓴다.

스크립트는 추출기가 뽑아야 할 네 범주를 모두 담는다.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Utterance:
    speaker: str
    voice: str      # TTS 목소리 (화자 분리 검증을 위해 화자마다 다르게)
    text: str


# 화자 4명. 목소리를 다르게 줘야 화자 분리(diarization) 검증이 의미를 갖는다.
SCRIPT: tuple[Utterance, ...] = (
    Utterance("박지훈", "onyx",
              "자, 이번 주 정기 회의를 시작하겠습니다. 먼저 백엔드 기술 스택부터 정리하죠."),
    Utterance("이서연", "nova",
              "백엔드 프레임워크는 FastAPI로 결정하는 게 좋겠습니다. "
              "비동기 처리가 필요하고 팀원 대부분이 경험이 있어서요."),
    Utterance("박지훈", "onyx",
              "좋습니다. 그러면 백엔드는 FastAPI로 확정하겠습니다."),
    Utterance("김동휘", "echo",
              "제가 다음 주 금요일까지 API 명세서 초안을 작성해서 공유드리겠습니다."),
    Utterance("이서연", "nova",
              "그런데 지금 MySQL 연결 테스트에서 타임아웃이 계속 발생하고 있습니다. "
              "커넥션 풀 설정 문제로 보입니다."),
    Utterance("최민수", "fable",
              "그 부분은 제가 오늘 중으로 확인해서 원인 파악하겠습니다."),
    Utterance("박지훈", "onyx",
              "네. 그리고 우려되는 점이 하나 있는데, 다음 달에 백엔드 인력이 한 명 "
              "빠질 예정이라 일정이 지연될 위험이 있습니다."),
    Utterance("최민수", "fable",
              "벡터 데이터베이스는 ChromaDB를 그대로 쓰기로 하죠. 이미 검증이 끝났습니다."),
    Utterance("박지훈", "onyx",
              "동의합니다. 그럼 오늘 회의는 여기서 마치겠습니다."),
)


SPEAKERS: tuple[str, ...] = tuple(dict.fromkeys(u.speaker for u in SCRIPT))
