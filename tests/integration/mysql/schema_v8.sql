# TASK-012A baseline 2b0b7c95f2bf332e62cf3c2d926cddee5535a1f6 v8 schema fixture.
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
    uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
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
    connected_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS memory (
    id               INT PRIMARY KEY AUTO_INCREMENT,
    project_id       INT NOT NULL,
    doc_id           INT NULL,
    repo_id          INT NULL,
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
        FOREIGN KEY (superseded_by) REFERENCES memory(id) ON DELETE SET NULL
);

-- 현재 유효한(번복되지 않은) memory만 보는 뷰(v8). 유효 항목만 봐야 하는 집계/요약
-- raw SQL은 memory 대신 이 뷰를 읽어 superseded 필터 누락을 구조적으로 방지한다.
CREATE OR REPLACE VIEW active_memory AS
SELECT * FROM memory WHERE superseded_by IS NULL;

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
