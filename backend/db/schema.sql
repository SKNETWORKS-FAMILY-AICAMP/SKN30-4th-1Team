CREATE TABLE IF NOT EXISTS users (
    id            INT PRIMARY KEY AUTO_INCREMENT,
    email         VARCHAR(255) NOT NULL UNIQUE,
    name          VARCHAR(255),
    password_hash VARCHAR(255) NULL,  -- bcrypt. NULL이면 로그인 불가(레거시/DEV row)
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS projects (
    id             INT PRIMARY KEY AUTO_INCREMENT,
    name           VARCHAR(255),
    owner_user_id  INT NULL,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (owner_user_id) REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS project_members (
    project_id   INT NOT NULL,
    user_id      INT NOT NULL,
    role         VARCHAR(20) NOT NULL DEFAULT 'member',
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME NULL,
    PRIMARY KEY (project_id, user_id),
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (user_id)    REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS documents (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    project_id  INT NOT NULL,
    filename    VARCHAR(255),
    doc_type    VARCHAR(50),
    status      VARCHAR(20)  NOT NULL DEFAULT 'uploaded',
    file_path   VARCHAR(500),
    last_error  TEXT         DEFAULT NULL,
    progress_done  INT       DEFAULT NULL,
    progress_total INT       DEFAULT NULL,
    size_bytes BIGINT UNSIGNED NOT NULL DEFAULT 0,
    uploaded_by INT NULL,
    processing_token CHAR(36) NULL,
    lease_expires_at DATETIME NULL,
    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    CONSTRAINT fk_documents_uploaded_by FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_documents_uploaded_by (uploaded_by),
    INDEX idx_documents_project_status (project_id, status)
);

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

CREATE TABLE IF NOT EXISTS repositories (
    id             INT PRIMARY KEY AUTO_INCREMENT,
    project_id     INT NOT NULL,
    provider       VARCHAR(20)  NOT NULL DEFAULT 'github',
    repository_url VARCHAR(500) NOT NULL,
    branch         VARCHAR(100),
    status         VARCHAR(20)  NOT NULL DEFAULT 'connected',
    commit_sha     VARCHAR(40),
    indexed_files  INT          NOT NULL DEFAULT 0,
    last_error     TEXT         DEFAULT NULL,
    sync_warning   TEXT         DEFAULT NULL,
    last_reconciled_pr INT      NULL,
    -- 저장소 동기화는 새 세대를 staging한 뒤 active pointer를 원자적으로 바꾼다.
    -- current_sync_run_id는 중복 worker와 늦게 끝난 worker를 막는 fence다.
    active_sync_run_id  CHAR(36) NULL,
    current_sync_run_id CHAR(36) NULL,
    connected_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- 이 저장소의 '현재 동기화가 시작된 시각'. connected_at(연결 시각)과 축이 다르다.
    -- stale 판정은 이 값을 기준으로 한다 — connected_at은 재동기화 때 갱신되지 않아
    -- 연결한 지 오래된 저장소의 정상 동기화가 곧바로 stale로 오판됐다.
    sync_started_at DATETIME(6) NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    INDEX idx_repositories_active_sync_run (active_sync_run_id),
    INDEX idx_repositories_current_sync_run (current_sync_run_id)
);

CREATE TABLE IF NOT EXISTS memory (
    id               INT PRIMARY KEY AUTO_INCREMENT,
    project_id       INT NOT NULL,
    doc_id           INT NULL,
    repo_id          INT NULL,
    repo_sync_run_id CHAR(36) NULL,
    category         VARCHAR(20),
    content          TEXT,
    reason           TEXT,
    topic            VARCHAR(100),
    owner            VARCHAR(100),
    date             DATE,
    due_date         DATE         NULL,
    source           VARCHAR(255),
    created_by       VARCHAR(10)  NOT NULL DEFAULT 'llm',
    updated_by       VARCHAR(10)  NULL,
    is_user_verified TINYINT(1)   NOT NULL DEFAULT 0,
    completed_at     DATETIME     NULL,
    completion_status VARCHAR(20) NOT NULL DEFAULT 'unknown',
    completion_status_source VARCHAR(20) NULL,
    superseded_by    INT          NULL,
    superseded_at    DATETIME     NULL,
    sort_order       INT          NULL,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (doc_id)     REFERENCES documents(id),
    FOREIGN KEY (repo_id)    REFERENCES repositories(id),
    -- self-FK: 대체(신) decision 삭제 시 포인터를 자동 해제해 구 decision을 복귀시킨다(v8).
    CONSTRAINT fk_memory_superseded_by
        FOREIGN KEY (superseded_by) REFERENCES memory(id) ON DELETE SET NULL,
    INDEX idx_memory_repo_sync_run (repo_id, repo_sync_run_id)
);

-- 문서는 항상 보이고, 저장소 memory는 게시된 generation만 보인다. generation
-- 도입 전 저장소의 NULL/NULL 조합도 최초 성공 sync 전까지 호환 노출한다.
CREATE OR REPLACE VIEW published_memory AS
SELECT m.* FROM memory m
LEFT JOIN repositories r ON r.id = m.repo_id
WHERE m.repo_id IS NULL
   OR r.active_sync_run_id = m.repo_sync_run_id
   OR (r.active_sync_run_id IS NULL AND m.repo_sync_run_id IS NULL);

-- 게시된 스냅샷 안에서만 supersede 관계를 해석한다. staging successor가 기존
-- 게시 결정을 미리 숨기지 않도록 raw superseded_by IS NULL 조건을 쓰지 않는다.
CREATE OR REPLACE VIEW active_memory AS
SELECT pm.* FROM published_memory pm
LEFT JOIN published_memory successor ON successor.id = pm.superseded_by
WHERE successor.id IS NULL;

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

CREATE TABLE IF NOT EXISTS memory_suggestions (
    id          INT PRIMARY KEY AUTO_INCREMENT,
    project_id  INT NOT NULL,
    memory_id   INT NOT NULL,
    kind        VARCHAR(20) NOT NULL,
    evidence    JSON NOT NULL,
    rationale   TEXT NOT NULL,
    confidence  VARCHAR(10) NOT NULL,
    status      VARCHAR(10) NOT NULL DEFAULT 'pending',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME NULL,
    resolved_by INT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (memory_id)  REFERENCES memory(id) ON DELETE CASCADE,
    FOREIGN KEY (resolved_by) REFERENCES users(id),
    INDEX idx_memory_suggestions_project_status (project_id, status),
    INDEX idx_memory_suggestions_memory_status  (memory_id, status)
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id         VARCHAR(64) PRIMARY KEY,
    project_id INT NOT NULL,
    user_id    INT NULL,  -- 세션 소유자. NULL은 마이그레이션 이전 레거시 세션(멤버 전원에게 보임)
    title      VARCHAR(255),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id),
    FOREIGN KEY (user_id)    REFERENCES users(id),
    INDEX idx_chat_sessions_project_user (project_id, user_id)
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

CREATE TABLE IF NOT EXISTS project_memory (
    project_id INT PRIMARY KEY,
    summary    TEXT,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);
