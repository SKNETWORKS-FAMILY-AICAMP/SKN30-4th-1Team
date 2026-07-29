# 골든셋 평가 파이프라인 사용법 (TASK-006, 계층 4)

supersede 계층 1~3이 검색 품질을 개선했는지 골든셋(60문항, 2코퍼스)으로 측정한다.
설계 근거·구성 정의는 `EVAL_DESIGN.md`, 결과 해석은 `docs/EVAL_REPORT.md` 참조.

## 사전 조건

- **Docker** — 일회용 MySQL 컨테이너(`paim-eval-db`, `127.0.0.1:3316`에만 바인딩)를
  띄운다. 기존 개발용 DB(`paim-mysql`, 3306)와 완전히 분리. 컨테이너 안에서
  코퍼스마다 **별도 스키마**(`paim_modu`/`paim_csbot`)를 만들어, 전체-DB
  스냅샷/복원이 다른 코퍼스 행을 건드리지 않게 격리한다.
- **eval 의존성** — RAGAS 채점은 `eval` dependency group(ragas 0.4.x)이 필요:
  `uv sync --group eval` (평상시 `uv sync`는 eval을 설치하지 않음 — dev 환경을
  가볍게 유지하기 위한 의도적 분리). ragas가 langchain-community 0.4에서 제거된
  vertexai 모듈을 임포트하는 문제는 run_eval.py가 내부 shim으로 우회한다.
- **OPENAI_API_KEY** — 필수. 적재(추출 LLM)·임베딩·RAGAS judge 전부 OpenAI 호출.
  **파일이 아니라 환경변수로 주면**(`export OPENAI_API_KEY=...`) scope 검사(시크릿
  파일 차단)와도 충돌하지 않는다. 리포 루트 `.env`도 로드되지만 `.env` 파일이
  working tree에 있으면 `check-scope.sh`가 (의도적으로) 실패한다.
  (`check-scope.sh`·`verify-backend.sh`는 저장소에 없는 **개인 워크플로 도구**다.
   `.gitignore`의 `/scripts` 대상이며 외부에서 제공된다.)
- **LANGSMITH_API_KEY** — 선택. 있으면 experiment `golden-<corpus>-<config>-<runid>`
  로 기록. 없거나 `--no-langsmith`면 로컬 CSV만으로 완주.
- 실행은 리포 루트에서: `.venv/bin/python backend/test/golden/run_eval.py <명령>`

## 최초 전체 실행 (코퍼스당 1커맨드)

```bash
RUNID=$(date +%Y%m%d-%H%M)
.venv/bin/python backend/test/golden/run_eval.py all --corpus modu  --phase dev --runid $RUNID
.venv/bin/python backend/test/golden/run_eval.py all --corpus csbot --phase dev --runid $RUNID
# 파이프라인 검증(dev) 후 보고용 최종 측정:
.venv/bin/python backend/test/golden/run_eval.py all --corpus modu  --phase final --runid $RUNID
.venv/bin/python backend/test/golden/run_eval.py all --corpus csbot --phase final --runid $RUNID
```

`all`이 강제하는 순서: `db-up → ingest → checkpoint(pre-pairs) →
[R0-sql·R0-vec·R0-both·E0 측정] → pairs(E1 전환) → [E1·E2-e2e·E2-oracle 측정]
→ audit → report`. final은 시작 시 `restore`로 pre-pairs 상태로 되돌린 뒤 같은
순서를 실행한다. final judge는 dev와 동일한 gpt-4.1-mini다(보고 수치가 한
judge를 공유하도록 — 2026-07-20 dev 승격 방식으로 전환, 아래 phase 표 참조).

## phase 구분

| phase | judge | 용도 |
|---|---|---|
| `dev` (기본) | gpt-4.1-mini | 파이프라인 검증·개발 반복 — 저비용 |
| `final` | gpt-4.1-mini | **보고서·발표 수치** — context 지표는 dev 승격, 생성 지표(faithfulness·relevancy)·출처 추적성(citation_grounding)만 E0·E2 증분 |

출처 추적성(`citation_grounding`, TASK-007): 답변이 근거의 실제 출처를
`(출처: 파일명)` 마커로 인용했는지(유형 라벨·허위 출처·본문 우연 언급은 0점).
final E0·E2-e2e에서 실서비스와 동일한 렌더링 컨텍스트로 답변을 생성해 측정한다.

summary는 `(run_id, corpus, config, phase)` 키로 분리 기록되므로 dev/final이
서로 덮어쓰지 않는다. 같은 키에 다른 judge로 다시 쓰려면 `--overwrite` 필요.

## 단계별 재실행 시나리오

```bash
P=".venv/bin/python backend/test/golden/run_eval.py"

# 구성 1개만 다시 측정 (예: E2만)
$P measure --corpus modu --config E2-e2e --phase dev --runid <RUNID>

# 라우팅 감사만 다시
$P audit --corpus modu --phase dev --runid <RUNID>

# pair 적용 후에 R0/E0을 다시 측정하고 싶을 때: pre-pairs 상태로 복원
$P restore --corpus modu
$P measure --corpus modu --config E0 --phase dev --runid <RUNID>
$P pairs --corpus modu --runid <RUNID>     # 측정 후 다시 E1 상태로

# 중단된 all 재개 (완료 구성 건너뜀 — phase별 마커라 dev 완료가 final을 안 막음)
$P all --corpus modu --phase dev --runid <RUNID> --resume

# 코퍼스 재적재 (추출이 LLM이라 행이 달라짐 — 상태 완전 삭제 후 재생성)
$P ingest --corpus modu --force

# 전부 정리
$P db-down && rm -rf backend/test/golden/.eval_state
```

## 상태 모델 (왜 이 순서가 강제되는가)

- **적재 1회·측정 N회**: 추출(extract)이 LLM이라 재적재마다 memory 행이 달라진다.
  적재 직후 상태를 `checkpoint`(mysqldump + Chroma 스냅샷)로 고정하고, 모든
  측정은 그 상태(또는 pairs 적용 상태)에서 수행한다.
- **pre/post 상태 검사**: R0·E0은 supersede 관계 0건 + 구 결정 벡터 존재(pre),
  E1·E2는 골든 pair와 정확히 일치하는 관계 + 구 벡터 부재(post)를 전제한다.
  measure가 매번 검사해 불일치면 중단한다 — 반쪽 상태에서의 측정 오염 방지.
- **pairs 보상 복구**: 적용 실패 시 자동으로 체크포인트 복원 + 재검증까지 마친
  뒤 중단한다. 복원 자체가 실패하면 run이 `INVALID`로 봉인되며(이후 measure
  거부), `restore` 성공으로 해소된다.
- **승인 경로 동등(검색 상태)**: pairs는 `superseded_by`·`superseded_at` 설정 +
  구 결정 memory 벡터 삭제까지 수행한다 — 데스크톱에서 제안을 승인했을 때와
  검색 관점에서 동일한 상태. (`updated_by`·프로젝트 요약 재생성은 검색 경로가
  읽지 않으므로 재현 범위 밖.)

## 산출물

| 파일 | 내용 |
|---|---|
| `results/summary.csv` | 구성당 1행 누적(키: run_id/corpus/config/phase) — 보고서·그래프 원천 |
| `results/ragas_<corpus>_<config>_<phase>_<runid>.csv` | 문항별 RAGAS 지표 + history debug |
| `results/oracle_<corpus>_E2-oracle_<phase>_<runid>.csv` | E2-oracle 보조 측정(감지 실패와 체인 품질 분리 진단) |
| `results/routing_audit_<corpus>_<phase>_<runid>.csv` | 문항별 기대/실제 경로·stage 대조 — 미탐 목록 원천 |
| `results/pair_coverage_<corpus>_<phase>_<runid>.csv` | 판별기 적중(정타 대조)/오대상/negative 오제안 + 훅 상태 |
| `results/run_<corpus>_<phase>_<runid>.log` | **실행 로그(as-run trace)** — `all`의 부모+자식 단계 출력을 시각과 함께 (`*.log`만 gitignore) |
| `results/METHODS_<runid>.md` | **Materials & Methods** — 커밋·버전·모델(실측 judge)·표본·pair·재현 커맨드 |
| `.eval_state/` (gitignore) | 체크포인트(`checkpoint.ok` 완성 표식)·적재 덤프·컨텍스트 전문·완료 마커 |

`results/`의 CSV·METHODS는 추적(커밋) 대상, 실행 로그(`*.log`)만 로컬 전용이다.
집계 표 출력: `$P report --runid <RUNID>` (지정 없으면 최근 run_id로 한정 — 여러
run 수치가 한 표에 섞이지 않는다).

## 테스트가 어떻게 진행되었는지 확인 (Material & Method)

세 층위로 남는다 — **무엇을 어떻게 돌렸나(방법)** / **실제로 어떻게 흘렀나(추적)** /
**하네스가 맞나(단위 테스트)**.

```bash
P=".venv/bin/python backend/test/golden/run_eval.py"
L=".agent-workflow/tasks/TASK-006/logs"

# ① 방법론 기록(Materials & Methods) — DB·키 없이 언제든 생성/갱신
$P methods --phase final --runid <RUNID>      # → results/METHODS_<RUNID>.md
#   all 실행 시 자동 생성되며, 골든 파일·적재 덤프·설치 버전에서 as-run 값을 채운다.

# ② 실행 로그(as-run trace) — all이 자동으로 남긴다. 부분 재실행은 셸 tee로:
$P measure --corpus modu --config E2-e2e --phase dev --runid <RUNID> \
  2>&1 | tee -a results/run_modu_dev_<RUNID>.log

# ③ 하네스 단위 테스트(pytest) — 케이스별 통과/실패 리포트
.venv/bin/python -m pytest tests/test_golden_harness.py -v \
  --junitxml="$L/pytest-golden.xml" 2>&1 | tee "$L/pytest-golden.txt"

# 백엔드 전체 사전검사 로그도 파일로:
./scripts/verify-backend.sh 2>&1 | tee "$L/verify-backend-latest.log"
```

- **실행 로그**는 `all`이 fd 수준 tee로 부모·자식(적재 행수·상태 검사·구성별
  measure·pair 매칭·감사)을 한 파일에 시간순으로 모은다 — 결과 수치(CSV)와 별개로
  "이 run이 실제로 어떤 단계를 밟았나"를 감사할 때 본다.
- **METHODS**는 EVAL_DESIGN(설계 *의도*)과 겹치지 않게 **실행 시점 값만** 담는다:
  git 커밋·패키지 버전·judge/임베딩 모델·코퍼스별 추출 행수·표본 크기(비환각/환각/
  history/conflict_negative)·골든 pair·재현 커맨드.

## 비용 개요 (OpenAI 호출)

- **dev**: 코퍼스당 비환각 26문항 × 6구성 RAGAS 2지표(judge 4.1-mini) + 멀티쿼리
  (fast 티어) + 환각 4문항 × 6구성 생성 + oracle + 감사 LLM 폴백(~45문항/2코퍼스).
  대략 수천 회의 4.1-mini 호출 — 소액(달러 단위).
- **final(증분)**: 생성 지표(E0·E2, faithfulness/relevancy)만 추가 채점 —
  judge는 dev와 동일 gpt-4.1-mini(정합). context 지표는 dev 실측을 승격.
- **적재**: 회의록 15편 추출 + supersede 판별 + 임베딩 — 1회성 소액.
- 동시성은 `measure --workers N`(기본 3 — judge·백엔드가 같은 한도 버킷 공유), 실패 시 `--resume`으로 재개해 중복
  지출을 막는다.

## 문제 해결

- `OPENAI_API_KEY가 필요합니다` — 키 설정 후 재시도. 키 없이 가능한 건
  단위 테스트(`tests/test_golden_harness.py`)·`report`·`methods`뿐.
- `매칭 N건(정확히 1건 필요)` — 추출 결과가 pair의 match 문구와 안 맞는 경우.
  출력된 후보를 보고 `golden_supersede_pairs.json`의 match 문구만 보정 후 재시도
  (QA·라벨 판정값은 수정 금지).
- `현재 상태가 pre-pairs가 아님` — 이전 pairs 실행 잔재. `restore` 후 재시도.
  (이미 E1 상태면 `pairs`는 멱등적으로 건너뛴다 — resume 안전. 이때 이 run의
  coverage CSV가 없으면 상태 변경 없이 자동 재생성한다.)
- `유효한 체크포인트 없음(미완성/부재)` — 체크포인트 게시가 중단돼 완성 표식
  (`checkpoint.ok`)이 없는 경우. pre 상태에서 `checkpoint`를 다시 실행.
- `run이 invalid 봉인 상태` — 복구(MySQL·Chroma) 실패 이력. `restore` 성공 시 해소.
- `judge 불일치` — 같은 키를 다른 judge로 재측정하려는데 완료 마커가 있는 경우.
  `--overwrite`로 교체하거나 같은 judge로 재실행.
- 컨테이너 충돌 — `db-down` 후 `db-up`.
