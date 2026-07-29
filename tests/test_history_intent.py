"""TASK-004 계층 3 — history_intent 말단 모듈 테스트.

이력 질문 감지(보수적 정규식), 지시어 판정, canonical 내용어 추출(질문·컴포넌트
양쪽 단일 함수), 그리고 순환 import 차단(단독 import 격리)을 검증한다.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from backend.retriever import history_intent

_REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("question", [
    "왜 바뀌었어?",
    "배포 주기가 왜 바뀌었어?",
    "JWT로 왜 바뀌었어?",
    "원래 계획은?",
    "처음 결정이 뭐였지?",
    "이전 결정 목록 보여줘",
    "변경 이력 정리해줘",
    "번복된 결정 있어?",
    "그건 왜 바뀌었어?",
    "어떻게 바뀌어왔어?",
    "바뀐 이유가 뭐야?",
    "JWT로 바꾼 이유가 뭐야?",   # round-3 R-008: 능동 관형형 + 이유
    "수정한 이유가 뭐지?",
    "왜 JWT로 바꿨어?",          # round-3 R-008: 왜 + 능동 변화 동사
])
def test_detects_history_questions(question):
    assert history_intent.detect_history_intent(question)


@pytest.mark.parametrize("question", [
    "현재 상태는?",
    "배포 일정 알려줘",
    "왜 이슈가 생겼어?",              # 이유 질문이지만 변화 동사 없음 — 일반 semantic
    "프로젝트 전체 상황 정리해줘",     # overview 규칙 유지
    "박제섭이 담당인 미완료 액션은?",  # filter_lookup 규칙 유지
    "완료된 액션 몇 개야?",
    "마감 지난 거 있어?",
    "기존 보안 이슈 목록 보여줘",      # round-2 R-005: '보안' 내부 '안' 오매칭 금지
    "",
])
def test_does_not_detect_regular_questions(question):
    assert not history_intent.detect_history_intent(question)


def test_is_deictic_whitelist():
    assert history_intent.is_deictic("그건 왜 바뀌었어?")
    assert history_intent.is_deictic("그 결정 말이야, 원래 뭐였어?")
    assert not history_intent.is_deictic("배포 주기가 왜 바뀌었어?")
    assert not history_intent.is_deictic("")


@pytest.mark.parametrize("question", [
    "왜 바뀌었어?",
    "변경 이력 정리해줘",
    "그건 왜 바뀌었어?",       # 지시어도 제거
    "바뀐 이유가 뭐야?",        # round-2 R-006: 활용형 '바뀐' + 일반 표현 '이유/뭐'
    "변경된 배경은?",           # round-2 R-006: '배경' + 고아 조사 잔재
    "원래는 뭐였지?",
    "어떻게 바뀌어왔어?",       # 용언 잔재('어떻')는 명사 태그 필터가 차단
    "원래 계획은?",             # round-3 R-007: 감지 구문의 분류 명사('계획')도 주제 아님
    "처음 결정이 뭐였지?",
    "이전 결정 목록 보여줘",     # 분류 명사 + 요청 명사('목록') 모두 제거
    "수정 이력 정리해줘",
])
def test_global_predicate_when_only_trigger_words(question):
    """트리거·일반 이유/의문 표현만 있는 이력 질문은 전역형(빈 집합)이어야 한다.
    제거 없이 토크나이즈하면 Kiwi가 '바뀌'(VV) 등을 내용어로 뽑아 주제형으로
    오판되고, 그 단어를 우연히 포함한 오래된 컴포넌트가 최신 체인을 밀어낸다."""
    assert history_intent.extract_content_tokens(question) == set()


def test_topical_predicate_keeps_content_tokens():
    assert history_intent.extract_content_tokens("배포 주기가 왜 바뀌었어?") == {"배포", "주기"}
    assert history_intent.extract_content_tokens("JWT로 왜 바뀌었어?") == {"jwt"}
    # 능동형(round-3 R-008)에서도 주제 명사만 남는다
    assert history_intent.extract_content_tokens("JWT로 바꾼 이유가 뭐야?") == {"jwt"}
    # 결합 질문(지시어 승계 시나리오): 요청 표현·용언 잔재 없이 주제 명사만 남는다
    assert history_intent.extract_content_tokens(
        "배포 주기 어떻게 하기로 했어? 그건 왜 바뀌었어?"
    ) == {"배포", "주기"}


def test_canonical_normalization_unifies_question_and_component():
    """5차 P1 회귀: 질문 "JWT로"(조사 결합 표면형)와 컴포넌트 "JWT 도입"이
    같은 canonical 함수로 정규화되어 교집합이 성립해야 한다."""
    question_tokens = history_intent.extract_content_tokens("JWT로 왜 바뀌었어?")
    component_tokens = history_intent.content_tokens("JWT 도입")
    assert question_tokens & component_tokens == {"jwt"}


def test_content_tokens_no_fallback_to_raw_text():
    """전부 걸러지면 빈 집합 — 원문 폴백 금지(predicate 판정용)."""
    assert history_intent.content_tokens("었어?") == set()
    assert history_intent.content_tokens("") == set()
    assert history_intent.content_tokens("   ") == set()


@pytest.mark.parametrize("module", [
    "backend.retriever.history_intent",
    "backend.retriever.qa_engine",
    "backend.project_memory",
    "backend.api.query",
])
def test_module_imports_standalone(module):
    """새 프로세스 단독 import — history_intent 도입이 순환 import를 만들지 않는다."""
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True, text=True, cwd=_REPO_ROOT,
        env={**os.environ, "PAIM_AUTH_MODE": "dev"},
    )
    assert result.returncode == 0, result.stderr
