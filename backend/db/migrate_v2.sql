-- v2 마이그레이션 (idempotent, MySQL 8.0 호환)
-- ADD COLUMN IF NOT EXISTS / DROP FOREIGN KEY IF EXISTS 미지원 → stored procedure로 대체
-- information_schema 조회로 컬럼/FK 존재 여부를 확인한 뒤 ALTER 실행

DROP PROCEDURE IF EXISTS paiM_migrate_v2;

DELIMITER //

CREATE PROCEDURE paiM_migrate_v2()
BEGIN

    -- ── 1) documents 확장 ────────────────────────────────────────────
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents' AND COLUMN_NAME = 'status'
    ) THEN
        ALTER TABLE documents ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'uploaded' AFTER doc_type;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents' AND COLUMN_NAME = 'file_path'
    ) THEN
        ALTER TABLE documents ADD COLUMN file_path VARCHAR(500) DEFAULT NULL AFTER status;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents' AND COLUMN_NAME = 'last_error'
    ) THEN
        ALTER TABLE documents ADD COLUMN last_error TEXT DEFAULT NULL AFTER file_path;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents' AND COLUMN_NAME = 'progress_done'
    ) THEN
        ALTER TABLE documents ADD COLUMN progress_done INT DEFAULT NULL AFTER last_error;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'documents' AND COLUMN_NAME = 'progress_total'
    ) THEN
        ALTER TABLE documents ADD COLUMN progress_total INT DEFAULT NULL AFTER progress_done;
    END IF;

    -- ── 2) repositories 테이블 (CREATE TABLE IF NOT EXISTS 는 MySQL 지원) ──
    CREATE TABLE IF NOT EXISTS repositories (
        id             INT PRIMARY KEY AUTO_INCREMENT,
        project_id     INT NOT NULL,
        provider       VARCHAR(20)  NOT NULL DEFAULT 'github',
        repository_url VARCHAR(500) NOT NULL,
        branch         VARCHAR(100),
        status         VARCHAR(20)  NOT NULL DEFAULT 'connected',
        commit_sha     VARCHAR(40),
        indexed_files  INT          NOT NULL DEFAULT 0,
        connected_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'repositories' AND COLUMN_NAME = 'last_error'
    ) THEN
        ALTER TABLE repositories ADD COLUMN last_error TEXT DEFAULT NULL AFTER indexed_files;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'repositories' AND COLUMN_NAME = 'sync_warning'
    ) THEN
        ALTER TABLE repositories ADD COLUMN sync_warning TEXT DEFAULT NULL AFTER last_error;
    END IF;

    -- ── 3) memory 확장 ───────────────────────────────────────────────
    -- doc_id NULL 허용 — 이미 NULL이어도 MODIFY는 안전
    ALTER TABLE memory MODIFY COLUMN doc_id INT NULL;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'memory' AND COLUMN_NAME = 'repo_id'
    ) THEN
        ALTER TABLE memory ADD COLUMN repo_id INT NULL AFTER doc_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'memory' AND COLUMN_NAME = 'created_by'
    ) THEN
        ALTER TABLE memory ADD COLUMN created_by VARCHAR(10) NOT NULL DEFAULT 'llm' AFTER source;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'memory' AND COLUMN_NAME = 'updated_by'
    ) THEN
        ALTER TABLE memory ADD COLUMN updated_by VARCHAR(10) NULL AFTER created_by;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'memory' AND COLUMN_NAME = 'is_user_verified'
    ) THEN
        ALTER TABLE memory ADD COLUMN is_user_verified TINYINT(1) NOT NULL DEFAULT 0 AFTER updated_by;
    END IF;

    -- ── 4) FK: fk_memory_repo ────────────────────────────────────────
    IF EXISTS (
        SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'memory'
          AND CONSTRAINT_NAME = 'fk_memory_repo' AND CONSTRAINT_TYPE = 'FOREIGN KEY'
    ) THEN
        ALTER TABLE memory DROP FOREIGN KEY fk_memory_repo;
    END IF;

    ALTER TABLE memory ADD CONSTRAINT fk_memory_repo FOREIGN KEY (repo_id) REFERENCES repositories(id);

    -- ── 5) users 테이블 ─────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS users (
        id         INT PRIMARY KEY AUTO_INCREMENT,
        email      VARCHAR(255) NOT NULL UNIQUE,
        name       VARCHAR(255),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    -- ── 6) projects.owner_user_id + FK ──────────────────────────────
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects' AND COLUMN_NAME = 'owner_user_id'
    ) THEN
        ALTER TABLE projects ADD COLUMN owner_user_id INT NULL AFTER name;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'projects'
          AND CONSTRAINT_NAME = 'fk_projects_owner' AND CONSTRAINT_TYPE = 'FOREIGN KEY'
    ) THEN
        ALTER TABLE projects DROP FOREIGN KEY fk_projects_owner;
    END IF;

    ALTER TABLE projects ADD CONSTRAINT fk_projects_owner FOREIGN KEY (owner_user_id) REFERENCES users(id);

    -- ── project_members ──────────────────────────────────────────────
    CREATE TABLE IF NOT EXISTS project_members (
        project_id INT NOT NULL,
        user_id    INT NOT NULL,
        role       VARCHAR(20) NOT NULL DEFAULT 'member',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (project_id, user_id),
        FOREIGN KEY (project_id) REFERENCES projects(id),
        FOREIGN KEY (user_id)    REFERENCES users(id)
    );

    -- ── 7) memory_sources ────────────────────────────────────────────
    -- CREATE INDEX IF NOT EXISTS MySQL 8.0 미지원 → INDEX를 CREATE TABLE 내부에서만 정의
    CREATE TABLE IF NOT EXISTS memory_sources (
        id          INT PRIMARY KEY AUTO_INCREMENT,
        memory_id   INT NOT NULL,
        source_kind VARCHAR(20)  NOT NULL,
        doc_id      INT NULL,
        repo_id     INT NULL,
        source_type VARCHAR(30)  NULL,
        source_path VARCHAR(500) NULL,
        source_ref  VARCHAR(100) NULL,
        source_url  VARCHAR(500) NULL,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (memory_id) REFERENCES memory(id) ON DELETE CASCADE,
        FOREIGN KEY (doc_id)    REFERENCES documents(id) ON DELETE SET NULL,
        FOREIGN KEY (repo_id)   REFERENCES repositories(id) ON DELETE SET NULL,
        INDEX idx_memory_sources_memory_id (memory_id),
        INDEX idx_memory_sources_doc_id    (doc_id),
        INDEX idx_memory_sources_repo_id   (repo_id)
    );

    -- ── 8) project_memory 테이블 (project_memory.py 런타임 DDL 정식 등록) ─
    CREATE TABLE IF NOT EXISTS project_memory (
        project_id INT PRIMARY KEY,
        summary    TEXT,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );

    -- ── 9) 채팅 세션 테이블 (기존 DB에 없는 경우 생성) ─────────────────
    CREATE TABLE IF NOT EXISTS chat_sessions (
        id         VARCHAR(64) PRIMARY KEY,
        project_id INT NOT NULL,
        title      VARCHAR(255),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (project_id) REFERENCES projects(id)
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        id          INT PRIMARY KEY AUTO_INCREMENT,
        session_id  VARCHAR(64) NOT NULL,
        role        VARCHAR(20) NOT NULL,
        ciphertext  TEXT NOT NULL,
        nonce       VARCHAR(64) NOT NULL,
        key_version VARCHAR(20) NOT NULL,
        token_count INT NOT NULL DEFAULT 0,
        created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
    );

    CREATE TABLE IF NOT EXISTS chat_summaries (
        session_id         VARCHAR(64) PRIMARY KEY,
        ciphertext         TEXT NOT NULL,
        nonce              VARCHAR(64) NOT NULL,
        key_version        VARCHAR(20) NOT NULL,
        source_message_id  INT NOT NULL DEFAULT 0,
        updated_at         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
    );

END //

DELIMITER ;

CALL paiM_migrate_v2();
DROP PROCEDURE IF EXISTS paiM_migrate_v2;
