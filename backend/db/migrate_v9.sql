-- v9: TASK-012B runtime readiness and durable upload quota accounting.
-- Existing rows are backfilled by ensure_schema_v9(), which can inspect the filesystem.
DROP PROCEDURE IF EXISTS paiM_migrate_v9;

DELIMITER //

CREATE PROCEDURE paiM_migrate_v9()
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents' AND COLUMN_NAME='size_bytes') THEN
        ALTER TABLE documents ADD COLUMN size_bytes BIGINT UNSIGNED NULL AFTER progress_total;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents' AND COLUMN_NAME='uploaded_by') THEN
        ALTER TABLE documents ADD COLUMN uploaded_by INT NULL AFTER size_bytes;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents' AND COLUMN_NAME='processing_token') THEN
        ALTER TABLE documents ADD COLUMN processing_token CHAR(36) NULL AFTER uploaded_by;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents' AND COLUMN_NAME='lease_expires_at') THEN
        ALTER TABLE documents ADD COLUMN lease_expires_at DATETIME NULL AFTER processing_token;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents' AND INDEX_NAME='idx_documents_uploaded_by') THEN
        ALTER TABLE documents ADD INDEX idx_documents_uploaded_by (uploaded_by);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.TABLE_CONSTRAINTS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='documents' AND CONSTRAINT_NAME='fk_documents_uploaded_by') THEN
        ALTER TABLE documents ADD CONSTRAINT fk_documents_uploaded_by FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL;
    END IF;
END //

DELIMITER ;

CALL paiM_migrate_v9();
DROP PROCEDURE IF EXISTS paiM_migrate_v9;

CREATE TABLE IF NOT EXISTS upload_quota_reservations (
    reservation_id CHAR(36) PRIMARY KEY,
    user_id INT NOT NULL,
    project_id INT NOT NULL,
    kind VARCHAR(20) NOT NULL,
    size_bytes BIGINT UNSIGNED NOT NULL,
    target_path VARCHAR(500) NULL,
    temp_path VARCHAR(500) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    CONSTRAINT fk_quota_reservation_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_quota_reservation_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE RESTRICT,
    INDEX idx_quota_reservations_user (user_id),
    INDEX idx_quota_reservations_project (project_id),
    INDEX idx_quota_reservations_expiry (expires_at)
);

CREATE TABLE IF NOT EXISTS storage_cleanup_pending (
    cleanup_id CHAR(36) PRIMARY KEY,
    source_kind VARCHAR(20) NOT NULL,
    source_id VARCHAR(64) NOT NULL,
    user_id INT NULL,
    project_id INT NOT NULL,
    document_id INT NULL,
    file_path VARCHAR(500) NULL,
    size_bytes BIGINT UNSIGNED NOT NULL,
    count_units INT UNSIGNED NOT NULL DEFAULT 1,
    needs_chroma TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_attempt_at DATETIME NULL,
    UNIQUE KEY uq_cleanup_source (source_kind, source_id),
    INDEX idx_cleanup_user (user_id),
    INDEX idx_cleanup_project (project_id)
);
