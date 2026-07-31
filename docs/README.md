# PaiM 문서 인덱스

> 정리 기준: `main` `d13baba`, 최신 설치본 `v1.0.7`, 2026-07-31

현재 제품 계약은 이 인덱스의 **현재 문서**를 우선합니다. `archive/`는 당시의
판단과 평가 결과를 재현하기 위한 기록이며, 현재 API·배포 계약으로 사용하지 않습니다.

## 현재 정본

| 영역 | 문서 |
| --- | --- |
| API | [FastAPI 명세서](API_명세서.md) · [HTML](API_명세서.html) |
| 시스템 구조 | [아키텍처](ARCHITECTURE.md) |
| Agentic Q&A | [MVP 검증 기준](AGENTIC_QA_MVP_VALIDATION.md) · [실행 경로·평가 가이드](PR18_QA_PATH_AND_EVAL_GUIDE_20260729.md) |
| 제품 정책 | [policies/](policies/) |
| 남은 작업 | [planning/](planning/) |
| 프론트엔드 전달 계약 | [handovers/frontend/](handovers/frontend/) |
| 검증 결과 | [reports/validation/](reports/validation/) |
| 필수 산출물 | [deliverables/](deliverables/) |

API 명세서·아키텍처·Agentic Q&A 문서 네 편은 자동 테스트와 진행 중인 성능개선
변경의 경로 계약을 유지하기 위해 이번 정리에서 루트에 두었습니다. 관련 변경이
병합된 뒤 경로를 옮길 때는 테스트·생성 스크립트·문서 링크를 함께 수정해야 합니다.

## 디렉터리 기준

- `policies/`: 현재 제품 동작을 규정하는 정책과 데이터 계약
- `planning/`: 아직 닫히지 않은 후속 과제와 실행 계획
- `handovers/`: 다른 담당자가 구현할 때 따라야 하는 API·UI 계약
- `reports/`: 현재 코드에 대한 검증 결과
- `deliverables/`: 제출용 요구사항·화면·구성도·테스트 산출물
- `archive/`: 완료된 통합, 과거 평가, 낡은 로드맵과 핸드오버

## 문서 판정 우선순위

1. 실행 코드와 자동 테스트
2. 이 인덱스에 연결된 현재 정본
3. 현재 검증 보고서
4. `archive/`의 과거 자료

문서와 코드가 다르면 코드 동작을 먼저 확인하고 정본 문서를 갱신합니다. 과거 평가
수치는 같은 커밋·데이터·모델 조건을 재현할 수 있을 때만 비교 기준으로 사용합니다.
