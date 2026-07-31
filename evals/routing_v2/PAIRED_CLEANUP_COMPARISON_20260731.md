# PR #41 후속 정리 paired 평가

## 실행 조건

- 기준: `416a6d17b3047fe258e2451133d3c35ab06678a8`
- 후보: `cef61143bed0e5ec818686d9d670db452eb7a953`
- 데이터: 동일한 격리 MySQL(`127.0.0.1:3316`)·Chroma snapshot
- 모델: 공식 OpenAI `gpt-4.1-mini`, temperature 0
- Judge: `gpt-4.1`, temperature 0
- 질문: `routing_v2` 40개(CS-Bot 21, Modu 19)
- 두 실행 모두 별도 clean worktree에서 수행했고 raw 결과의
  `working_tree_dirty`는 `false`다.

## 결과

| 지표 | 기준 | 후보 | 변화 |
|---|---:|---:|---:|
| HTTP 성공 | 40/40 | 40/40 | 동일 |
| Tool 계약 | 39/40 | 39/40 | 동일 |
| 엄격 PASS | 24/40 (60.0%) | 24/40 (60.0%) | 동일 |
| PASS+PARTIAL | 38/40 (95.0%) | 37/40 (92.5%) | -1문항 |
| 현재 DB 상태 보정 PASS | 26/40 (65.0%) | 26/40 (65.0%) | 동일 |
| 평균 지연 | 4480.7ms | 4233.5ms | -5.5% |
| 중앙 지연 | 4295.1ms | 4522.6ms | +5.3% |
| p95 지연 | 9026.3ms | 6967.0ms | -22.8% |
| 최대 지연 | 9240.7ms | 8780.9ms | -5.0% |

Tool 계약에서 빠진 문항은 양쪽 모두 `V2-SEM-06`이다. 두 작업의 담당자를
정확히 답했지만 허용 목록 밖의 선행 structured 조회를 한 뒤 두 번 검색해 계약만
실패했다.

## 한 문항 변동 조사

후보의 `V2-OV-13`이 PARTIAL 대신 FAIL로 판정돼 PASS+PARTIAL이 한 문항 낮아졌다.
이 문항은 golden의 `issue=18`, `risk=6`과 현재 격리 DB의 `issue=19`, `risk=7`이
이미 어긋나 있다.

- 양쪽 실행에서 이 문항의 Tool context SHA-256은
  `0292cc93c78f4d0cc76c39d3d4ff73d5682b711da5897a5bb552b6c699a34a08`로 같다.
- 전체 문항의 HTTP·Tool 계약·Tool 결과 상태를 정규화한 SHA-256도 양쪽 모두
  `d6ea97c79d17694a1123a3d74e0d4ffe19d2b6ab44110c92241475884840dee8`로 같다.
- 해당 문항을 각 SHA에서 추가로 3회씩 실행하자 두 SHA 모두 간결형과 상세형
  답변 변동이 재현됐다.
- 기준과 후보 사이의 일반 `/query` 프롬프트·Tool 실행·결과 수집 로직에는 차이가
  없다. 후보의 `agentic_graph.py` 변경은 세션 전용 인자와 사용되지 않는 지역 변수
  제거뿐이다.

따라서 한 번의 생성 길이 차이는 이번 정리로 생긴 결정론적 회귀가 아니라 외부 모델
출력 변동으로 판정한다. `routing_v2` 범위에서는 정확한 Tool 경로와 엄격 PASS가
유지됐고 평균·p95·최대 지연도 낮아져 성능 저하 증거가 없다.

## 정본 `agentic_v2` 차단 사항

정본 `evals.agentic_v2.pipeline run → score → compare`는 이번에 임의로 실행하지
않았다. 저장소에 필요한 formal state와 paired baseline이 없고, 현재 공개 dev
질문 일부가 남아 있는 로컬 state 및 Tool 계약과 모순되기 때문이다.

- `evals/results/agentic_v2/state/{modu,csbot}/manifest.json`과 봉인된 Chroma
  snapshot이 없다.
- `M-STR-01`은 severity 필터가 없는 전체 issue count Tool로 정확히 2건을
  요구하지만 현재 Modu 활성 issue는 19건이다.
- `M-STR-03`, `C-STR-03`은 unknown action을 요구하지만 현재 격리 state에는
  unknown action이 0건이다.

이 상태에서 manifest를 임의 작성해 실행하면 코드 성능이 아니라 잘못된 데이터
계약을 측정하게 된다. 따라서 위 paired `routing_v2` 결과는 실제 Tool 기본 회귀
근거이며, formal 승인 결과를 대신하지 않는다.
