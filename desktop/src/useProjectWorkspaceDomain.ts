import {
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { canRole, type ProjectRole } from "./members";
import type {
  ChatSession,
  ProjectState,
  ProjectWorkspace,
} from "./types";

type ProjectWorkspaceDomainOptions = {
  hasAuthenticatedUser: boolean;
  initialState: ProjectState;
};

type ProjectWorkspaceSelection = {
  canDeleteSelectedProject: boolean;
  canMutateSelectedProject: boolean;
  isSelectedProjectOwner: boolean;
  selectedProject: ProjectWorkspace | null;
  selectedProjectRole: ProjectRole | null | undefined;
  selectedSession: ChatSession | null;
};

function deriveProjectWorkspaceSelection(
  projects: ProjectWorkspace[],
  selectedProjectId: string | null,
  selectedSessionId: string | null,
  hasAuthenticatedUser: boolean,
): ProjectWorkspaceSelection {
  const selectedProject =
    projects.find((project) => project.id === selectedProjectId) ?? null;
  const sessions = selectedProject?.sessions ?? [];
  const selectedSession =
    sessions.find((session) => session.id === selectedSessionId) ?? null;
  const selectedProjectRole = selectedProject?.currentUserRole;
  const usesLocalPermissions =
    Boolean(selectedProject) &&
    (!hasAuthenticatedUser ||
      typeof selectedProject?.apiProjectId !== "number");
  const isSelectedProjectOwner = selectedProject
    ? usesLocalPermissions || selectedProjectRole === "owner"
    : false;
  const canMutateSelectedProject = selectedProject
    ? usesLocalPermissions || canRole(selectedProjectRole, "member")
    : false;

  return {
    canDeleteSelectedProject: isSelectedProjectOwner,
    canMutateSelectedProject,
    isSelectedProjectOwner,
    selectedProject,
    selectedProjectRole,
    selectedSession,
  };
}

export function useProjectWorkspaceDomain({
  hasAuthenticatedUser,
  initialState,
}: ProjectWorkspaceDomainOptions) {
  const [projects, setProjects] = useState<ProjectWorkspace[]>(
    initialState.projects,
  );
  const [selectedProjectId, setSelectedProjectId] = useState(
    initialState.selectedProjectId,
  );
  const [selectedSessionId, setSelectedSessionId] = useState(
    initialState.selectedSessionId,
  );
  const projectsRef = useRef(initialState.projects);
  const selectedProjectIdRef = useRef(initialState.selectedProjectId);
  const selectedSessionIdRef = useRef(initialState.selectedSessionId);

  useLayoutEffect(() => {
    projectsRef.current = projects;
  }, [projects]);

  useLayoutEffect(() => {
    selectedProjectIdRef.current = selectedProjectId;
  }, [selectedProjectId]);

  useLayoutEffect(() => {
    selectedSessionIdRef.current = selectedSessionId;
  }, [selectedSessionId]);

  const selection = useMemo(
    () =>
      deriveProjectWorkspaceSelection(
        projects,
        selectedProjectId,
        selectedSessionId,
        hasAuthenticatedUser,
      ),
    [
      hasAuthenticatedUser,
      projects,
      selectedProjectId,
      selectedSessionId,
    ],
  );

  return {
    ...selection,
    projects,
    projectsRef,
    selectedProjectId,
    selectedProjectIdRef,
    selectedSessionId,
    selectedSessionIdRef,
    setProjects,
    setSelectedProjectId,
    setSelectedSessionId,
  };
}
