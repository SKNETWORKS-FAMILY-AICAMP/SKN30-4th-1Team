-- v10: minimal fenced GitHub repository generations.
-- repositories keeps the published generation and current execution UUID.
DROP PROCEDURE IF EXISTS paiM_migrate_v10;

DELIMITER //

CREATE PROCEDURE paiM_migrate_v10()
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='repositories'
          AND COLUMN_NAME='active_sync_run_id'
    ) THEN
        ALTER TABLE repositories
            ADD COLUMN active_sync_run_id CHAR(36) NULL AFTER last_reconciled_pr;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='repositories'
          AND COLUMN_NAME='current_sync_run_id'
    ) THEN
        ALTER TABLE repositories
            ADD COLUMN current_sync_run_id CHAR(36) NULL AFTER active_sync_run_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='repositories'
          AND COLUMN_NAME='sync_started_at'
    ) THEN
        ALTER TABLE repositories
            ADD COLUMN sync_started_at DATETIME(6) NULL AFTER current_sync_run_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='memory'
          AND COLUMN_NAME='repo_sync_run_id'
    ) THEN
        ALTER TABLE memory
            ADD COLUMN repo_sync_run_id CHAR(36) NULL AFTER repo_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='repositories'
          AND INDEX_NAME='idx_repositories_active_sync_run'
    ) THEN
        ALTER TABLE repositories
            ADD INDEX idx_repositories_active_sync_run (active_sync_run_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='repositories'
          AND INDEX_NAME='idx_repositories_current_sync_run'
    ) THEN
        ALTER TABLE repositories
            ADD INDEX idx_repositories_current_sync_run (current_sync_run_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='memory'
          AND INDEX_NAME='idx_memory_repo_sync_run'
    ) THEN
        ALTER TABLE memory
            ADD INDEX idx_memory_repo_sync_run (repo_id, repo_sync_run_id);
    END IF;
END //

DELIMITER ;

CALL paiM_migrate_v10();
DROP PROCEDURE IF EXISTS paiM_migrate_v10;

CREATE OR REPLACE VIEW published_memory AS
SELECT m.*
FROM memory m
LEFT JOIN repositories r ON r.id = m.repo_id
WHERE m.repo_id IS NULL
   OR r.active_sync_run_id = m.repo_sync_run_id
   OR (r.active_sync_run_id IS NULL AND m.repo_sync_run_id IS NULL);

CREATE OR REPLACE VIEW active_memory AS
SELECT pm.*
FROM published_memory pm
LEFT JOIN published_memory successor ON successor.id = pm.superseded_by
WHERE successor.id IS NULL;
