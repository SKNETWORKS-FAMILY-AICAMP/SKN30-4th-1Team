# 골든셋 평가 설계 (계층 4 — TASK-006 예정)

- 작성: 2026-07-17 / 개정 v2: Codex 라벨 리뷰(`codex-label-review.log`) 반영 —
  라벨 16건 수정 + 설계 결함 6건 정정
- 목적: supersede 계층 1~3(PR #50·#51로 main 반영)이 검색 품질을 실제로
  개선했는지 수치로 증명하고, 회귀를 감지한다. 로드맵 #2의 계층 4.

## 1. 골든셋 데이터

| | Test_modu | Test_CS-Bot |
|---|---|---|
| 코퍼스 | 회의록 10편 (2026-03-02~05-15, Modu 앱 출시) | 회의록 5편 (2026-06-02~06-27, CS봇 유지보수) |
| QA셋 | `qa_set_Modu.json` 30문항 | `paim_qa_testset.json` 30문항 |
| 참조 | `modu_rag_qa_testset_and_person_timeline.md` (인물 타임라인 포함) | `Test1_CS-Bot_유지보수_프로젝트 회의록.html` |

QA 스키마: `{id, set(A/B/C), tag, question, answer(골든 답), source(출처 회의록)}`
- A세트: 기본 사실 + 결정 이유 (decision)
- B세트: 결정 변경·충돌 추적 — 코퍼스에 번복 스토리 내장
  (예: modu 3/9 이메일 로그인 결정 → 3/23 소셜 로그인으로 번복)
- C세트: 담당자 추적 (action 12) + 문서에 없는 정보 (hallucination 8)
- **conflict_negative 4문항 (음성 대조군)**: modu B4·B10, csbot B3·B7 —
  번복처럼 보이지만 실제로는 유지·재확인·구체화인 케이스. 판정 기준은
  "구 결정의 내용이 신 결정으로 대체되어 무효가 됐는가"(사전 리스크 논의
  유무가 아님 — 현실의 번복은 대부분 사전 논의를 거치므로). 검증 목적:
  ① supersede 판별기가 오제안하지 않는지(정확도>재현율), ② 답변이 충돌을
  지어내지 않는지. csbot B3 골든 답은 이 기준으로 수정 완료(2026-07-17,
  사용자 승인: "입장 동일 — 조건부 재검토 방침의 구체화").

## 2. 측정 구성 (코퍼스별 반복)

| 구성 | 검색 방식 | history | recency | 성격 |
|---|---|---|---|---|
| R0-sql | 구조화 기록(SQL)만 | — | — | 초기 소스별 진단 (병렬) |
| R0-vec | dense 코사인 top-k만 | — | — | 초기 소스별 진단 (병렬) |
| R0-both | 두 소스 단순 결합 | — | — | **초기 모델 베이스라인** |
| E0 | 현 하이브리드(`_build_context`) | off | **0** | supersede 미적용 |
| E1 | 〃 | off | **0** | + 계층 1·2 (골든 pair 승인) |
| E2 | 〃 | on | **0.2** | + 계층 3 전체 |

- **단계 기여 비교는 `R0-both → E0 → E1 → E2` 선형 구간에만 적용**한다.
  R0-sql/R0-vec은 선형 단계가 아니라 초기 시스템의 소스별 성능 진단(병렬)이다.
- E0·E1은 `CHUNK_RECENCY_WEIGHT=0`으로 계층 3의 recency 축까지 끈다(현
  `_build_context` 기본값이 0.2이므로 평가 스크립트에서 명시적으로 0 덮어쓰기).
- R0-\*는 **현 코퍼스·현 추출 결과 위에서 초기 검색 전략을 재현**한 것(실제 초기
  커밋 실행 아님 — 보고서에 명시). 초기의 "LLM이 소스 선택" 라우터는 재현하지
  않는다(세 모드 개별 측정이 상한 포함 더 많은 정보).
- **E2의 history_mode 적용은 이중 측정**:
  - E2-e2e (기본): 실제 `classify_question` 감지 결과대로 — 서비스 그대로의
    end-to-end 성능. 발표 수치는 이것.
  - E2-oracle (보조): `expected_history_mode=True` 문항(5개)만 강제 on —
    감지 실패와 체인 품질을 분리 진단. e2e와의 델타 = 감지 미탐의 비용.
- 예상 시나리오: E1은 A세트 상승·B세트 하락 가능(구 결정 숨김) → E2가 B세트를
  회복하는지가 핵심 관전 포인트.

## 3. 측정 축 (5개)

1. **RAGAS 검색 품질** (비환각 52문항 = A·B 40 + C-action 12, × 6구성):
   context_precision / context_recall, LLM judge(gpt-4.1-mini, 최종 보고 시 상향 — 2026-07-20 4o-mini RPD 소진으로 4.1 계열 교체).
   LangSmith experiment로 기록해 웹에서 구성 간 비교. 경량 모드 기본, 생성
   지표(faithfulness 등)는 최종 보고 시 E0·E2만.
2. **라우팅 감사** (60문항): `classify_question()` 직접 호출 결과
   `{route, router_stage, history_mode}`를 `routing_expected.json`과 대조.
   - 기대 라벨은 `expected_route`·`expected_history_mode`만. `router_stage`는
     **관측값으로만 기록**(기대 라벨 아님) — 정규식 기준 60문항 중 다수(~45)가
     LLM 폴백이라 비결정 가능성을 stage로 식별한다.
   - rule/history_rule 분기는 LLM 호출이 없어 LangSmith 트레이스에 안 남으므로
     반드시 직접 수집.
3. **B세트 이력 체인 포함률** (E2, 결정론): history 기대 문항(5개)에서
   `debug.history_rows_added`·기대 결정 포함 여부 단언.
4. **환각 기권률** (hallucination 8문항): 응답의 "기록에서 확인되지 않는다" 류
   기권 표현 비율.
5. **출처 추적성(인용 근거성)** (final E0·E2-e2e, 비환각 답변, 결정론·LLM 비용
   0, TASK-007): 답변이 근거의 실제 출처를 `(출처: 라벨)` 마커로 인용했는지.
   - 라벨은 충돌 없는 식별자 — 문서는 파일명, 저장소 파일은 `repo#N` 접미로
     동명 충돌 방지. 검색된 출처 라벨 집합의 **완전 마커 리터럴 등장**만 근거로
     인정(파일명에 구분자가 있어도 안전, 본문 우연 언급·부분문자열은 불인정).
   - 근거 있는 인용을 제거한 뒤에도 `(출처:` 가 남으면 허위 출처/유형 라벨
     오용이므로 0점. 문항별 1.0/0.0 → 코퍼스 평균 `citation_grounding`.
   - 실서비스와 동일한 렌더링 컨텍스트로 답변을 생성해야 유효하다(§3주 참고).

> 주(TASK-007): 답변 생성은 `_build_context`의 **렌더링 컨텍스트**(출처 마커
> 포함)로 수행한다. RAGAS 검색 지표(1축)에는 마커 없는 원문 청크를 그대로
> 쓰므로 context_precision/recall은 영향받지 않는다. E2-e2e는 실서비스
> (`qa_tools.search_project_evidence`)와 동일하게 `[프로젝트 메모리]` 접두를 조립하며, 이를 위해
> ingest 단계에서 프로젝트 메모리 요약을 생성한다(무출처 요약이라 인용 근거
> 집합에는 더해지지 않음).

## 4. 기대 라우팅 라벨 (`routing_expected.json`, 리뷰 반영 v2)

- 라벨 원칙: **현재 감지기의 동작이 아니라 서비스 설계상 정답 경로** 기준.
- `expected_route`: **전 문항 semantic (60/60)** — C세트 담당자 질문은 역방향
  ("이 작업을 누가?")이라 내용으로 행을 특정해야 하므로 filter_lookup
  (owner/category/마감 순방향 필터)로는 답을 만들 수 없다(리뷰에서 10문항
  정정). filter_lookup 순방향 문항은 비검색 경로 트랙(§6)으로 — 초안 6문항은
  `nonsearch_track_draft.json`에 보관.
- `expected_history_mode=True` 5문항: modu B1(로그인 방식 변화)·B2(출시일
  최초→최종)·B3(연기 근본 원인 연쇄)·B7(소셜 로그인 제외→포함), csbot
  B4(re-ranking 입장 변화). 코퍼스의 실제 supersede 관계(결정 → 대체 결정)가
  있는 질문만 True — 유지·재확인·쟁점→결정 구체화·지표 추이는 False
  (리뷰에서 5문항 강등).
- 트리거 어휘 없는 이력 문형(modu B1 "어떻게 바뀌었는가", B3 등)은 현 감지기
  미탐 예상 — 라벨은 True 유지(감사의 목적), note에 표기.

## 5. 상태 재현 절차 (E0→E1 결정론 보장)

"supersede 제안 무검수 일괄 승인"은 LLM 판별 결과에 따라 상태가 달라져 재현이
깨진다. 대신:

1. **골든 supersede pair 명시**: 코퍼스별 기대 번복 관계(구 결정 내용 ↔ 신 결정
   내용)를 `golden_supersede_pairs.json`으로 고정 (modu: 이메일 로그인→소셜
   로그인 등, 코퍼스 검토로 작성). **negative pair도 포함**: csbot 파인튜닝
   (6/16 vs 6/27)은 번복처럼 보이지만 동일 방침의 구체화 — 판별기가 이 pair를
   supersede로 오제안하지 않는지 검증(정확도>재현율 원칙).
2. E1 전환 스크립트는 적재된 memory 행을 내용 매칭으로 찾아 **골든 pair만**
   `superseded_by`를 직접 설정(승인 API 경로 재사용). LLM 판별기의 제안이
   골든 pair를 얼마나 커버했는지는 **계층 2 판별기 성능 지표로 별도 기록**
   (평가 부산물).
3. 코퍼스 적재는 일회용 DB(스모크 테스트 패턴)에서 수행, 적재→E0 측정→pair
   적용→E1 측정→E2 측정 순서를 스크립트로 고정.

## 6. 범위 밖 (후속 태스크로 분리)

- **비검색 경로 트랙 (overview + filter_lookup)**: 두 경로 모두 semantic 검색을
  안 하므로(SQL 집계/필터 조회) RAGAS 부적합 — 결정론 검사 전용의 별도
  태스크로 분리. 본 트랙의 "RAGAS = semantic 검색 품질 / 결정론 = 비검색 경로"
  원칙에 따른 분류.
  - overview: 신규 4문항 + 필수/금지 요소 체크리스트(번복된 구 결정이 현재형
    노출되면 실패), supersede 승인 전/후 2회 측정.
  - filter_lookup: 순방향 문항 초안 6개 작성 완료(`nonsearch_track_draft.json`) —
    라우팅 감사 + 템플릿 답변의 담당자 이름 포함 검사.
- 감지기 어휘 튜닝: 본 평가의 미탐 목록을 재료로 후속 진행.

## 7. 산출물 형태 (2026-07-17 확정, 07-18 plan v3·v4 반영 보완)

phase 계약: `dev`(lite, judge gpt-4.1-mini — 개발 반복용) / `final`(보고용 —
생성 지표(faithfulness·relevancy)를 E0·E2-e2e 한정 증분, context 지표는 dev
실측 승격(judge 통일 gpt-4.1-mini — 2026-07-20 전환, implementation-report 참조),
환각 기권 생성은 양 phase 동일 수행). 보고서 수치는 **phase=final**.

1. **`results/summary.csv`** — 기계가 읽는 단일 원천. 키
   `(run_id, corpus, config, phase)` upsert(주 구성 6종 × 2코퍼스 = phase당
   12행): `run_id, date, commit, corpus, config, phase, judge, n,
   context_precision, context_recall, faithfulness, response_relevancy,
   citation_grounding, routing_accuracy, history_detect_rate,
   chain_inclusion_rate, abstain_rate`.
   (`citation_grounding`은 생성 지표를 측정한 구성 = final E0·E2-e2e에서만 채워짐.)
   같은 키에 다른 judge 기록은 거부(--overwrite로만 교체).
2. **`results/ragas_<corpus>_<config>_<phase>_<runid>.csv`** — 문항별 상세(점수).
   추적용 전문 스냅샷은 `.eval_state/contexts_*.jsonl`(로컬 전용, gitignore):
   문항별 `question·response(답변 원문)·citation_grounding·source_labels`와
   **SQL 구조화 기록(sql_contexts)·벡터 원문 청크(vector_contexts)를 출처 라벨과
   함께 분리 저장** — LangSmith 없이 답변·검색 근거·인용을 오프라인 확인.
3. **`results/oracle_<corpus>_E2-oracle_<phase>_<runid>.csv`** — E2-oracle 보조
   측정(summary 12행 계약 밖 — 감지 실패와 체인 품질의 분리 진단 전용).
4. **`results/routing_audit_<corpus>_<phase>_<runid>.csv`** — 코퍼스별 30문항
   기대/실제 경로·stage 대조. 미탐·오탐 목록의 원천.
5. **`results/pair_coverage_<corpus>_<phase>_<runid>.csv`** — 계층 2 판별기의
   골든 pair 적중(hit)/미제안(miss)/오류(error)·negative 오제안(관측 지표).
6. **`docs/EVAL_REPORT.md`** — 사람이 읽는 종합 보고(발표 수치 원천): 요약 →
   매트릭스 표·단계 기여 → 세트별 분해(양성 5 vs 음성 4) → 라우팅 감사 →
   체인 포함률(+e2e/oracle 델타) → 기권률 → 판별기 pair 커버리지 → 한계 →
   재현 커맨드.
- git: results/*.csv와 EVAL_REPORT 커밋, `.eval_state/`(체크포인트·덤프·컨텍스트
  전문·마커)는 로컬. LangSmith experiment 이름
  `golden-<corpus>-<config>-<runid>`로 summary와 상호 추적.

## 8. 파이프라인 요구 (사용자 수동 재실행 전제)

- 단일 진입점 CLI (`backend/test/golden/run_eval.py`)로 서브커맨드화:
  적재(ingest) / 상태 전환(supersede pair 적용) / 구성별 측정(measure) /
  라우팅 감사(audit) / 요약 집계(report). 전 단계 일괄 실행(all)도 제공.
- 사용법 문서 `backend/test/golden/README.md` — 사전 조건(일회용 DB·API 키),
  전체/단계별 실행 예시, 산출물 위치, 자주 쓰는 재실행 시나리오.
- **적재 1회·측정 N회 원칙**: 추출(extract)이 LLM 기반이라 재적재마다 memory
  행이 달라진다 → 코퍼스 적재는 1회 수행 후 DB 상태를 고정하고, 전 구성을
  같은 상태에서 측정. 적재 결과(행 덤프)를 runid에 귀속해 저장, 재현 시 참조.

## 9. 알려진 하네스 결함 (TASK-006에서 수정)

- `rag_eval.py`·`rag_eval_langsmith.py`가 현 엔진에 없는
  `qa_engine.CHROMA_MAX_DISTANCE`를 참조 → 실행 즉시 AttributeError.
- `rag_eval.py`의 `collect()`는 실서비스 경로(`_build_context`)를 타지 않는 자체
  재구현(하이브리드 이전) — E0~E2 측정에는 실경로 호출로 교체, R0 재현에는
  이 패턴 재사용.
- 하드코딩 `TESTS` → 골든 JSON 로더로 교체.
- 기존 로드맵 수치 0.571은 옛 코퍼스(project 6) + 하이브리드 이전 검색 기준이라
  새 골든셋 수치와 직접 비교 불가(보고서에 명시).
