export type Attachment = {
  id: string;
  name: string;
  uploadName?: string;
  path: string;
  kind?: "file" | "directory";
  children?: Attachment[];
  childrenLoaded?: boolean;
  docId?: number;
  documentStatus?: ProjectDocumentStatus;
  isExpanded?: boolean;
  lastError?: string | null;
  serverOnly?: boolean;
  uploadedAt?: number;
  previewUrl?: string;
};

export type ProjectDocumentStatus =
  | "uploading"
  | "uploaded"
  | "processing"
  | "indexed"
  | "failed"
  | "delayed";

export type DirectoryChildEntry = {
  name: string;
  path: string;
  kind: "file" | "directory";
};

export type ProjectFilePreview = {
  id: string;
  name: string;
  path: string;
  content: string;
  isLoading: boolean;
  error?: string;
};

export type Message = {
  id: string;
  role: "assistant" | "error" | "user";
  content: string;
  attachments?: Attachment[];
  sources?: string[];
  thinkingSeconds?: number;
};

export type ChatSession = {
  id: string;
  createdExplicitly?: boolean;
  title: string;
  messages: Message[];
  createdAt: number;
};

export type GitHubEventType = "issue" | "pull_request" | "commit";

export type GitHubTimelineEvent = {
  author?: string;
  id: string;
  number?: number;
  type: GitHubEventType;
  title: string;
  createdAt: number;
  status?: string;
  url?: string;
};

export type GitRepositoryInfo = {
  path: string;
  name: string;
  branch: string;
  isDirty: boolean;
  remoteRepo?: string;
  issuePrStatus: string;
  visibility?: "public" | "private";
  authProvider?: "public" | "github_oauth" | "github_app";
  repoId?: number;
  syncStatus?: GitRepositorySyncStatus;
  syncStartedAt?: number;
  connectedAt?: string;
  commitSha?: string | null;
  indexedFiles?: number | null;
  lastError?: string | null;
  syncWarnings?: GitRepositorySyncWarning[];
};

export type GitRepositorySyncStatus = "connected" | "syncing" | "indexed" | "failed" | "delayed";

export type GitRepositorySyncWarning = {
  source_type?: string;
  reason?: string;
};

export type ProjectMemoryCategory = "decision" | "action" | "issue" | "risk";

export type ProjectMemoryItem = {
  id: number;
  project_id?: number;
  doc_id?: number;
  repo_id?: number | null;
  category: ProjectMemoryCategory;
  content: string;
  reason?: string | null;
  topic?: string | null;
  owner?: string | null;
  date?: string | null;
  due_date?: string | null;
  source?: string | null;
  created_by?: string | null;
  updated_by?: string | null;
  is_user_verified?: boolean | number | null;
  completed_at?: string | null;
  sort_order?: number | null;
  created_at?: string | null;
  source_info?: {
    doc_id?: number | null;
    kind?: string | null;
    path?: string | null;
    ref?: string | null;
    repo_id?: number | null;
    type?: string | null;
    url?: string | null;
  };
};

export type ProjectMemoryCompleteActionSuggestionEvidence = {
  type: "pr";
  number: number;
  title: string;
  url: string;
  merged_at: string;
};

export type ProjectMemorySupersedeSuggestionEvidence = {
  type: "supersede";
  superseding_memory_id: number;
};

type ProjectMemorySuggestionBase = {
  id: number;
  memory_id: number;
  rationale: string;
  confidence: "high" | "medium";
  status: "pending" | "accepted" | "rejected";
  created_at?: string | null;
  resolved_at?: string | null;
};

export type ProjectMemorySuggestion = ProjectMemorySuggestionBase &
  (
    | {
        kind: "complete_action";
        evidence: ProjectMemoryCompleteActionSuggestionEvidence;
      }
    | {
        kind: "supersede";
        evidence: ProjectMemorySupersedeSuggestionEvidence;
      }
  );

export type ProjectWorkspace = {
  id: string;
  apiProjectId?: number;
  currentUserRole?: "viewer" | "member" | "admin" | "owner" | null;
  serverMissing?: boolean;
  setupCompletedAt?: number;
  setupMode?: "analyzed" | "chat_only" | "existing";
  lastSeenAt?: string;
  name: string;
  description?: string;
  files?: Attachment[];
  githubConnected?: boolean;
  githubRepository?: GitRepositoryInfo;
  githubEvents?: GitHubTimelineEvent[];
  sessions: ChatSession[];
  createdAt: number;
};

export function isProjectSetupComplete(project: ProjectWorkspace) {
  return typeof project.setupCompletedAt === "number";
}

export type ProjectState = {
  projects: ProjectWorkspace[];
  selectedProjectId: string | null;
  selectedSessionId: string | null;
};

export type DemoStatus = {
  kind?: "error" | "info" | "success" | "warning";
  ok: boolean;
  message: string;
  projectId?: string;
  scope?: "github" | "overview";
};

export type GithubLoginSessionState = {
  deviceCode?: string;
  state?: string;
  userCode?: string;
  verificationUri: string;
  interval: number;
  status: "pending" | "connected";
  accessToken?: string;
  scope?: string;
  tokenType?: string;
  user?: GithubUserProfile;
};

export type GithubUserProfile = {
  login: string;
  avatarUrl: string;
  htmlUrl: string;
  name?: string | null;
};

export type GithubDeviceCodeResponse = {
  device_code?: string;
  user_code?: string;
  verification_uri?: string;
  expires_in?: number;
  interval?: number;
  error?: string;
  error_description?: string;
};

export type GithubAccessTokenResponse = {
  access_token?: string;
  token_type?: string;
  scope?: string;
  error?: string;
  error_description?: string;
};

export type GithubAvailableRepository = {
  fullName: string;
  name: string;
  private: boolean;
  defaultBranch: string;
  url: string;
  owner?: GithubUserProfile;
};

export type GithubPanelState = "signedout" | "authing" | "repos" | "connected";
export type ProjectSourcesMode = "library" | "tree";
