import { fetchPaimJson, isPaimApiError } from "./paimApi";
import { parsePaimTimestamp } from "./format";
import {
  isProjectSetupComplete,
  type ProjectMemoryItem,
  type ProjectWorkspace,
} from "./types";

export type ProjectHealth = "active" | "attention" | "completed" | "setup" | "syncing";

export type ProjectOverviewMember = {
  id: number;
  name?: string | null;
  email: string;
  profile_image_url?: string | null;
  role: string;
};

export type ProjectOverview = {
  id: number;
  local_project_id?: string;
  name: string;
  health: ProjectHealth;
  member_count: number;
  members: ProjectOverviewMember[];
  document_count: number;
  indexed_documents: number;
  processing_documents: number;
  failed_documents: number;
  repository_count: number;
  indexed_repositories: number;
  syncing_repositories: number;
  failed_repositories: number;
  memory_count: number;
  action_count: number;
  open_actions: number;
  overdue_actions: number;
  issue_count: number;
  risk_count: number;
  progress_percent?: number | null;
  progress_basis: "actions" | "empty" | "sources";
  project_summary?: string | null;
  project_summary_updated_at?: string | null;
  recent_activity_at?: string | null;
};

type LegacyProjectMember = {
  user_id: number;
  name?: string | null;
  email: string;
  profile_image_url?: string | null;
  role: string;
};

type LegacyProjectDocument = {
  status: string;
  uploaded_at?: string | null;
};

type LegacyProjectRepository = {
  status: string;
  connected_at?: string | null;
};

function latestTimestamp(values: Array<string | null | undefined>) {
  return values
    .filter((value): value is string => Boolean(value))
    .sort((a, b) => parsePaimTimestamp(b) - parsePaimTimestamp(a))[0] ?? null;
}

export function createLocalProjectOverview(project: ProjectWorkspace): ProjectOverview {
  const isSetupComplete = isProjectSetupComplete(project);

  return {
    id: project.apiProjectId ?? -1,
    local_project_id: project.id,
    name: project.name,
    health: isSetupComplete ? "active" : "setup",
    member_count: 0,
    members: [],
    document_count: 0,
    indexed_documents: 0,
    processing_documents: 0,
    failed_documents: 0,
    repository_count: 0,
    indexed_repositories: 0,
    syncing_repositories: 0,
    failed_repositories: 0,
    memory_count: 0,
    action_count: 0,
    open_actions: 0,
    overdue_actions: 0,
    issue_count: 0,
    risk_count: 0,
    progress_percent: null,
    progress_basis: "empty",
    recent_activity_at: null,
  };
}

/**
 * Compatibility path for older PaiM servers that predate /projects-overview.
 * Remove this after the minimum supported backend version exposes that endpoint.
 */
async function loadLegacyOverview(project: ProjectWorkspace): Promise<ProjectOverview> {
  if (typeof project.apiProjectId !== "number") {
    return createLocalProjectOverview(project);
  }

  const projectId = project.apiProjectId;
  try {
    const [members, documents, repositories, memories] = await Promise.all([
      fetchPaimJson<LegacyProjectMember[]>(`/projects/${projectId}/members`),
      fetchPaimJson<LegacyProjectDocument[]>(`/projects/${projectId}/documents`),
      fetchPaimJson<LegacyProjectRepository[]>(`/projects/${projectId}/repositories`),
      fetchPaimJson<ProjectMemoryItem[]>(`/projects/${projectId}/memory`),
    ]);
    const today = new Date().toISOString().slice(0, 10);
    const actions = memories.filter((item) => item.category === "action");
    const openActions = actions.filter((item) => !item.completed_at);
    const overdueActions = openActions.filter(
      (item) => item.due_date && item.due_date.split("T")[0] < today,
    );
    const indexedDocuments = documents.filter((item) => item.status === "indexed").length;
    const processingDocuments = documents.filter((item) =>
      ["uploading", "uploaded", "processing"].includes(item.status),
    ).length;
    const failedDocuments = documents.filter((item) =>
      ["failed", "delayed"].includes(item.status),
    ).length;
    const indexedRepositories = repositories.filter((item) => item.status === "indexed").length;
    const syncingRepositories = repositories.filter((item) => item.status === "syncing").length;
    const failedRepositories = repositories.filter((item) => item.status === "failed").length;
    const issueCount = memories.filter((item) => item.category === "issue").length;
    const riskCount = memories.filter((item) => item.category === "risk").length;
    const hasAttention = failedDocuments || failedRepositories || overdueActions.length;
    const isSyncing = processingDocuments || syncingRepositories;
    const isComplete =
      actions.length > 0 && openActions.length === 0 && issueCount === 0 && riskCount === 0;
    const isActive =
      indexedDocuments ||
      indexedRepositories ||
      memories.length ||
      issueCount ||
      riskCount ||
      openActions.length;
    const setupComplete = isProjectSetupComplete(project);
    const readySources = indexedDocuments + indexedRepositories;
    const totalSources = documents.length + repositories.length;
    const progressPercent = actions.length
      ? Math.round(((actions.length - openActions.length) * 100) / actions.length)
      : totalSources
        ? Math.round((readySources * 100) / totalSources)
        : null;

    return {
      id: projectId,
      local_project_id: project.id,
      name: project.name,
      health: hasAttention
        ? "attention"
        : isSyncing
          ? "syncing"
          : isComplete
            ? "completed"
            : isActive || setupComplete
              ? "active"
              : "setup",
      member_count: members.length,
      members: members.slice(0, 5).map((member) => ({
        id: member.user_id,
        name: member.name,
        email: member.email,
        profile_image_url: member.profile_image_url,
        role: member.role,
      })),
      document_count: documents.length,
      indexed_documents: indexedDocuments,
      processing_documents: processingDocuments,
      failed_documents: failedDocuments,
      repository_count: repositories.length,
      indexed_repositories: indexedRepositories,
      syncing_repositories: syncingRepositories,
      failed_repositories: failedRepositories,
      memory_count: memories.length,
      action_count: actions.length,
      open_actions: openActions.length,
      overdue_actions: overdueActions.length,
      issue_count: issueCount,
      risk_count: riskCount,
      progress_percent: progressPercent,
      progress_basis: actions.length ? "actions" : totalSources ? "sources" : "empty",
      recent_activity_at: latestTimestamp([
        ...documents.map((item) => item.uploaded_at),
        ...repositories.map((item) => item.connected_at),
        ...memories.map((item) => item.created_at),
      ]),
    };
  } catch (error) {
    if (isPaimApiError(error) && error.status === 404) {
      return createLocalProjectOverview(project);
    }
    throw error;
  }
}

export async function fetchProjectOverviews(
  localProjects: ProjectWorkspace[],
): Promise<ProjectOverview[]> {
  try {
    const overviews = await fetchPaimJson<ProjectOverview[]>("/projects-overview");
    const serverOverviews = overviews.map((overview) => {
      const localProject = localProjects.find(
        (project) => project.apiProjectId === overview.id,
      );
      if (!localProject) return overview;

      return {
        ...overview,
        local_project_id: localProject.id,
        health:
          overview.health === "setup" && isProjectSetupComplete(localProject)
            ? "active"
            : overview.health,
      };
    });
    const localOnlyOverviews = localProjects
      .filter(
        (project) =>
          !serverOverviews.some(
            (overview) =>
              overview.local_project_id === project.id ||
              (typeof project.apiProjectId === "number" &&
                overview.id === project.apiProjectId),
          ),
      )
      .map(createLocalProjectOverview);

    return [...localOnlyOverviews, ...serverOverviews];
  } catch (error) {
    if (!isPaimApiError(error)) {
      return localProjects.map(createLocalProjectOverview);
    }
    if (error.status !== 404) {
      throw error;
    }
    return Promise.all(localProjects.map(loadLegacyOverview));
  }
}
