"""이력(history) 질문 감지 — 말단 모듈.

"왜 바뀌었어?", "원래 계획은?" 류 질문을 감지해 supersede 체인 포함 여부를
결정한다. retriever 내부 모듈을 import하지 않아 Agentic 검색 Tool과
qa_engine에서 순환 없이 import할 수 있다. kiwipiepy는 외부 라이브러리이며
함수 내부에서 지연 import한다 — 모듈 import 시점 의존성 없음.
"""
import re
from typing import Set

# 이력 트리거: 보수적 구문 조합. 미탐 시 현행 동작(체인 미포함)이라 안전하므로
# recall보다 precision을 우선한다. 키워드는 운영 피드백으로 후속 튜닝.
_HISTORY_TRIGGER_RES = [
    # "왜 바뀌었어?", "JWT로 왜 변경됐지?", "왜 바꿨어?" — 이유 + 변화 동사(수동·능동)
    re.compile(r"(왜|어째서|무슨\s*이유)[^?\n]{0,16}?(바뀌|바꾸|바꿨|바꾼|변경|번복|뒤집)"),
    # "바뀐 이유가 뭐야?", "변경된 배경은?" — 변화 관형형(수동) + 이유
    re.compile(r"(바뀐|변경된|번복된|뒤집힌)\s*(이유|배경|경위)"),
    # "JWT로 바꾼 이유가 뭐야?", "수정한 배경은?" — 변화 관형형(능동) + 이유
    # (round-3 R-008: 능동형은 위 수동형 패턴에 안 걸려 체인 없는 semantic으로 샜음)
    re.compile(r"(바꾼|변경한|수정한|교체한|번복한|전환한)\s*[^?\n]{0,8}?(이유|배경|경위|까닭)"),
    # "원래 계획은?", "처음 결정이 뭐였지?" — 과거 상태 조회.
    # 단독 '안'은 쓰지 않는다(round-2 R-005): 한글에 \b가 안 통해 "보안"의 '안'과
    # 매칭되면 비이력 필터 질문("기존 보안 이슈 목록")이 이력 경로로 강제된다.
    re.compile(r"(원래|처음|애초|기존)(에는|에|엔|의)?\s*[^?\n]{0,12}?(계획|결정|방침|방향|방안|대안|초안|설계|버전|뭐)"),
    # "이전 결정 목록", "과거 방침" — 과거 한정사 + 결정 명사
    re.compile(r"(이전|과거|예전)의?\s*(계획|결정|방침|방향|방안|대안|초안|설계|버전)"),
    # "변경 이력 정리해줘", "결정 히스토리" — 이력/경위 명시
    re.compile(r"(변경|수정|번복|결정)\s*(이력|내역|히스토리|경위)"),
    # "어떻게 바뀌어왔어?" — 변천 경위
    re.compile(r"(어떻게|어떤\s*식으로)[^?\n]{0,16}?(바뀌어|변해|변천)"),
    # "번복"은 도메인 특화 어휘 — 등장 자체가 이력 의도
    re.compile(r"번복"),
]

# 지시어 화이트리스트: 직전 질문의 주제를 가리키는 표현.
_DEICTIC_RE = re.compile(
    r"(그거|그것|그건|그게|이거|이건|이게|저거"
    r"|그\s*(결정|계획|건|부분|항목|얘기|이야기)"
    r"|방금\s*(그|말한)|아까\s*(그|말한))"
)

# 주제 토큰 추출 전 제거할 표현: 이력 트리거 어휘 + 요청형 표현.
# 이걸 안 지우면 "왜 바뀌었어?"에서 Kiwi가 '바뀌'(VV)를 내용어로 뽑아
# 전역형 질문이 주제형으로 오판된다(실측 확인).
_TRIGGER_STRIP_RES = [
    # 활용형(바뀐/바뀔)과 일반 이유·의문 표현(이유/배경/뭐)도 제거한다(round-2
    # R-006): 감지기가 허용하는 표현이 주제 토큰으로 새면 주제 없는 이력 질문이
    # topical로 오판되어, 그 단어를 우연히 포함한 오래된 컴포넌트가 우선된다.
    # 명사형 트리거는 붙은 조사까지 \w*로 함께 제거 — "이유가"에서 '이유'만 지우면
    # 고아 조사 '가'를 Kiwi가 단독 용언으로 오태깅해 topical로 새는 것을 실측 확인.
    re.compile(
        r"(왜|어째서|무슨"
        r"|원래\w*|처음\w*|애초\w*|기존\w*|이전\w*|과거\w*|예전\w*"
        r"|바뀌\w*|바뀐\w*|바뀔\w*|바꾸\w*|바꾼\w*|바꿀\w*|바꿔\w*|바꿨\w*"
        r"|변경\w*|수정\w*|교체한|전환한|번복\w*|뒤집\w*|변해\w*|변천\w*"
        # 감지 구문의 분류 명사도 주제가 아니다(round-3 R-007): "원래 계획은?"이
        # {계획} topical이 되면 그 일반어를 포함한 오래된 컴포넌트가 최신 체인에 우선한다
        r"|계획\w*|결정\w*|방침\w*|방향\w*|방안\w*|대안\w*|초안\w*|설계\w*|버전\w*"
        r"|이유\w*|배경\w*|이력\w*|내역\w*|히스토리\w*|경위\w*|까닭\w*|무엇\w*|뭐\w*"
        r"|목록\w*|리스트\w*)"
    ),
    # "정리해줘", "알려줘" 류 요청 표현 — '하/주' 같은 용언 토큰이 새는 것 방지
    re.compile(r"(정리|요약|설명|말)?\s*해\s*?(줘|주세요|줄래|봐)\w*"),
    re.compile(r"(알려|보여)\s*(줘|주세요|줄래)\w*"),
]

_kiwi = None


def detect_history_intent(question: str) -> bool:
    """질문이 결정 변경 이력을 묻는지 보수적 정규식으로 판정한다."""
    if not question:
        return False
    return any(p.search(question) for p in _HISTORY_TRIGGER_RES)


def is_deictic(question: str) -> bool:
    """질문이 지시어로 직전 주제를 가리키는지 판정한다."""
    if not question:
        return False
    return bool(_DEICTIC_RE.search(question))


def content_tokens(text: str, *, nouns_only: bool = False) -> Set[str]:
    """canonical 내용어 추출 — 질문 주제 토큰과 컴포넌트 텍스트 양쪽이
    이 함수 하나를 사용해야 한다(표면형/형태소 불일치로 교집합이 항상
    공집합이 되는 결함 방지 — 예: 질문 "JWT로" ↔ 기록 "JWT 도입").

    qa_engine._tokenize_ko와 동일한 태그 집합(N/V/X 접두 + SL/SN)을 쓰되,
    전부 걸러지면 빈 집합을 반환한다(원문 폴백 없음 — predicate 판정용이라
    폴백하면 전역형 질문이 주제형으로 오판된다).

    nouns_only=True는 질문 주제 토큰 전용: 명사 계열(N 접두 + SL/SN)만 남긴다.
    주제는 명사 공간이므로, 트리거 활용형·요청 표현에서 나오는 용언 토큰
    (하/되/어떻 등)이 전역형 질문을 주제형으로 오판시키는 것을 태그 수준에서
    차단한다(round-2 R-006). 교집합은 여전히 동일 함수의 canonical 형태 공간이다.
    """
    global _kiwi
    if not text or not text.strip():
        return set()
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
    if nouns_only:
        return {
            t.form.lower() for t in _kiwi.tokenize(text)
            if t.tag[0] == "N" or t.tag in ("SL", "SN")
        }
    return {
        t.form.lower() for t in _kiwi.tokenize(text)
        if t.tag[0] in ("N", "V", "X") or t.tag in ("SL", "SN")
    }


def extract_content_tokens(question: str) -> Set[str]:
    """이력 트리거 구문·지시어·요청 표현을 제거한 뒤 남는 주제 명사를 반환한다.
    빈 집합 = 전역형(모든 체인 대상), 비어 있지 않으면 주제형(관련도 정렬).

    문자열 제거는 명사형 트리거(이유/배경/변경 등) 담당, 태그 필터(nouns_only)는
    용언 잔재 담당 — 문자열 제거를 넓히면 Kiwi가 남은 단어를 문맥 상실로
    오분해("주기"→주+기)하는 것을 실측 확인해 역할을 나눴다.
    """
    if not question:
        return set()
    stripped = question
    for pattern in _TRIGGER_STRIP_RES:
        stripped = pattern.sub(" ", stripped)
    stripped = _DEICTIC_RE.sub(" ", stripped)
    return content_tokens(stripped, nouns_only=True)
