-- v10 마이그레이션 (idempotent, MySQL 8.0 호환)
-- 문서 기반 완료 제안을 별도 kind로 분리한다: complete_action + evidence.type='document'
--   → complete_action_doc
--
-- 원래 migrate_v9.sql로 작성했으나 PR #7(TASK-012B quota·운영 스키마)이 v9를 선점해
-- v10으로 옮겼다. 두 마이그레이션은 건드리는 테이블이 달라(documents vs
-- memory_suggestions) 적용 순서에 의존하지 않는다.
--
-- 배경: PR 기반 complete_action의 evidence는 {type:"pr", number, title, url, merged_at}인데
-- 문서 기반은 {type:"document", doc_id, source, date, quote}로 title이 없다. 구 데스크톱은
-- kind='complete_action'이면 evidence.title.trim()을 호출하므로 문서 evidence가 섞이면
-- TypeError로 패널 전체가 죽는다(해당 렌더 트리에 ErrorBoundary 없음).
--
-- 코드만 고치면 이미 저장된 행이 남아 재발하므로 여기서 함께 재분류한다.
-- status 무관 전체 적용: 해소된 행도 ?status=accepted 조회에서 같은 렌더 분기를 타고,
-- 승인 효과는 두 kind가 공유하므로(_apply_accepted_effect) 재적용 위험이 없다.
--
-- kind는 VARCHAR(20), complete_action_doc은 19자 — 컬럼 변경 불필요.
-- 재실행 안전: 두 번째 실행은 대상이 0행(이미 kind가 바뀌어 WHERE에 안 걸림).

UPDATE memory_suggestions
SET kind = 'complete_action_doc'
WHERE kind = 'complete_action'
  AND JSON_UNQUOTE(JSON_EXTRACT(evidence, '$.type')) = 'document';
