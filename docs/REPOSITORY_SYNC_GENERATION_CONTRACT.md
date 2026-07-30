# Repository Sync Generation Contract

## 목적

GitHub 저장소 재동기화 중 오류가 발생해도 이미 게시된 검색 결과를 유지하고,
동기화 중인 일부 데이터가 Q&A에 섞이지 않게 한다.

## v9 스키마 계약

이 프로젝트는 아직 운영 DB가 배포되지 않았다는 현재 릴리스 방침에 따라 별도
`migrate_v10.sql`을 만들지 않는다. 신규 설치의 `schema.sql`과 v8에서 직접
올라오는 경우의 `migrate_v9.sql`, 런타임의 `ensure_schema_v9()`가 아래 필드를
동일하게 보장한다.

- `repositories.active_sync_run_id`: 현재 게시된 generation UUID
- `repositories.current_sync_run_id`: 실행 중 worker가 소유한 fence UUID
- `repositories.sync_started_at`: stale worker 판정을 위한 시작 시각
- `memory.repo_sync_run_id`: 저장소 memory가 속한 generation UUID
- `published_memory`: 문서 memory와 게시된 저장소 generation만 노출하는 뷰
- `active_memory`: 게시 스냅샷 내부의 supersede 관계까지 적용한 뷰

## 실행 흐름

1. sync 요청이 저장소 행을 잠그고 `current_sync_run_id`를 발급한다.
2. 수집 시작 시 branch HEAD를 고정한다.
3. Memory와 Chroma chunk를 해당 run UUID로 staging한다.
4. MySQL·Chroma 검색은 하나의 `ProjectIndexScope`를 캡처해 게시된 run만 읽는다.
   `search_project_evidence`는 generation이 없는 프로젝트 요약을 섞지 않는다.
   프로젝트 요약은 별도의 조망 도구에서만 사용한다.
5. 모든 source 적재가 성공하면 fence 소유권을 확인하고 active pointer를 교체한다.
6. 실패하거나 fence를 잃으면 해당 staging generation만 정리한다.
7. 이전 generation은 이미 시작한 조회가 끝날 수 있도록 런타임 동안 보존하고,
   다음 서버 기동 시 요청을 받기 전에 정리한다.

## 운영 제약

- 프로젝트 요약 publication lock은 현재 단일 backend worker 배포 계약을 전제로 한다.
- 다중 worker로 확장할 때는 이 process-local lock을 DB advisory lock 또는 별도
  versioned summary 저장 방식으로 교체해야 한다.
- `main` 병합 전 fresh v9 MySQL에서 staging 비노출, 실패 시 기존 generation 유지,
  성공 시 active pointer 전환을 통합 테스트한다.
