import { useCallback, useReducer } from "react";
import type { ManagementSection } from "./ProjectManagementPage";
import type { ProjectDetailTab } from "./ProjectDetailPage";

export type MainView =
  | "chat"
  | "members"
  | "profile"
  | "project-detail"
  | "project-management"
  | "project-setup"
  | "projects"
  | "settings";

type WorkspaceRouteState = {
  mainView: MainView;
  membersReturnView: Extract<
    MainView,
    "project-detail" | "project-management"
  >;
  projectDetailTab: ProjectDetailTab;
  projectManagementSection: ManagementSection;
};

type WorkspaceRouteAction =
  | { type: "navigate"; view: MainView }
  | {
      type: "open-members";
      returnView: WorkspaceRouteState["membersReturnView"];
    }
  | { type: "open-project-detail"; tab?: ProjectDetailTab }
  | { type: "open-project-management"; section?: ManagementSection }
  | { type: "set-project-detail-tab"; tab: ProjectDetailTab }
  | { type: "set-project-management-section"; section: ManagementSection };

export const INITIAL_WORKSPACE_ROUTE: WorkspaceRouteState = {
  mainView: "projects",
  membersReturnView: "project-detail",
  projectDetailTab: "overview",
  projectManagementSection: "general",
};

export function reduceWorkspaceRoute(
  state: WorkspaceRouteState,
  action: WorkspaceRouteAction,
): WorkspaceRouteState {
  switch (action.type) {
    case "navigate":
      return state.mainView === action.view
        ? state
        : { ...state, mainView: action.view };
    case "open-members":
      return {
        ...state,
        mainView: "members",
        membersReturnView: action.returnView,
      };
    case "open-project-detail":
      return {
        ...state,
        mainView: "project-detail",
        projectDetailTab: action.tab ?? state.projectDetailTab,
      };
    case "open-project-management":
      return {
        ...state,
        mainView: "project-management",
        projectManagementSection:
          action.section ?? state.projectManagementSection,
      };
    case "set-project-detail-tab":
      return state.projectDetailTab === action.tab
        ? state
        : { ...state, projectDetailTab: action.tab };
    case "set-project-management-section":
      return state.projectManagementSection === action.section
        ? state
        : { ...state, projectManagementSection: action.section };
  }
}

export function useWorkspaceRoute(
  initialState: WorkspaceRouteState = INITIAL_WORKSPACE_ROUTE,
) {
  const [route, dispatch] = useReducer(reduceWorkspaceRoute, initialState);

  const navigateTo = useCallback((view: MainView) => {
    dispatch({ type: "navigate", view });
  }, []);
  const openMembers = useCallback(
    (returnView: WorkspaceRouteState["membersReturnView"]) => {
      dispatch({ type: "open-members", returnView });
    },
    [],
  );
  const openProjectDetail = useCallback((tab?: ProjectDetailTab) => {
    dispatch({ type: "open-project-detail", tab });
  }, []);
  const openProjectManagement = useCallback((section?: ManagementSection) => {
    dispatch({ type: "open-project-management", section });
  }, []);
  const setProjectDetailTab = useCallback((tab: ProjectDetailTab) => {
    dispatch({ type: "set-project-detail-tab", tab });
  }, []);
  const setProjectManagementSection = useCallback(
    (section: ManagementSection) => {
      dispatch({ type: "set-project-management-section", section });
    },
    [],
  );

  return {
    ...route,
    navigateTo,
    openMembers,
    openProjectDetail,
    openProjectManagement,
    setProjectDetailTab,
    setProjectManagementSection,
  };
}
