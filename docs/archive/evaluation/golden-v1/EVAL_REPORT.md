# PaiM 골든셋 평가 보고서

- 대상 run: `RUNID=20260719-2329`
- judge: `gpt-4.1-mini` (dev·final 통일)
- 코퍼스: `modu`, `csbot` (각 비환각 26 + 환각 4 = 30문항)
- 설계 정본: `backend/test/golden/EVAL_DESIGN.md` / 하네스: `run_eval.py`
- 측정 방식: **context 지표는 dev 실측 승격**, **생성·인용 지표는 final E0·E2-e2e
  증분**(faithfulness·response_relevancy·citation_grounding).
- 엑셀 요약: `docs/archive/evaluation/golden-v1/EVAL_REPORT.xlsx` (`export_report.py`로 재생성).

## 1. 최종 결과 (phase=final)

| 코퍼스 | 구성 | ctx_precision | ctx_recall | faithfulness | citation_grounding |
|---|---|---|---|---|---|
| modu | E0 | 0.301 | 0.981 | 0.773 | 1.000 |
| modu | E2-e2e | 0.307 | 0.981 | 0.772 | 1.000 |
| csbot | E0 | 0.340 | 0.962 | 0.786 | 1.000 |
| csbot | E2-e2e | 0.329 | 0.962 | 0.752 | 0.962 |

- **출처 추적성(citation_grounding)**: 4구성 중 3개 1.0, csbot E2-e2e 0.962 —
  답변이 유형 라벨이 아니라 **실제 출처 파일명**을 근거로 인용함이 수치로 확인.
- context_recall 0.96~0.98, faithfulness 0.75~0.79로 안정적.

## 2. 계층 기여 분석 (dev, context 지표)

| 코퍼스 | R0-sql | R0-vec | R0-both | E0 | E1 | E2-e2e |
|---|---|---|---|---|---|---|
| modu  ctx_precision | 0.087 | 0.740 | 0.083 | 0.305 | 0.328 | 0.306 |
| modu  ctx_recall | 0.808 | 0.904 | 0.981 | 0.962 | 0.981 | 0.981 |
| csbot ctx_precision | 0.147 | 0.768 | 0.110 | 0.364 | 0.338 | 0.339 |
| csbot ctx_recall | 0.596 | 0.962 | 0.110→0.962 | 1.000 | 1.000 | 0.962 |

- naive 결합(R0-both) 대비 **하이브리드(E0)가 ctx_precision을 3~4배 개선**
  (modu 0.083→0.305, csbot 0.110→0.364)하면서 recall은 0.96~1.0로 유지 —
  RRF(dense+BM25+recency) 융합·BM25 유관 선별의 효과.
- E1·E2 계층에서 context 지표는 큰 변화 없음(계층 1~3은 주로 이력·번복 정합성
  개선이 목적이며, 이는 체인 포함률·인용 등 다른 축에서 확인).

## 3. context_precision이 낮게 나온 원인 (분석)

**결론: 낮은 ctx_precision은 결함이 아니라 "구조화 사실 누락 방지"를 위한
recall 우선 검색 설계의 의도된 비용이다.**

### 근거
1. **검색 소스별 정밀도 격차** (dev):
   - 벡터만(R0-vec): **0.74~0.77** — top-5 RRF로 질문에 밀착, 정밀.
   - SQL만(R0-sql): **0.09~0.15** — 구조화 기록 검색이 저정밀.
   - naive 결합(R0-both): **0.08~0.11** — SQL이 전체를 희석.
2. **컨텍스트 구성 비대칭** (final E2-e2e 스냅샷 실측):
   - 문항당 평균 **SQL 구조화 기록 13~16행 + 벡터 청크 5개** — SQL이 컨텍스트
     수의 대부분을 차지.
3. **원인**: `mysql_search.search`는 category를 하드 필터가 아닌 소프트
   우선순위로 쓰고(경계 모호한 decision/action을 하드 컷하면 recall 하락),
   문항당 `MYSQL_TOP_N(12)`~`QA_MYSQL_ROWS_LIMIT` 범위의 행을 반환한다. 특정
   질문과 무관한 구조화 행이 다수 포함되어 `context_precision`(검색된 컨텍스트
   중 정답 관련 비율)을 떨어뜨린다. 반면 답변에 필요한 사실은 빠짐없이
   포함되므로 `context_recall`은 0.96~1.0로 높게 유지된다.

### 함의
- 이 값은 **검색 집합의 "순도"** 지표이며, 구조화 기록을 폭넓게 포함하는
  설계상 낮은 것이 자연스럽다. 최종 답변 품질은 recall(누락 없음) +
  faithfulness(근거 충실) + citation(출처 추적)이 함께 담보한다.
- 하이브리드(E0)가 naive 대비 정밀도를 3~4배 끌어올린 것은 **검색 개선이
  실제로 작동**함을 보여준다. 절대 precision이 중간대인 것은 MySQL의 포괄성 때문.
- **개선 여지(후속)**: 문항별 SQL 행 관련도 재랭킹·상한 축소로 precision을 더
  올릴 수 있으나 recall 하락 위험이 있어, 현재는 recall 우선을 선택.

## 4. 출처 추적성 상세 및 경계 사례

- citation_grounding 판정: 답변의 `(출처: 라벨)` 마커를 **검색된 출처 라벨을
  경계로 파싱**해, 실제 검색 출처를 인용했는지 1.0/0.0으로 채점(구분자·다중
  출처·저장소 repo 라벨 안전, 본문 우연 언급·유형 라벨·허위 출처는 0점).
- **경계 사례 — csbot A7** ("LLM 모델 최신 업데이트 이유·비용"): 답변이
  올바른 파일을 인용했으나 마커가
  `(출처: 2026-06-16_개선방안_확정.md, 2026-06-16_개선방안_확정.md 원문)`로,
  파일명 뒤에 **"원문"을 덧붙여**(구조화 기록 vs 원문 맥락 구분 의도) 정확한
  라벨이 아니게 되어 엄격 파서가 0점 처리. **실제 파일은 추적 가능하므로
  사람의 문서 확인에는 지장 없는 형식상 감점**이다. 재현되는 패턴은 아니며
  (답변 비결정성), 지표를 이 접미까지 관대하게 인정하면 허위 출처 오통과 위험이
  커져 현재는 엄격 기준을 유지한다.

## 5. 기타 관측 지표 (dev)

| 지표 | modu | csbot | 비고 |
|---|---|---|---|
| routing_accuracy | 0.567 | 0.533 | 관측값(라우터는 구성 독립), 다수 LLM 폴백 |
| chain_inclusion(E2-e2e) | 0.000 | 1.000 | pair old/new 문구가 검색 컨텍스트에 포함됐는지 검사 — **이력 라우팅 작동 여부가 아님** |
| abstain_rate | 1.000 | 0.75~1.0 | 환각 문항 기권률 |

- `routing_accuracy`·`chain_inclusion`은 합격 조건이 아닌 **관측 지표**다.
- `chain_inclusion`은 이력 로직 작동 지표가 아니다: 문구가 일반 검색으로 들어와도
  통과한다(csbot 1.0이 그 경우 — §8). modu 0.0은 문구 미포함. 이력 라우팅이
  실제로 켜졌는지는 §8(이력 감지 재현율 0%)로 판단한다.

## 6. 한계

- `context_precision`은 recall 우선 검색 설계상 낮게 나오는 순도 지표다(§3).
- `citation_grounding`은 마커 형식에 엄격하다(§4의 A7 경계 사례).
- 답변 생성 비결정성으로 인용 수치가 소폭 변동한다(직전 run에선 modu C10이
  0.962였으나 본 run에선 1.0).
- `routing`·`chain`은 관측 지표이며 일부 문항은 LLM 폴백이라 비결정 가능.

## 7. 질문 유형별 검색 품질 (context 지표, dev)

> **주석**: 이 표는 **검색 정확도 확인**을 위해 검색 품질 지표
> (context_precision/recall)만 유형별로 정리한다. 이 지표들은 답변 생성 없이
> 검색 결과 ↔ 정답 비교만으로 측정되므로 R0-sql/vec/both·E0·E1·E2-e2e 6구성
> 전부 존재한다. 반면 생성 지표(faithfulness·response_relevancy·
> citation_grounding)는 답변 생성이 필요하고 설계상 final E0·E2-e2e에서만
> 측정하므로, R0×3·E1에는 없어 **"-"로 처리**한다(hallucination 태그는 RAGAS
> 대상이 아니라 제외 — 기권률로 별도 측정). 엑셀 `유형별검색품질` 시트 참조.

**modu — context_precision**

| config | decision | conflict | conflict_negative | action |
|---|---|---|---|---|
| R0-sql | 0.053 | 0.074 | 0.389 | 0.073 |
| R0-vec | 0.820 | 0.592 | 0.878 | 0.606 |
| R0-both | 0.052 | 0.091 | 0.341 | 0.063 |
| E0 | 0.309 | 0.365 | 0.535 | 0.178 |
| E1 | 0.332 | 0.428 | 0.596 | 0.161 |
| E2-e2e | 0.301 | 0.412 | 0.547 | 0.166 |

**modu — context_recall**

| config | decision | conflict | conflict_negative | action |
|---|---|---|---|---|
| R0-sql | 0.750 | 0.875 | 1.000 | 0.833 |
| R0-vec | 0.964 | 0.750 | 1.000 | 0.833 |
| R0-both | 1.000 | 1.000 | 1.000 | 0.917 |
| E0 | 1.000 | 0.875 | 1.000 | 0.917 |
| E1 | 1.000 | 1.000 | 1.000 | 0.917 |
| E2-e2e | 1.000 | 1.000 | 1.000 | 0.917 |

**csbot — context_precision**

| config | decision | conflict | conflict_negative | action |
|---|---|---|---|---|
| R0-sql | 0.170 | 0.122 | 0.188 | 0.074 |
| R0-vec | 0.749 | 0.750 | 0.944 | 0.766 |
| R0-both | 0.107 | 0.103 | 0.198 | 0.090 |
| E0 | 0.369 | 0.651 | 0.434 | 0.277 |
| E1 | 0.367 | 0.607 | 0.333 | 0.212 |
| E2-e2e | 0.360 | 0.592 | 0.426 | 0.208 |

**csbot — context_recall**

| config | decision | conflict | conflict_negative | action |
|---|---|---|---|---|
| R0-sql | 0.382 | 1.000 | 1.000 | 1.000 |
| R0-vec | 0.941 | 1.000 | 1.000 | 1.000 |
| R0-both | 0.941 | 1.000 | 1.000 | 1.000 |
| E0 | 1.000 | 1.000 | 1.000 | 1.000 |
| E1 | 1.000 | 1.000 | 1.000 | 1.000 |
| E2-e2e | 0.941 | 1.000 | 1.000 | 1.000 |

- 생성 지표(faithfulness/relevancy/citation)는 R0×3·E1에서 미측정 → "-".
  final E0·E2-e2e 값은 §1·§4 참조.

## 8. 질문별 라우팅 감사 — 이력 라우팅 필요/불필요 (dev)

**이력(history_mode) 라우팅이 필요한 질문(expected_history=True)이 실제로
감지됐는지, 불필요한 질문(False)이 잘못 라우팅됐는지**를 정리한다.
`history_mode`는 정규식(`detect_history_intent`)으로 결정론적으로 판정되며
(LLM은 route 분류만 담당, history를 켜지 못함), 이 미탐 결과는 재현된다
(관측 지표, 합격 조건 아님). 엑셀 `라우팅감사` 시트에 문항별 전체(60행,
`mismatch` 열로 필터) 수록.

| 코퍼스 | 필요(True) | 감지(TP) | **미탐(FN)** | 불필요(False) | **오탐(FP)** |
|---|---|---|---|---|---|
| modu | 4 | 0 | **4** — conflict B1·B2·B3·B7 | 26 | 1 — B4(conflict_negative) |
| csbot | 1 | 0 | **1** — conflict B4 | 29 | 1 — A3(decision) |

- **핵심 발견**: 이력 라우팅이 필요한 conflict 질문을 **하나도 감지하지 못했다
  (재현율 0%)**. 오탐(불필요한데 감지)은 각 코퍼스 1건씩(modu B4 대조군, csbot A3).
- **원인 규명**: 이력 감지(`detect_history_intent`)는 **정규식 기반 결정론적**
  판정이다. "어떻게 **바뀌었는가**"·"제외됐다가 다시 포함" 같은 conflict 표현이
  현재 트리거에 안 걸려(**recall 부족**) 미탐된다. 즉 재현성 문제가 아니라
  **감지 규칙의 recall 문제**다(LLM은 route만 정하고 history를 켜지 못하므로,
  이력 라우팅은 전적으로 이 정규식 recall에 달려 있다).
- **chain_inclusion과의 관계(중요)**: measure의 `chain_inclusion`(csbot 1.0)은
  이력 라우팅이 켜졌음을 뜻하지 **않는다**. 이 지표는 pair의 old/new 문구가
  검색 컨텍스트에 있는지만 검사하는데, 그 문구는 **일반 하이브리드 검색으로도
  들어온다**(csbot B4: old "도입 여부"가 `issue` 행, new "정식 도입"이
  `decision` 행으로 각각 검색돼 통과 — history_mode=False인데도). 따라서 audit
  미탐과 chain_inclusion=1.0은 **모순이 아니라 서로 다른 것을 측정**한 결과다.
- 개선은 트리거 정규식 확장으로 가능하다(결정론적이라 튜닝 후 recall 즉시 측정).
  **이력 감지 개선 = TASK-008(선행)**, 그 위에서 supersede correctness 검증 =
  **TASK-009**로 분리한다.

## 9. 분석 노트 (세션 중 확인 사항)

이 보고 수치를 사용자와 함께 해석하며 확인한 사항을 정리한다(후속 판단 근거).

1. **context_precision이 낮은 것은 결함이 아니다**(§3). R0-sql은 질문과 무관하게
   구조화 기록 **전체 테이블을 덤프**하고(modu 105행·csbot 53행, 문항 불문 동일),
   하이브리드도 문항당 SQL ~13-16 + 벡터 5로 SQL이 75%를 차지 → recall 우선
   설계의 정밀도 희석. R0-both→E0에서 정밀도 3~7배 개선(검색 개선 작동).
2. **recall이 하이브리드 필요성의 핵심 증거**. SQL만·벡터만은 서로 다른 정보를
   놓친다: csbot decision recall 0.382(SQL만)→1.0(하이브리드), modu conflict
   recall 0.750(벡터만)→1.0(E1부터). precision과 달리 recall은 "전체 덤프" 왜곡이
   없어 신뢰할 수 있는 지표다.
3. **유형별 패턴**: R0-both→E0 정밀도가 전 유형 상승(conflict 최대: csbot
   0.10→0.65). modu conflict recall이 E0에서 0.875로 잠깐 하락→E1에서 1.0 회복 =
   **계층 1·2(supersede 승인)가 작동한다는 증거**. conflict_negative는 recall이
   전 구성 1.0으로 안정(대조군 정보 누락 없음).
4. **E1·E2 도입을 현재 지표로는 정당화하기 어렵다**. 5개 축은 전부 "컨텍스트에
   근거했는가"만 재고 "옛 결정 vs 최신 결정 중 맞는 것을 골랐는가"는 못 본다.
   → 신규 LLM-judge 지표 `supersede_correctness`(E0/E1/E2 비교)를 **TASK-009**로
   분리(이력 감지가 선행돼야 유효 — 아래 5번).
5. **이력 감지 recall 부족**(§8): `detect_history_intent`(정규식)가 conflict
   표현("바뀌었는가" 등)을 못 잡아 재현율 0%(결정론적, 비결정 아님). LLM은
   route만 정하고 history를 켜지 못하므로 이력 라우팅은 이 정규식 recall에
   전적으로 달려 있다. `chain_inclusion`은 라우팅 작동과 무관(문구 포함 검사)
   하므로 이력 로직 지표로 쓸 수 없다. → 이력 감지 개선을 **TASK-008**로 선행,
   그 위에서 supersede correctness 검증은 **TASK-009**.
6. **conflict_negative faithfulness 하락**(final, E0→E2-e2e: modu 0.83→0.59,
   csbot 0.86→0.61) — 이력 모드가 대조군(번복 아님)에서 번복 서사를 과잉
   생성할 가능성. TASK-009(supersede correctness) 관전 포인트.
7. **citation_grounding 경계 사례 A7**(§4), **CSV utf-8-sig 인코딩**(Excel 한글
   호환), **추적 스냅샷**(답변·SQL/벡터 근거·인용 로컬 저장)으로 오프라인 검수
   가능.

## 10. 산출물 · 재현

- `results/summary.csv`(citation_grounding 포함), 문항별 상세
  `results/ragas_<corpus>_<config>_<phase>_<runid>.csv`,
  `results/METHODS_20260719-2329.md`.
- 추적 스냅샷(로컬 전용, gitignore): `.eval_state/contexts_*.jsonl` —
  문항별 답변·SQL/벡터 근거·인용·LLM 입력 전문.
- 엑셀 요약: `docs/archive/evaluation/golden-v1/EVAL_REPORT.xlsx`.
- 재현:
  ```bash
  RUNID=20260719-2329
  .venv/bin/python backend/test/golden/run_eval.py all --corpus modu  --phase dev  --runid $RUNID
  .venv/bin/python backend/test/golden/run_eval.py all --corpus csbot --phase dev  --runid $RUNID
  bash .agent-workflow/tasks/TASK-007/remeasure-task007.sh   # final 생성·인용 증분
  .venv/bin/python backend/test/golden/export_report.py      # → docs/archive/evaluation/golden-v1/EVAL_REPORT.xlsx
  ```
