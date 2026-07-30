import {
  Activity,
  AlertTriangle,
  AudioLines,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  CheckCircle2,
  Clock3,
  File,
  FilePlus2,
  FileText,
  Files,
  Folder,
  FolderPlus,
  GitBranch,
  GitPullRequest,
  Info,
  MessageSquare,
  Plus,
  RefreshCw,
  Settings2,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Spinner } from "@astryxdesign/core/Spinner";
import {
  type KeyboardEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { formatRelativeAge, parsePaimTimestamp } from "./format";
import {
  fetchProjectMembers,
  type ProjectMember,
  type ProjectRole,
} from "./members";
import { ProfileAvatar } from "./ProfileAvatar";
import {
  fetchProjectActivity,
  type ProjectActivityEvent,
} from "./projectActivity";
import {
  createLocalProjectOverview,
  fetchProjectOverviews,
  type ProjectOverview,
} from "./projectOverview";
import { translate } from "./i18n";
import type { LanguageSetting } from "./settings";
import { isMeetingDocument } from "./stt";
import type {
  Attachment,
  ProjectMemoryItem,
  ProjectWorkspace,
} from "./types";

export type ProjectDetailPageProps = {
  activeTab: ProjectDetailTab;
  composerAttachments: Attachment[];
  composerDisabledMessage?: string;
  composerPrompt: string;
  isComposerSending?: boolean;
  language: LanguageSetting;
  memoryItems: ProjectMemoryItem[];
  onAddProjectAudio?: () => void;
  onAddProjectFiles?: () => void;
  onAddProjectFolder?: () => void;
  onBack: () => void;
  onComposerPickFiles?: () => void;
  onComposerPromptChange: (value: string) => void;
  onComposerRemoveAttachment: (attachmentId: string) => void;
  onComposerSubmit: () => void | Promise<void>;
  onDeleteProjectFile?: (file: Attachment) => void | Promise<boolean | void>;
  onOpenGithub?: () => void;
  onManageMembers: (trigger?: HTMLElement) => void;
  onOpenManagement?: (trigger?: HTMLElement) => void;
  onOpenProjectFile?: (file: Attachment) => void;
  onOpenProjectFilesManager?: () => void;
  onRefreshProjectFileStatus?: (file: Attachment) => void;
  onTabChange: (tab: ProjectDetailTab) => void;
  project: ProjectWorkspace;
  projectRole?: ProjectRole | null;
  currentUserId?: number | null;
  refreshRevision?: number;
};

export type ProjectDetailTab = "activity" | "files" | "overview" | "team";

type DetailData = {
  memories: ProjectMemoryItem[];
  overview: ProjectOverview;
};

type ProjectActivityItem = {
  description: string;
  id: string;
  kind: "chat" | "file" | "github" | "member" | "memory" | "project";
  timestamp: number;
  title: string;
};

const STATUS_LABEL = {
  active: { en: "Active", ko: "운영 중" },
  attention: { en: "Needs attention", ko: "확인 필요" },
  completed: { en: "Completed", ko: "완료" },
  setup: { en: "Setup", ko: "설정 중" },
  syncing: { en: "Syncing", ko: "동기화 중" },
};

function activityMetadataText(
  event: ProjectActivityEvent,
  key: string,
): string {
  const value = event.metadata[key];
  return typeof value === "string" ? value.trim() : "";
}

function mapServerActivityEvent(
  event: ProjectActivityEvent,
  language: LanguageSetting,
): ProjectActivityItem | null {
  const isKorean = language === "ko";
  const timestamp = parsePaimTimestamp(event.createdAt);
  if (!Number.isFinite(timestamp)) return null;

  const actor =
    event.actor.name?.trim() ||
    event.actor.email?.split("@")[0] ||
    (isKorean ? "시스템" : "System");
  const filename = activityMetadataText(event, "filename");
  const member =
    activityMetadataText(event, "member_name") ||
    activityMetadataText(event, "member_email") ||
    (isKorean ? "팀원" : "Member");
  const role = activityMetadataText(event, "role");
  const projectName = activityMetadataText(event, "name");
  const sessionTitle = activityMetadataText(event, "title");
  const repositoryUrl = activityMetadataText(event, "repository_url");

  const copy: Record<
    string,
    { detail: string; kind: ProjectActivityItem["kind"]; title: string }
  > = {
    "chat.session_created": {
      detail: sessionTitle || (isKorean ? "새 채팅" : "New chat"),
      kind: "chat",
      title: isKorean ? "채팅을 시작했습니다" : "Started a chat",
    },
    "document.deleted": {
      detail: filename || (isKorean ? "프로젝트 자료" : "Project source"),
      kind: "file",
      title: isKorean ? "자료를 삭제했습니다" : "Deleted a source",
    },
    "document.uploaded": {
      detail: filename || (isKorean ? "프로젝트 자료" : "Project source"),
      kind: "file",
      title: isKorean ? "자료를 추가했습니다" : "Added a source",
    },
    "member.added": {
      detail: role ? `${member} · ${role}` : member,
      kind: "member",
      title: isKorean ? "팀원을 추가했습니다" : "Added a member",
    },
    "member.removed": {
      detail: member,
      kind: "member",
      title: isKorean ? "팀원을 제외했습니다" : "Removed a member",
    },
    "member.role_changed": {
      detail: role ? `${member} · ${role}` : member,
      kind: "member",
      title: isKorean ? "팀원 권한을 변경했습니다" : "Changed a member role",
    },
    "project.created": {
      detail: projectName,
      kind: "project",
      title: isKorean ? "프로젝트를 만들었습니다" : "Created the project",
    },
    "project.setup_completed": {
      detail:
        activityMetadataText(event, "mode") ||
        (isKorean ? "설정 완료" : "Setup complete"),
      kind: "project",
      title: isKorean ? "프로젝트 설정을 완료했습니다" : "Completed setup",
    },
    "project.updated": {
      detail:
        projectName ||
        (isKorean ? "프로젝트 정보를 변경했습니다" : "Project details changed"),
      kind: "project",
      title: isKorean ? "프로젝트를 수정했습니다" : "Updated the project",
    },
    "repository.connected": {
      detail: repositoryUrl || "GitHub",
      kind: "github",
      title: isKorean ? "저장소를 연결했습니다" : "Connected a repository",
    },
    "repository.sync_started": {
      detail: "GitHub",
      kind: "github",
      title: isKorean ? "저장소 동기화를 시작했습니다" : "Started repository sync",
    },
  };
  const mapped = copy[event.eventType] ?? {
    detail: event.entityType,
    kind: "project" as const,
    title: event.eventType.replace(/\./g, " "),
  };

  return {
    description: mapped.detail ? `${actor} · ${mapped.detail}` : actor,
    id: `server-activity-${event.id}`,
    kind: mapped.kind,
    timestamp,
    title: mapped.title,
  };
}

function memberInitial(name: string | null | undefined, email: string) {
  return (name?.trim() || email.split("@")[0] || "?").slice(0, 2).toUpperCase();
}

function ProjectMemberAvatar({
  ariaHidden = false,
  member,
  size = "sm",
}: {
  ariaHidden?: boolean;
  member: {
    email: string;
    name?: string | null;
    profile_image_url?: string | null;
  };
  size?: "sm" | "md";
}) {
  const label = member.name?.trim() || member.email;

  return (
    <ProfileAvatar
      ariaHidden={ariaHidden}
      ariaLabel={label}
      className="project-detail-member-avatar"
      fallback={memberInitial(member.name, member.email)}
      imageUrl={member.profile_image_url}
      label={label}
      size={size}
    />
  );
}

function formatMemberJoinedAt(
  value: string | null | undefined,
  language: LanguageSetting,
) {
  if (!value) return "—";
  const date = new Date(parsePaimTimestamp(value));
  if (!Number.isFinite(date.getTime())) return "—";
  return new Intl.DateTimeFormat(language === "ko" ? "ko-KR" : "en-US", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  }).format(date);
}

function formatMemberLastSeenAt(
  value: string | null | undefined,
  language: LanguageSetting,
) {
  if (!value) return language === "ko" ? "기록 없음" : "No activity";
  const timestamp = parsePaimTimestamp(value);
  if (!Number.isFinite(timestamp)) {
    return language === "ko" ? "기록 없음" : "No activity";
  }
  return formatRelativeAge(timestamp, language);
}

function countNestedEntries(entries: Attachment[]): number {
  return entries.reduce(
    (count, entry) =>
      count + 1 + (entry.children ? countNestedEntries(entry.children) : 0),
    0,
  );
}

function projectFileStatus(
  file: Attachment,
  language: LanguageSetting,
): { label: string; tone: "failed" | "processing" | "ready" | "stored" } {
  if (file.kind === "directory") {
    const count = countNestedEntries(file.children ?? []);
    return {
      label:
        language === "ko"
          ? count
            ? `${count}개 항목`
            : "폴더"
          : count
            ? `${count} items`
            : "Folder",
      tone: "stored",
    };
  }

  if (file.documentStatus === "delayed") {
    return {
      label: isMeetingDocument(file.documentType)
        ? language === "ko"
          ? "음성 전사 지연"
          : "Transcription delayed"
        : language === "ko"
          ? "처리 지연"
          : "Delayed",
      tone: "processing",
    };
  }

  if (file.documentStatus === "failed") {
    return {
      label: isMeetingDocument(file.documentType)
        ? language === "ko"
          ? "음성 전사 실패"
          : "Transcription failed"
        : language === "ko"
          ? "처리 실패"
          : "Failed",
      tone: "failed",
    };
  }

  if (
    file.documentStatus === "uploading" ||
    file.documentStatus === "uploaded" ||
    file.documentStatus === "processing"
  ) {
    return {
      label: isMeetingDocument(file.documentType)
        ? language === "ko"
          ? "음성 전사 중"
          : "Transcribing"
        : language === "ko"
          ? "처리 중"
          : "Processing",
      tone: "processing",
    };
  }

  if (file.documentStatus === "indexed") {
    return {
      label: isMeetingDocument(file.documentType)
        ? language === "ko"
          ? "회의 분석 완료"
          : "Meeting analyzed"
        : language === "ko"
          ? "분석 완료"
          : "Indexed",
      tone: "ready",
    };
  }

  return {
    label: file.serverOnly
      ? language === "ko"
        ? "서버 자료"
        : "Server source"
      : language === "ko"
        ? "프로젝트 자료"
        : "Project source",
    tone: "stored",
  };
}

function dateOnly(value?: string | null) {
  return value?.split("T")[0] ?? "";
}

function isCompleted(item: ProjectMemoryItem) {
  return Boolean(item.completed_at);
}

function isOverdue(item: ProjectMemoryItem, today: string) {
  const dueDate = dateOnly(item.due_date);
  return Boolean(dueDate && dueDate < today && !isCompleted(item));
}

function sourceLabel(item: ProjectMemoryItem, language: LanguageSetting) {
  const source = item.source_info;
  const reference = source?.ref?.trim();
  const path = source?.path?.trim();

  if (source?.kind === "repository" || item.repo_id) {
    if (source?.type === "pull_request" && reference) {
      return `GitHub PR #${reference.replace(/^#/, "")}`;
    }
    return "GitHub";
  }

  if (item.doc_id) {
    return `${language === "ko" ? "자료" : "Source"} #${item.doc_id}`;
  }

  if (path) {
    return path.split(/[\\/]/).pop() || path;
  }

  return `${language === "ko" ? "메모리" : "Memory"} #${item.id}`;
}

export function ProjectDetailPage({
  activeTab,
  composerAttachments,
  composerDisabledMessage,
  composerPrompt,
  currentUserId,
  isComposerSending = false,
  language,
  memoryItems,
  onAddProjectAudio,
  onAddProjectFiles,
  onAddProjectFolder,
  onBack,
  onComposerPickFiles,
  onComposerPromptChange,
  onComposerRemoveAttachment,
  onComposerSubmit,
  onDeleteProjectFile,
  onOpenGithub,
  onManageMembers,
  onOpenManagement,
  onOpenProjectFile,
  onOpenProjectFilesManager,
  onRefreshProjectFileStatus,
  onTabChange,
  project,
  projectRole,
  refreshRevision = 0,
}: ProjectDetailPageProps) {
  const composerTextareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [data, setData] = useState<DetailData | null>(null);
  const [error, setError] = useState("");
  const [pendingDeleteFileId, setPendingDeleteFileId] = useState<string | null>(
    null,
  );
  const [serverActivityItems, setServerActivityItems] = useState<
    ProjectActivityItem[] | null
  >(null);
  const [serverActivityError, setServerActivityError] = useState("");
  const [serverActivityLoading, setServerActivityLoading] = useState(false);
  const [teamMembers, setTeamMembers] = useState<ProjectMember[] | null>(null);
  const [teamMembersError, setTeamMembersError] = useState("");
  const [teamMembersLoading, setTeamMembersLoading] = useState(false);
  const isKorean = language === "ko";
  const isOwner = projectRole === "owner";
  const today = useMemo(() => {
    const now = new Date();
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
      now.getDate(),
    ).padStart(2, "0")}`;
  }, []);

  useEffect(() => {
    setPendingDeleteFileId(null);
    setServerActivityItems(null);
    setServerActivityError("");
    setTeamMembers(null);
    setTeamMembersError("");
  }, [project.id]);

  useEffect(() => {
    let isActive = true;
    setData({
      memories: memoryItems,
      overview: createLocalProjectOverview(project),
    });
    setError("");

    if (typeof project.apiProjectId !== "number") {
      return () => {
        isActive = false;
      };
    }

    void fetchProjectOverviews([project])
      .then((overviews) => {
        if (!isActive) return;
        const overview = overviews.find(
          (candidate) => candidate.id === project.apiProjectId,
        );
        if (!overview) {
          throw new Error(
            isKorean
              ? "프로젝트 현황을 찾을 수 없습니다"
              : "Project overview not found",
          );
        }
        setData((current) => ({
          memories: current?.memories ?? memoryItems,
          overview,
        }));
      })
      .catch(() => {
        if (!isActive) return;
        setError(
          isKorean
            ? "일부 현황을 불러오지 못해 저장된 정보를 표시합니다"
            : "Some project signals could not load; showing saved information",
        );
      });

    return () => {
      isActive = false;
    };
  }, [
    isKorean,
    project.apiProjectId,
    project.id,
    refreshRevision,
  ]);

  useEffect(() => {
    if (activeTab !== "team" || typeof project.apiProjectId !== "number") {
      return;
    }

    let isActive = true;
    setTeamMembersLoading(true);
    setTeamMembersError("");

    void fetchProjectMembers(project.apiProjectId)
      .then((members) => {
        if (!isActive) return;
        setTeamMembers(members);
      })
      .catch(() => {
        if (!isActive) return;
        setTeamMembersError(
          isKorean
            ? "전체 팀원 목록을 불러오지 못했습니다."
            : "The full member list could not be loaded.",
        );
      })
      .finally(() => {
        if (isActive) setTeamMembersLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, [
    activeTab,
    isKorean,
    project.apiProjectId,
    project.id,
    refreshRevision,
  ]);

  useEffect(() => {
    if (
      activeTab !== "activity" ||
      typeof project.apiProjectId !== "number"
    ) {
      return;
    }

    let isActive = true;
    setServerActivityLoading(true);
    setServerActivityError("");

    void fetchProjectActivity(project.apiProjectId)
      .then((page) => {
        if (!isActive) return;
        setServerActivityItems(
          page
            ? page.items
                .map((event) => mapServerActivityEvent(event, language))
                .filter(
                  (item): item is ProjectActivityItem => item !== null,
                )
            : null,
        );
      })
      .catch(() => {
        if (!isActive) return;
        setServerActivityError(
          isKorean
            ? "서버 활동 기록을 불러오지 못해 현재 앱 기록을 표시합니다."
            : "Server activity could not be loaded; showing current app records.",
        );
        setServerActivityItems(null);
      })
      .finally(() => {
        if (isActive) setServerActivityLoading(false);
      });

    return () => {
      isActive = false;
    };
  }, [
    activeTab,
    isKorean,
    language,
    project.apiProjectId,
    project.id,
    refreshRevision,
  ]);

  useEffect(() => {
    setData((current) =>
      current ? { ...current, memories: memoryItems } : current,
    );
  }, [memoryItems]);

  useEffect(() => {
    if (!pendingDeleteFileId) return;
    const timeoutId = window.setTimeout(() => {
      setPendingDeleteFileId(null);
    }, 4000);
    return () => window.clearTimeout(timeoutId);
  }, [pendingDeleteFileId]);

  const derived = useMemo(() => {
    if (!data) return null;
    const activeMemories = data.memories.filter((item) => !item.completed_at);
    const actions = activeMemories
      .filter((item) => item.category === "action")
      .sort((a, b) => {
        const aDue = dateOnly(a.due_date) || "9999-12-31";
        const bDue = dateOnly(b.due_date) || "9999-12-31";
        return (
          aDue.localeCompare(bDue) ||
          (a.sort_order ?? 9999) - (b.sort_order ?? 9999)
        );
      });
    return {
      actions,
      decisions: activeMemories
        .filter((item) => item.category === "decision")
        .slice(0, 3),
      issues: activeMemories
        .filter(
          (item) => item.category === "issue" || item.category === "risk",
        )
        .slice(0, 3),
    };
  }, [data, today]);

  if (!data || !derived) {
    return (
      <section className="project-detail-page">
        <header className="project-detail-toolbar">
          <Button
            icon={<ArrowLeft size={15} />}
            label={isKorean ? "프로젝트 Home" : "Project Home"}
            onClick={onBack}
            size="sm"
            variant="ghost"
          />
        </header>
        <div
          className="project-detail-state"
          data-tone={error ? "error" : "loading"}
          role={error ? "alert" : "status"}
        >
          {error ? <AlertTriangle size={22} /> : <Spinner size="md" />}
          <p>
            {error ||
              (isKorean
                ? "프로젝트 상세를 불러오는 중"
                : "Loading project details")}
          </p>
        </div>
      </section>
    );
  }

  const { overview } = data;
  const completedActions = Math.max(
    0,
    overview.action_count - overview.open_actions,
  );
  const readySources =
    overview.indexed_documents + overview.indexed_repositories;
  const totalSources = overview.document_count + overview.repository_count;
  const progressMetric =
    overview.progress_basis === "actions"
      ? {
          explanation: isKorean
            ? `완료된 액션 ${completedActions}개 ÷ 전체 액션 ${overview.action_count}개로 계산합니다. 프로젝트 전체 완성도를 의미하지 않습니다.`
            : `${completedActions} completed actions divided by ${overview.action_count} total actions. This does not estimate overall project completion.`,
          label: isKorean ? "액션 완료율" : "Action completion",
          value: `${completedActions} / ${overview.action_count}`,
        }
      : overview.progress_basis === "sources"
        ? {
            explanation: isKorean
              ? `분석·인덱싱이 끝난 자료와 저장소 ${readySources}개 ÷ 등록된 전체 자료와 저장소 ${totalSources}개로 계산합니다. 일정 완료율을 의미하지 않습니다.`
              : `${readySources} indexed sources divided by ${totalSources} registered sources. This is not a schedule completion estimate.`,
            label: isKorean ? "자료 준비율" : "Source readiness",
            value: `${readySources} / ${totalSources}`,
          }
        : {
            explanation: isKorean
              ? "액션이나 분석할 자료가 아직 없어 진행률을 계산하지 않습니다. 자료를 추가하고 분석하면 기준이 생깁니다."
              : "There are no actions or analyzable sources yet. Add and analyze sources to establish a progress basis.",
            label: isKorean ? "진행률 기준 없음" : "No progress basis",
            value: "0 / 0",
          };
  const recentActivity = overview.recent_activity_at
    ? parsePaimTimestamp(overview.recent_activity_at)
    : NaN;
  const summary = overview.project_summary?.trim();
  const projectFiles = project.files ?? [];
  const canSubmitComposer =
    !composerDisabledMessage &&
    !isComposerSending &&
    Boolean(composerPrompt.trim() || composerAttachments.length);

  const localActivityItems: ProjectActivityItem[] = [
    ...data.memories.flatMap((item) => {
      const timestamp = parsePaimTimestamp(item.created_at);
      if (!Number.isFinite(timestamp)) return [];
      const kindLabel =
        item.category === "action"
          ? isKorean
            ? "액션"
            : "Action"
          : item.category === "decision"
            ? isKorean
              ? "결정"
              : "Decision"
            : item.category === "issue"
              ? isKorean
                ? "이슈"
                : "Issue"
              : isKorean
                ? "리스크"
                : "Risk";
      return [
        {
          description: sourceLabel(item, language),
          id: `memory-${item.id}`,
          kind: "memory" as const,
          timestamp,
          title: `${kindLabel} · ${item.content}`,
        },
      ];
    }),
    ...projectFiles.flatMap((file) => {
      if (!file.uploadedAt) return [];
      return [
        {
          description:
            file.kind === "directory"
              ? isKorean
                ? "프로젝트 폴더"
                : "Project folder"
              : projectFileStatus(file, language).label,
          id: `file-${file.id}`,
          kind: "file" as const,
          timestamp: file.uploadedAt,
          title: isKorean
            ? `${file.name} 자료 추가`
            : `${file.name} added`,
        },
      ];
    }),
    ...project.sessions.map((session) => ({
      description: isKorean
        ? `${session.messages.length}개 메시지`
        : `${session.messages.length} messages`,
      id: `chat-${session.id}`,
      kind: "chat" as const,
      timestamp: session.createdAt,
      title: isKorean
        ? `${session.title} 채팅 시작`
        : `${session.title} started`,
    })),
    ...(project.githubEvents ?? []).map((event) => ({
      description:
        event.type === "pull_request"
          ? `GitHub PR #${event.number ?? ""}`.trim()
          : event.type === "issue"
            ? `GitHub Issue #${event.number ?? ""}`.trim()
            : "GitHub commit",
      id: `github-${event.id}`,
      kind: "github" as const,
      timestamp: event.createdAt,
      title: event.title,
    })),
  ]
    .filter((item) => Number.isFinite(item.timestamp))
    .sort((a, b) => b.timestamp - a.timestamp)
    .slice(0, 40);
  const activityItems = serverActivityItems ?? localActivityItems;

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    if (canSubmitComposer) {
      event.currentTarget.form?.requestSubmit();
    }
  }

  async function requestProjectFileDelete(file: Attachment) {
    if (!onDeleteProjectFile) return;
    if (pendingDeleteFileId !== file.id) {
      setPendingDeleteFileId(file.id);
      return;
    }
    setPendingDeleteFileId(null);
    await onDeleteProjectFile(file);
  }

  function renderFilesPanel() {
    return (
      <section className="project-detail-rail-card project-detail-files-card project-detail-tab-surface">
        <header className="project-detail-files-header">
          <div className="project-detail-rail-heading">
            <span className="project-detail-rail-heading-icon" aria-hidden="true">
              <Files size={16} />
            </span>
            <div>
              <h2>{isKorean ? "프로젝트 자료" : "Project sources"}</h2>
              <p>
                {isKorean
                  ? `${projectFiles.length}개 자료를 이 프로젝트에서 사용 중`
                  : `${projectFiles.length} sources used in this project`}
              </p>
            </div>
          </div>

          <div className="project-detail-file-add-actions">
            <Button
              icon={<FilePlus2 size={14} />}
              isDisabled={!onAddProjectFiles}
              label={isKorean ? "파일 추가" : "Add files"}
              onClick={onAddProjectFiles}
              size="sm"
              variant="secondary"
            />
            <Button
              icon={<FolderPlus size={14} />}
              isDisabled={!onAddProjectFolder}
              label={isKorean ? "폴더" : "Folder"}
              onClick={onAddProjectFolder}
              size="sm"
              variant="ghost"
            />
            <Button
              icon={<AudioLines size={14} />}
              isDisabled={!onAddProjectAudio}
              label={isKorean ? "회의 음성" : "Meeting audio"}
              onClick={onAddProjectAudio}
              size="sm"
              variant="ghost"
            />
          </div>
        </header>

        {projectFiles.length ? (
          <div
            aria-label={isKorean ? "프로젝트 자료 목록" : "Project source list"}
            className="project-detail-file-list"
            data-full-page="true"
            role="list"
          >
            {projectFiles.map((file) => {
              const status = projectFileStatus(file, language);
              const statusDetail =
                isMeetingDocument(file.documentType) &&
                (file.documentStatus === "failed" ||
                  file.documentStatus === "delayed") &&
                file.lastError
                  ? translate(language, file.lastError)
                  : "";
              const isConfirmingDelete = pendingDeleteFileId === file.id;
              const isDirectory = file.kind === "directory";
              const canOpen = Boolean(
                isMeetingDocument(file.documentType)
                  ? false
                  : isDirectory
                    ? onOpenProjectFilesManager
                    : onOpenProjectFile,
              );

              return (
                <div
                  className="project-detail-file-row"
                  data-confirming={isConfirmingDelete ? "true" : undefined}
                  key={file.id}
                  role="listitem"
                >
                  <button
                    className="project-detail-file-open"
                    data-meeting={
                      isMeetingDocument(file.documentType) ? "true" : undefined
                    }
                    disabled={!canOpen}
                    onClick={() => {
                      if (isDirectory) onOpenProjectFilesManager?.();
                      else onOpenProjectFile?.(file);
                    }}
                    type="button"
                  >
                    <span className="project-detail-file-icon" aria-hidden="true">
                      {isDirectory ? (
                        <Folder size={15} />
                      ) : isMeetingDocument(file.documentType) ? (
                        <AudioLines size={15} />
                      ) : (
                        <File size={15} />
                      )}
                    </span>
                    <span className="project-detail-file-copy">
                      <strong>{file.name}</strong>
                      <small data-tone={status.tone}>
                        <i aria-hidden="true" />
                        {status.label}
                        {statusDetail ? ` · ${statusDetail}` : ""}
                        {file.uploadedAt
                          ? ` · ${formatRelativeAge(file.uploadedAt, language)}`
                          : ""}
                      </small>
                    </span>
                  </button>
                  {isMeetingDocument(file.documentType) &&
                  (file.documentStatus === "processing" ||
                    file.documentStatus === "delayed") ? (
                    <button
                      aria-label={isKorean ? "상태 새로고침" : "Refresh status"}
                      className="project-detail-file-delete"
                      disabled={!onRefreshProjectFileStatus}
                      onClick={() => onRefreshProjectFileStatus?.(file)}
                      title={isKorean ? "상태 새로고침" : "Refresh status"}
                      type="button"
                    >
                      <RefreshCw aria-hidden="true" size={13} />
                    </button>
                  ) : null}
                  {isConfirmingDelete ? (
                    <span
                      aria-label={
                        isKorean
                          ? `${file.name} 삭제 확인`
                          : `Confirm deleting ${file.name}`
                      }
                      className="project-detail-file-delete-confirmation"
                      role="group"
                    >
                      <span>{isKorean ? "삭제할까요?" : "Delete?"}</span>
                      <button
                        autoFocus
                        onClick={() => setPendingDeleteFileId(null)}
                        type="button"
                      >
                        {isKorean ? "취소" : "Cancel"}
                      </button>
                      <button
                        className="project-detail-file-delete-confirm"
                        onClick={() => void requestProjectFileDelete(file)}
                        type="button"
                      >
                        {isKorean ? "삭제" : "Delete"}
                      </button>
                    </span>
                  ) : (
                    <button
                      aria-label={
                        isKorean ? `${file.name} 삭제` : `Delete ${file.name}`
                      }
                      className="project-detail-file-delete"
                      disabled={!onDeleteProjectFile}
                      onClick={() => void requestProjectFileDelete(file)}
                      title={isKorean ? "자료 삭제" : "Delete source"}
                      type="button"
                    >
                      <Trash2 aria-hidden="true" size={13} />
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="project-detail-file-empty">
            <FilePlus2 aria-hidden="true" size={20} />
            <strong>{isKorean ? "아직 자료가 없습니다" : "No sources yet"}</strong>
            <p>
              {isKorean
                ? "파일을 추가하면 브리핑과 채팅에서 함께 활용됩니다."
                : "Add files to use them in briefings and chats."}
            </p>
          </div>
        )}

        <footer className="project-detail-files-footer">
          <Button
            className="project-detail-manage-all"
            endContent={<ArrowRight size={13} />}
            isDisabled={!onOpenProjectFilesManager}
            label={isKorean ? "자료 전체 관리" : "Manage all sources"}
            onClick={onOpenProjectFilesManager}
            size="sm"
            variant="ghost"
          />
        </footer>
      </section>
    );
  }

  function renderTeamPanel() {
    const members: ProjectMember[] =
      teamMembers ??
      overview.members.map((member) => ({
        created_at: null,
        email: member.email,
        last_seen_at: null,
        name: member.name ?? "",
        profile_image_url: member.profile_image_url,
        role: member.role as ProjectRole,
        user_id: member.id,
      }));
    const hasHiddenMembers =
      !teamMembers && overview.member_count > overview.members.length;

    return (
      <section
        className="project-detail-team-card project-detail-tab-surface"
        data-testid="project-detail-team-surface"
      >
        <header className="project-detail-team-header">
          <div>
            <div className="project-detail-team-title">
              <h2>{isKorean ? "프로젝트 팀" : "Project team"}</h2>
              <span>{overview.member_count}</span>
            </div>
            <p>
              {isOwner
                ? isKorean
                  ? "이 프로젝트에 참여 중인 팀원입니다."
                  : "People participating in this project."
                : isKorean
                  ? "프로젝트 참여자를 확인할 수 있습니다."
                  : "View the people participating in this project."}
            </p>
          </div>
          <div className="project-detail-team-header-action">
            {isOwner ? (
              <Button
                className="project-detail-rail-manage-members"
                data-testid="project-detail-team-manage"
                icon={<Users size={14} />}
                label={isKorean ? "팀원 관리" : "Manage members"}
                onClick={(event) => onManageMembers(event.currentTarget)}
                size="sm"
                variant="secondary"
              />
            ) : null}
            <small>
              {isKorean
                ? "팀원 초대와 권한 변경은 Owner가 관리합니다."
                : "The Owner manages invitations and role changes."}
            </small>
          </div>
        </header>

        {members.length ? (
          <div
            aria-label={isKorean ? "프로젝트 팀원" : "Project members"}
            className="project-detail-team-table"
            data-testid="project-detail-team-table"
            role="table"
          >
            <div className="project-detail-team-table-head" role="row">
              <span role="columnheader">{isKorean ? "이름" : "Name"}</span>
              <span role="columnheader">{isKorean ? "역할" : "Role"}</span>
              <span role="columnheader">
                {isKorean ? "참여일" : "Joined"}
              </span>
              <span role="columnheader">
                {isKorean ? "최근 활동" : "Last activity"}
              </span>
            </div>
            {members.map((member) => {
              const isCurrentUser = member.user_id === currentUserId;
              return (
                <div
                  className="project-detail-team-member"
                  data-current-user={isCurrentUser ? "true" : undefined}
                  data-role={member.role}
                  data-testid="project-detail-team-row"
                  key={member.user_id}
                  role="row"
                >
                  <span
                    className="project-detail-team-identity"
                    data-label={isKorean ? "이름" : "Name"}
                    role="cell"
                  >
                    <ProjectMemberAvatar
                      ariaHidden
                      member={member}
                      size="md"
                    />
                    <span>
                      <strong>
                        {member.name?.trim() || member.email.split("@")[0]}
                        {isCurrentUser ? (
                          <small className="project-detail-team-self">
                            {isKorean ? "나" : "You"}
                          </small>
                        ) : null}
                      </strong>
                      <small>{member.email}</small>
                    </span>
                  </span>
                  <span data-label={isKorean ? "역할" : "Role"} role="cell">
                    <span className="project-detail-team-role">
                      {member.role.slice(0, 1).toUpperCase() +
                        member.role.slice(1)}
                    </span>
                  </span>
                  <time
                    data-label={isKorean ? "참여일" : "Joined"}
                    dateTime={member.created_at ?? undefined}
                    role="cell"
                  >
                    {formatMemberJoinedAt(member.created_at, language)}
                  </time>
                  <time
                    data-label={isKorean ? "최근 활동" : "Last activity"}
                    dateTime={member.last_seen_at ?? undefined}
                    role="cell"
                  >
                    {formatMemberLastSeenAt(member.last_seen_at, language)}
                  </time>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="project-detail-team-empty">
            {isKorean
              ? "표시할 팀원 정보가 없습니다."
              : "No member details available."}
          </p>
        )}

        {teamMembersLoading ? (
          <p className="project-detail-team-feedback" role="status">
            <Spinner size="sm" />
            {isKorean ? "전체 팀원을 불러오는 중" : "Loading all members"}
          </p>
        ) : null}
        {teamMembersError ? (
          <p
            className="project-detail-team-feedback"
            data-tone="error"
            role="alert"
          >
            <AlertTriangle aria-hidden="true" size={13} />
            {teamMembersError}
          </p>
        ) : null}
        {hasHiddenMembers && !teamMembersLoading && !teamMembersError ? (
          <p className="project-detail-team-feedback">
            {isKorean
              ? "서버 연결 후 전체 팀원 정보를 확인할 수 있습니다."
              : "Connect to the server to view the complete team."}
          </p>
        ) : null}

        <footer className="project-detail-team-note">
          <Info aria-hidden="true" size={13} />
          <span>
            {isOwner
              ? isKorean
                ? "Owner는 프로젝트의 팀원 초대, 역할 변경 등 권한을 관리할 수 있습니다."
                : "Owners can invite members and manage project roles."
              : isKorean
                ? "Member 권한으로 팀 정보를 확인하고 프로젝트에서 협업할 수 있습니다."
                : "Members can view team information and collaborate in this project."}
          </span>
        </footer>
      </section>
    );
  }

  function renderOverviewContext() {
    const decisions = derived?.decisions ?? [];
    const issues = derived?.issues ?? [];
    const sourceStatus = isKorean
      ? `분석 완료 ${overview.indexed_documents} · 처리 중 ${overview.processing_documents} · 실패 ${overview.failed_documents}`
      : `${overview.indexed_documents} indexed · ${overview.processing_documents} processing · ${overview.failed_documents} failed`;
    const repositoryStatus = overview.repository_count
      ? isKorean
        ? `${overview.repository_count}개 연결 · 동기화 중 ${overview.syncing_repositories} · 실패 ${overview.failed_repositories}`
        : `${overview.repository_count} connected · ${overview.syncing_repositories} syncing · ${overview.failed_repositories} failed`
      : isKorean
        ? "연결된 저장소 없음"
        : "No repository connected";
    const recentActivityLabel = Number.isFinite(recentActivity)
      ? formatRelativeAge(recentActivity, language)
      : isKorean
        ? "기록 없음"
        : "No activity";

    return (
      <aside
        aria-label={isKorean ? "프로젝트 요약" : "Project summary"}
        className="project-detail-overview-context"
      >
        <section
          className="project-detail-overview-briefing"
          data-testid="project-detail-overview-briefing"
        >
          <div className="project-detail-overview-briefing-section">
            <h2>{isKorean ? "프로젝트 요약" : "Project summary"}</h2>
            <p>
              {summary ||
                (isKorean
                  ? "아직 생성된 프로젝트 브리핑이 없습니다. 프로젝트 자료가 분석되면 여기에 요약됩니다."
                  : "No project briefing yet. It will appear after project sources are analyzed.")}
            </p>
          </div>
          <div className="project-detail-overview-briefing-section">
            <h3>{isKorean ? "주요 결정 사항" : "Key decisions"}</h3>
            {decisions.length ? (
              <ul>
                {decisions.map((item) => (
                  <li key={item.id}>{item.content}</li>
                ))}
              </ul>
            ) : (
              <p className="project-detail-overview-empty-copy">
                {isKorean ? "저장된 결정이 없습니다." : "No saved decisions."}
              </p>
            )}
          </div>
          <div className="project-detail-overview-briefing-section">
            <h3>{isKorean ? "이슈/위험 요인" : "Issues and risks"}</h3>
            {issues.length ? (
              <ul>
                {issues.map((item) => (
                  <li key={item.id}>{item.content}</li>
                ))}
              </ul>
            ) : (
              <p className="project-detail-overview-empty-copy">
                {isKorean
                  ? "열린 이슈나 위험 요인이 없습니다."
                  : "No open issues or risks."}
              </p>
            )}
          </div>
        </section>

        <div className="project-detail-overview-links">
          <button
            data-testid="project-detail-overview-sources-summary"
            onClick={() => onTabChange("files")}
            type="button"
          >
            <span className="project-detail-overview-link-icon" aria-hidden="true">
              <FileText size={17} />
            </span>
            <span>
              <strong>
                {isKorean
                  ? `자료 ${overview.document_count}개`
                  : `${overview.document_count} sources`}
              </strong>
              <small>{sourceStatus}</small>
            </span>
            <ArrowRight aria-hidden="true" size={16} />
          </button>
          <button
            data-testid="project-detail-overview-team-summary"
            onClick={() => onTabChange("team")}
            type="button"
          >
            <span className="project-detail-overview-link-icon" aria-hidden="true">
              <Users size={17} />
            </span>
            <span>
              <strong>
                {isKorean
                  ? `팀 ${overview.member_count}명`
                  : `${overview.member_count} team members`}
              </strong>
              <small>
                {isOwner
                  ? isKorean
                    ? "팀 정보와 역할 확인"
                    : "View team and roles"
                  : isKorean
                    ? "프로젝트 참여자 확인"
                    : "View project participants"}
              </small>
            </span>
            <span
              aria-hidden="true"
              className="project-detail-overview-member-stack"
            >
              {overview.members.slice(0, 3).map((member) => (
                <ProjectMemberAvatar key={member.id} member={member} />
              ))}
              {overview.member_count > 3 ? (
                <span>+{overview.member_count - 3}</span>
              ) : null}
            </span>
            <ArrowRight aria-hidden="true" size={16} />
          </button>
          {onOpenGithub ? (
            <button
              data-testid="project-detail-overview-github-summary"
              onClick={onOpenGithub}
              type="button"
            >
              <span
                className="project-detail-overview-link-icon"
                aria-hidden="true"
              >
                <GitBranch size={17} />
              </span>
              <span>
                <strong>{isKorean ? "GitHub 저장소" : "GitHub repository"}</strong>
                <small>{repositoryStatus}</small>
              </span>
              <ArrowRight aria-hidden="true" size={16} />
            </button>
          ) : (
            <div data-testid="project-detail-overview-github-summary">
              <span
                className="project-detail-overview-link-icon"
                aria-hidden="true"
              >
                <GitBranch size={17} />
              </span>
              <span>
                <strong>{isKorean ? "GitHub 저장소" : "GitHub repository"}</strong>
                <small>{repositoryStatus}</small>
              </span>
            </div>
          )}
          <button
            data-testid="project-detail-overview-activity-summary"
            onClick={() => onTabChange("activity")}
            type="button"
          >
            <span className="project-detail-overview-link-icon" aria-hidden="true">
              <Activity size={17} />
            </span>
            <span>
              <strong>{isKorean ? "최근 활동" : "Recent activity"}</strong>
              <small>{recentActivityLabel}</small>
            </span>
            <ArrowRight aria-hidden="true" size={16} />
          </button>
        </div>
      </aside>
    );
  }

  function renderComposer() {
    return (
      <section
        aria-label={isKorean ? "새 채팅 시작" : "Start a new chat"}
        className="project-detail-chat-entry"
      >
        <form
          className="project-detail-composer"
          data-disabled={
            Boolean(composerDisabledMessage) || isComposerSending
              ? "true"
              : undefined
          }
          data-drop-zone="prompt"
          data-testid="project-detail-chat-composer"
          onPointerDown={(event) => {
            const target = event.target;
            if (
              !(target instanceof Element) ||
              target.closest("button, textarea, input, a, [role='button']") ||
              composerDisabledMessage ||
              isComposerSending
            ) {
              return;
            }
            composerTextareaRef.current?.focus();
          }}
          onSubmit={(event) => {
            event.preventDefault();
            if (canSubmitComposer) {
              void onComposerSubmit();
            }
          }}
        >
          <label className="project-detail-composer-input">
            <span className="project-detail-visually-hidden">
              {isKorean ? "프로젝트에 질문하기" : "Ask about this project"}
            </span>
            <textarea
              aria-describedby="project-detail-composer-helper"
              disabled={Boolean(composerDisabledMessage) || isComposerSending}
              onChange={(event) =>
                onComposerPromptChange(event.currentTarget.value)
              }
              onKeyDown={handleComposerKeyDown}
              placeholder={
                isKorean
                  ? "이 프로젝트에 무엇이든 요청하세요"
                  : "Ask anything about this project"
              }
              ref={composerTextareaRef}
              rows={1}
              value={composerPrompt}
            />
          </label>

          {composerAttachments.length ? (
            <div
              aria-label={isKorean ? "전송할 첨부 파일" : "Attachments to send"}
              className="project-detail-composer-attachments"
              role="list"
            >
              {composerAttachments.map((attachment) => (
                <span
                  className="project-detail-composer-attachment"
                  key={attachment.id}
                  role="listitem"
                >
                  <FileText aria-hidden="true" size={13} />
                  <span>{attachment.name}</span>
                  <button
                    aria-label={
                      isKorean
                        ? `${attachment.name} 첨부 제거`
                        : `Remove ${attachment.name}`
                    }
                    onClick={() => onComposerRemoveAttachment(attachment.id)}
                    type="button"
                  >
                    <X aria-hidden="true" size={12} />
                  </button>
                </span>
              ))}
            </div>
          ) : null}

          <div className="project-detail-composer-toolbar">
            <button
              aria-label={isKorean ? "파일 추가" : "Add files"}
              className="project-detail-composer-add"
              disabled={!onComposerPickFiles || Boolean(composerDisabledMessage)}
              onClick={onComposerPickFiles}
              title={
                composerDisabledMessage || (isKorean ? "파일 추가" : "Add files")
              }
              type="button"
            >
              <Plus aria-hidden="true" size={18} />
            </button>
            <p id="project-detail-composer-helper">
              {composerDisabledMessage ||
                (isKorean
                  ? "메시지를 보내면 이 프로젝트 아래에 새 채팅이 생성됩니다"
                  : "Sending creates a new chat under this project")}
            </p>
            <button
              aria-label={isKorean ? "메시지 보내기" : "Send message"}
              className="project-detail-composer-send"
              disabled={!canSubmitComposer}
              type="submit"
            >
              <ArrowUp aria-hidden="true" size={18} />
            </button>
          </div>
        </form>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="project-detail-title"
      className="project-detail-page"
    >
      <header className="project-detail-toolbar">
        <Button
          icon={<ArrowLeft size={15} />}
          label={isKorean ? "프로젝트 Home" : "Project Home"}
          onClick={onBack}
          size="sm"
          variant="ghost"
        />
      </header>

      {error ? (
        <div className="project-detail-load-warning" role="alert">
          <AlertTriangle aria-hidden="true" size={15} />
          <span>{error}</span>
        </div>
      ) : null}

      <div className="project-detail-content">
        <header className="project-detail-hero">
          <div className="project-detail-hero-copy">
            <div className="project-detail-title-row">
              <h1 id="project-detail-title">{project.name}</h1>
              <span
                className="project-detail-status"
                data-health={overview.health}
              >
                {overview.health === "attention" ? (
                  <AlertTriangle size={14} />
                ) : overview.health === "syncing" ? (
                  <RefreshCw size={14} />
                ) : (
                  <CheckCircle2 size={14} />
                )}
                {STATUS_LABEL[overview.health][language]}
              </span>
            </div>
            <p>
              <Clock3 size={13} />
              {Number.isFinite(recentActivity)
                ? `${isKorean ? "최근 활동" : "Last activity"} · ${formatRelativeAge(
                    recentActivity,
                    language,
                  )}`
                : isKorean
                  ? "아직 기록된 활동이 없습니다"
                  : "No recorded activity yet"}
            </p>
          </div>

          {isOwner && onOpenManagement ? (
            <div className="project-detail-hero-actions">
              <Button
                className="project-detail-open-management"
                icon={<Settings2 size={14} />}
                label={isKorean ? "관리" : "Manage"}
                onClick={(event) =>
                  onOpenManagement(event.currentTarget)
                }
                size="sm"
                variant="primary"
              />
            </div>
          ) : null}
        </header>

        {renderComposer()}

        <nav
          aria-label={isKorean ? "프로젝트 상세 메뉴" : "Project detail menu"}
          className="project-detail-tabs"
          role="tablist"
        >
          {(
            [
              ["overview", isKorean ? "개요" : "Overview"],
              ["files", isKorean ? "자료" : "Sources"],
              ["team", isKorean ? "팀" : "Team"],
              ["activity", isKorean ? "활동" : "Activity"],
            ] as const
          ).map(([tab, label]) => (
            <button
              aria-controls={`project-detail-panel-${tab}`}
              aria-selected={activeTab === tab}
              data-testid={`project-detail-tab-${tab}`}
              id={`project-detail-tab-${tab}`}
              key={tab}
              onClick={() => onTabChange(tab)}
              role="tab"
              type="button"
            >
              {label}
            </button>
          ))}
        </nav>

        {activeTab === "overview" ? (
          <div
            aria-labelledby="project-detail-tab-overview"
            className="project-detail-tab-panel project-detail-overview-panel"
            data-testid="project-detail-panel-overview"
            id="project-detail-panel-overview"
            role="tabpanel"
          >
            <div className="project-detail-workspace-layout">
              <main className="project-detail-main">
                <section
                  aria-labelledby="project-progress-title"
                  className="project-detail-progress"
                  data-testid="project-detail-overview-progress"
                >
                  <div className="project-detail-progress-copy">
                    <p id="project-progress-title">{progressMetric.label}</p>
                    <strong>{progressMetric.value}</strong>
                  </div>
                  <div className="project-detail-progress-visual">
                    <strong>{overview.progress_percent ?? 0}%</strong>
                    <div
                      aria-valuemax={100}
                      aria-valuemin={0}
                      aria-valuenow={overview.progress_percent ?? 0}
                      className="project-detail-progress-track"
                      role="progressbar"
                    >
                      <span
                        style={{
                          width: `${overview.progress_percent ?? 0}%`,
                        }}
                      />
                    </div>
                  </div>
                  <p className="project-detail-progress-explanation">
                    {progressMetric.explanation}
                  </p>
                </section>

                <section
                  aria-labelledby="next-actions-title"
                  className="project-detail-actions-panel"
                  data-testid="project-detail-overview-actions"
                >
                  <div className="project-detail-panel-head">
                    <h2 id="next-actions-title">
                      {isKorean ? "다음 액션" : "Next actions"}
                    </h2>
                    <span className="project-detail-actions-count">
                      {isKorean
                        ? `상위 ${Math.min(3, derived.actions.length)}개`
                        : `Top ${Math.min(3, derived.actions.length)}`}
                    </span>
                  </div>

                  <div
                    aria-label={isKorean ? "다음 액션" : "Next actions"}
                    className="project-detail-action-table"
                    role="table"
                  >
                    <div className="project-detail-action-head" role="row">
                      <span role="columnheader">
                        {isKorean ? "액션" : "Action"}
                      </span>
                      <span role="columnheader">
                        {isKorean ? "담당자" : "Owner"}
                      </span>
                      <span role="columnheader">
                        {isKorean ? "기한" : "Due"}
                      </span>
                      <span role="columnheader">
                        {isKorean ? "상태" : "Status"}
                      </span>
                      <span role="columnheader">
                        {isKorean ? "출처" : "Source"}
                      </span>
                    </div>
                    {derived.actions.length ? (
                      derived.actions.slice(0, 3).map((item) => {
                        const overdue = isOverdue(item, today);
                        return (
                          <div
                            className="project-detail-action-row"
                            key={item.id}
                            role="row"
                          >
                            <span
                              data-label={isKorean ? "액션" : "Action"}
                              role="cell"
                            >
                              <strong>{item.content}</strong>
                            </span>
                            <span
                              data-label={isKorean ? "담당자" : "Owner"}
                              role="cell"
                            >
                              {item.owner?.trim() || "—"}
                            </span>
                            <time
                              data-label={isKorean ? "기한" : "Due"}
                              data-overdue={overdue ? "true" : undefined}
                              role="cell"
                            >
                              {dateOnly(item.due_date) || "—"}
                            </time>
                            <span
                              data-label={isKorean ? "상태" : "Status"}
                              role="cell"
                            >
                              <span
                                className="project-detail-action-status"
                                data-overdue={overdue ? "true" : undefined}
                              >
                                {overdue
                                  ? isKorean
                                    ? "기한 초과"
                                    : "Overdue"
                                  : isKorean
                                    ? "진행 중"
                                    : "Open"}
                              </span>
                            </span>
                            <span
                              data-label={isKorean ? "출처" : "Source"}
                              role="cell"
                            >
                              <small>
                                {item.source_info?.type === "pull_request" ? (
                                  <GitPullRequest
                                    aria-hidden="true"
                                    size={13}
                                  />
                                ) : item.doc_id ? (
                                  <FileText aria-hidden="true" size={13} />
                                ) : (
                                  <MessageSquare
                                    aria-hidden="true"
                                    size={13}
                                  />
                                )}
                                {sourceLabel(item, language)}
                              </small>
                            </span>
                          </div>
                        );
                      })
                    ) : (
                      <p className="project-detail-empty-row" role="row">
                        {isKorean
                          ? "등록된 다음 액션이 없습니다."
                          : "No next actions have been saved."}
                      </p>
                    )}
                  </div>
                </section>

              </main>
              {renderOverviewContext()}
            </div>
          </div>
        ) : null}

        {activeTab === "files" ? (
          <div
            aria-labelledby="project-detail-tab-files"
            className="project-detail-tab-panel"
            data-testid="project-detail-panel-files"
            id="project-detail-panel-files"
            role="tabpanel"
          >
            {renderFilesPanel()}
          </div>
        ) : null}

        {activeTab === "team" ? (
          <div
            aria-labelledby="project-detail-tab-team"
            className="project-detail-tab-panel"
            data-testid="project-detail-panel-team"
            id="project-detail-panel-team"
            role="tabpanel"
          >
            {renderTeamPanel()}
          </div>
        ) : null}

        {activeTab === "activity" ? (
          <div
            aria-labelledby="project-detail-tab-activity"
            className="project-detail-tab-panel"
            data-testid="project-detail-panel-activity"
            id="project-detail-panel-activity"
            role="tabpanel"
          >
            <section className="project-detail-activity project-detail-tab-surface">
              <header className="project-detail-tab-heading">
                <div>
                  <h2>{isKorean ? "프로젝트 활동" : "Project activity"}</h2>
                  <p>
                    {serverActivityItems
                      ? isKorean
                        ? "서버에 기록된 프로젝트 변경을 최근 순으로 표시합니다."
                        : "Server-recorded project changes in newest-first order."
                      : isKorean
                        ? "현재 앱에서 확인 가능한 채팅·자료·메모리·GitHub 생성 기록입니다."
                        : "Creation records currently available from chats, sources, memories, and GitHub."}
                  </p>
                </div>
                <span>{activityItems.length}</span>
              </header>
              {serverActivityLoading ? (
                <p className="project-detail-activity-feedback" role="status">
                  <Spinner size="sm" />
                  {isKorean
                    ? "서버 활동 기록을 불러오는 중"
                    : "Loading server activity"}
                </p>
              ) : null}
              {serverActivityError ? (
                <p
                  className="project-detail-activity-feedback"
                  data-tone="error"
                  role="alert"
                >
                  <AlertTriangle aria-hidden="true" size={13} />
                  {serverActivityError}
                </p>
              ) : null}
              {activityItems.length ? (
                <ol className="project-detail-activity-list">
                  {activityItems.map((item) => {
                    const Icon =
                      item.kind === "chat"
                        ? MessageSquare
                        : item.kind === "file"
                          ? FileText
                          : item.kind === "github"
                            ? GitBranch
                            : item.kind === "member"
                              ? Users
                              : item.kind === "project"
                                ? Settings2
                                : Activity;
                    return (
                      <li key={item.id}>
                        <span className="project-detail-activity-icon">
                          <Icon aria-hidden="true" size={15} />
                        </span>
                        <div>
                          <strong>{item.title}</strong>
                          <small>{item.description}</small>
                        </div>
                        <time dateTime={new Date(item.timestamp).toISOString()}>
                          {formatRelativeAge(item.timestamp, language)}
                        </time>
                      </li>
                    );
                  })}
                </ol>
              ) : (
                <div className="project-detail-activity-empty">
                  <Activity aria-hidden="true" size={24} />
                  <strong>
                    {isKorean
                      ? "아직 기록된 활동이 없습니다"
                      : "No activity yet"}
                  </strong>
                  <p>
                    {isKorean
                      ? "채팅을 시작하거나 자료를 추가하면 활동이 여기에 쌓입니다."
                      : "Start a chat or add a source to build the activity history."}
                  </p>
                </div>
              )}
            </section>
          </div>
        ) : null}
      </div>
    </section>
  );
}
