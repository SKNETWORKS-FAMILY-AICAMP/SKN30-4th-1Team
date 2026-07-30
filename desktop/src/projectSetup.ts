import type { ProjectWorkspace } from "./types";

export type ApiProjectSetupState = {
  created_at?: string;
  setup_status?: "draft" | "ready";
  setup_mode?: ProjectWorkspace["setupMode"] | null;
  setup_completed_at?: string | null;
};

type NormalizedProjectSetup = Pick<
  ProjectWorkspace,
  "setupCompletedAt" | "setupMode"
>;

function parseTimestamp(value: string | null | undefined) {
  const normalized = value?.trim();
  const timestamp = normalized
    ? Date.parse(
        /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(
          normalized,
        )
          ? `${normalized.replace(" ", "T")}Z`
          : normalized,
      )
    : NaN;
  return Number.isFinite(timestamp) ? timestamp : undefined;
}

/**
 * Backends predating persisted project setup omit every setup field. Treat
 * those rows as existing projects, while keeping explicit draft/ready values
 * authoritative when a newer backend supplies them.
 */
export function normalizeApiProjectSetup(
  serverProject: ApiProjectSetupState,
  localProject?: Pick<ProjectWorkspace, "setupCompletedAt" | "setupMode">,
): NormalizedProjectSetup {
  if (serverProject.setup_status === "draft") {
    return {
      setupCompletedAt: undefined,
      setupMode: undefined,
    };
  }

  if (serverProject.setup_status === "ready") {
    return {
      setupCompletedAt:
        parseTimestamp(serverProject.setup_completed_at) ??
        localProject?.setupCompletedAt ??
        parseTimestamp(serverProject.created_at) ??
        Date.now(),
      setupMode:
        serverProject.setup_mode ??
        localProject?.setupMode ??
        "existing",
    };
  }

  return {
    setupCompletedAt:
      localProject?.setupCompletedAt ??
      parseTimestamp(serverProject.created_at) ??
      Date.now(),
    setupMode: localProject?.setupMode ?? "existing",
  };
}
