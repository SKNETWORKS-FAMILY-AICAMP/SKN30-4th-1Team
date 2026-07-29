import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  GitBranch,
  Settings2,
  Trash2,
  Users,
} from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import {
  type FormEvent,
  type MouseEvent,
  useEffect,
  useRef,
  useState,
} from "react";
import type { LanguageSetting } from "./settings";
import type { ProjectWorkspace } from "./types";

export type ManagementSection = "danger" | "general" | "github" | "members";

export type ProjectManagementPageProps = {
  activeSection: ManagementSection;
  isProjectDeleteConfirming?: boolean;
  language: LanguageSetting;
  onBack: () => void;
  onDeleteProject?: (event: MouseEvent<HTMLButtonElement>) => void | Promise<void>;
  onManageMembers: (trigger?: HTMLElement) => void;
  onOpenProjectGithub?: () => void;
  onRenameProject?: (name: string) => void | Promise<void>;
  onSectionChange: (section: ManagementSection) => void;
  onUpdateProjectDescription?: (description: string) => void | Promise<void>;
  project: ProjectWorkspace;
};

const SECTION_COPY: Record<
  ManagementSection,
  { en: string; ko: string }
> = {
  danger: { en: "Danger zone", ko: "위험 구역" },
  general: { en: "General", ko: "일반" },
  github: { en: "GitHub", ko: "GitHub" },
  members: { en: "Members & permissions", ko: "멤버 및 권한" },
};

export function ProjectManagementPage({
  activeSection,
  isProjectDeleteConfirming = false,
  language,
  onBack,
  onDeleteProject,
  onManageMembers,
  onOpenProjectGithub,
  onRenameProject,
  onSectionChange,
  onUpdateProjectDescription,
  project,
}: ProjectManagementPageProps) {
  const [descriptionDraft, setDescriptionDraft] = useState(
    project.description ?? "",
  );
  const [isSavingDescription, setIsSavingDescription] = useState(false);
  const [isSavingName, setIsSavingName] = useState(false);
  const [nameDraft, setNameDraft] = useState(project.name);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const isKorean = language === "ko";

  useEffect(() => {
    setDescriptionDraft(project.description ?? "");
    setNameDraft(project.name);
    const frame = window.requestAnimationFrame(() => {
      headingRef.current?.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [project.id]);

  useEffect(() => {
    setNameDraft(project.name);
  }, [project.name]);

  useEffect(() => {
    setDescriptionDraft(project.description ?? "");
  }, [project.description]);

  async function submitName(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextName = nameDraft.trim();
    if (!onRenameProject || !nextName || nextName === project.name || isSavingName) {
      return;
    }

    setIsSavingName(true);
    try {
      await onRenameProject(nextName);
    } finally {
      setIsSavingName(false);
    }
  }

  async function submitDescription(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!onUpdateProjectDescription || isSavingDescription) {
      return;
    }

    setIsSavingDescription(true);
    try {
      await onUpdateProjectDescription(descriptionDraft);
    } finally {
      setIsSavingDescription(false);
    }
  }

  const setupModeLabel =
    project.setupMode === "analyzed"
      ? isKorean
        ? "자료 분석"
        : "Analyzed sources"
      : project.setupMode === "chat_only"
        ? isKorean
          ? "분석 없이 시작"
          : "Chat only"
        : isKorean
          ? "기존 프로젝트"
          : "Existing project";

  return (
    <section
      aria-labelledby="project-management-title"
      className="project-management-page"
      data-testid="project-management-page"
    >
      <div className="project-management-frame">
        <header className="project-management-header">
          <Button
            className="settings-back-button"
            icon={<ArrowLeft size={15} />}
            isIconOnly
            label={isKorean ? "프로젝트 상세로 돌아가기" : "Back to project detail"}
            onClick={onBack}
            tooltip={isKorean ? "돌아가기" : "Back"}
            variant="ghost"
          />
          <div>
            <p>{project.name}</p>
            <h1 id="project-management-title" ref={headingRef} tabIndex={-1}>
              {isKorean ? "프로젝트 관리" : "Project management"}
            </h1>
            <span>
              {isKorean
                ? "프로젝트 설정과 연동을 Owner 권한으로 관리합니다."
                : "Manage project settings and integrations as the Owner."}
            </span>
          </div>
        </header>

        <nav
          aria-label={isKorean ? "프로젝트 관리 메뉴" : "Project management menu"}
          className="project-management-tabs"
          role="tablist"
        >
          {(
            [
              ["general", Settings2],
              ["github", GitBranch],
              ["members", Users],
              ["danger", AlertTriangle],
            ] as const
          ).map(([section, Icon]) => (
            <button
              aria-controls={`project-management-panel-${section}`}
              aria-selected={activeSection === section}
              className="project-management-tab"
              data-section={section}
              id={`project-management-tab-${section}`}
              key={section}
              onClick={() => onSectionChange(section)}
              role="tab"
              type="button"
            >
              <Icon aria-hidden="true" size={15} />
              {SECTION_COPY[section][language]}
            </button>
          ))}
        </nav>

        <div
          aria-labelledby={`project-management-tab-${activeSection}`}
          className="project-management-panel"
          id={`project-management-panel-${activeSection}`}
          role="tabpanel"
        >
          {activeSection === "general" ? (
            <div className="project-management-general">
              <header className="project-management-section-heading">
                <h2>{isKorean ? "일반 설정" : "General settings"}</h2>
                <p>
                  {isKorean
                    ? "프로젝트 이름과 설명, 현재 운영 상태를 관리합니다."
                    : "Manage the project name, description, and current state."}
                </p>
              </header>

              <form className="project-management-form" onSubmit={submitName}>
                <label htmlFor="project-management-name">
                  <span>{isKorean ? "프로젝트 이름" : "Project name"}</span>
                  <small>
                    {isKorean
                      ? "팀원과 채팅 목록에 표시되는 이름입니다."
                      : "Shown to members and in chat lists."}
                  </small>
                </label>
                <div className="project-management-field-action">
                  <input
                    id="project-management-name"
                    maxLength={120}
                    onChange={(event) => setNameDraft(event.currentTarget.value)}
                    value={nameDraft}
                  />
                  <Button
                    isDisabled={
                      !onRenameProject ||
                      isSavingName ||
                      !nameDraft.trim() ||
                      nameDraft.trim() === project.name
                    }
                    label={
                      isSavingName
                        ? isKorean
                          ? "저장 중"
                          : "Saving"
                        : isKorean
                          ? "이름 변경"
                          : "Rename"
                    }
                    type="submit"
                    variant="secondary"
                  />
                </div>
              </form>

              <form
                className="project-management-form"
                onSubmit={submitDescription}
              >
                <label htmlFor="project-management-description">
                  <span>{isKorean ? "프로젝트 설명" : "Project description"}</span>
                  <small>
                    {isKorean
                      ? "프로젝트의 목표와 배경을 팀과 공유합니다."
                      : "Share the project goal and context with the team."}
                  </small>
                </label>
                <textarea
                  id="project-management-description"
                  maxLength={4000}
                  onChange={(event) =>
                    setDescriptionDraft(event.currentTarget.value)
                  }
                  rows={5}
                  value={descriptionDraft}
                />
                <div className="project-management-form-footer">
                  <small>{descriptionDraft.length} / 4000</small>
                  <Button
                    isDisabled={
                      !onUpdateProjectDescription ||
                      isSavingDescription ||
                      descriptionDraft.trim() ===
                        (project.description ?? "").trim()
                    }
                    label={
                      isSavingDescription
                        ? isKorean
                          ? "저장 중"
                          : "Saving"
                        : isKorean
                          ? "설명 저장"
                          : "Save description"
                    }
                    type="submit"
                    variant="secondary"
                  />
                </div>
              </form>

              <div className="project-management-status-row">
                <div>
                  <span>{isKorean ? "프로젝트 상태" : "Project status"}</span>
                  <small>
                    {isKorean
                      ? `설정 방식 · ${setupModeLabel}`
                      : `Setup mode · ${setupModeLabel}`}
                  </small>
                </div>
                <strong>
                  <CheckCircle2 aria-hidden="true" size={14} />
                  {isKorean ? "설정 완료" : "Setup complete"}
                </strong>
              </div>
            </div>
          ) : null}

          {activeSection === "github" ? (
            <div className="project-management-focused-section">
              <span className="project-management-section-icon">
                <GitBranch aria-hidden="true" size={20} />
              </span>
              <div>
                <h2>GitHub</h2>
                <p>
                  {project.githubConnected
                    ? isKorean
                      ? `${project.githubRepository?.name ?? "저장소"}가 연결되어 있습니다. 동기화 상태와 저장소 변경은 GitHub 관리 화면에서 처리합니다.`
                      : `${project.githubRepository?.name ?? "A repository"} is connected. Manage sync and repository selection in GitHub settings.`
                    : isKorean
                      ? "저장소를 연결하면 변경 사항과 프로젝트 맥락을 함께 활용할 수 있습니다."
                      : "Connect a repository to use its changes as project context."}
                </p>
              </div>
              <Button
                icon={<GitBranch size={14} />}
                isDisabled={!onOpenProjectGithub}
                label={
                  project.githubConnected
                    ? isKorean
                      ? "GitHub 관리"
                      : "Manage GitHub"
                    : isKorean
                      ? "GitHub 연결"
                      : "Connect GitHub"
                }
                onClick={onOpenProjectGithub}
                variant="secondary"
              />
            </div>
          ) : null}

          {activeSection === "members" ? (
            <div className="project-management-focused-section">
              <span className="project-management-section-icon">
                <Users aria-hidden="true" size={20} />
              </span>
              <div>
                <h2>{isKorean ? "멤버 및 권한" : "Members & permissions"}</h2>
                <p>
                  {isKorean
                    ? "프로젝트 참여자를 초대하고 역할을 변경합니다. Owner만 멤버 권한을 관리할 수 있습니다."
                    : "Invite project participants and change roles. Only the Owner can manage permissions."}
                </p>
              </div>
              <Button
                icon={<Users size={14} />}
                label={isKorean ? "팀원 관리 열기" : "Open member management"}
                onClick={(event) => onManageMembers(event.currentTarget)}
                variant="secondary"
              />
            </div>
          ) : null}

          {activeSection === "danger" ? (
            <div className="project-management-danger">
              <span className="project-management-section-icon">
                <Trash2 aria-hidden="true" size={20} />
              </span>
              <div>
                <h2>{isKorean ? "프로젝트 삭제" : "Delete project"}</h2>
                <p>
                  {isKorean
                    ? "프로젝트 자료, 메모리, 채팅 기록이 함께 삭제됩니다. 이 작업은 되돌릴 수 없습니다."
                    : "Project sources, memory, and chat history will be deleted. This cannot be undone."}
                </p>
              </div>
              <Button
                isDisabled={!onDeleteProject}
                label={
                  isProjectDeleteConfirming
                    ? isKorean
                      ? "한 번 더 눌러 삭제"
                      : "Press again to delete"
                    : isKorean
                      ? "프로젝트 삭제"
                      : "Delete project"
                }
                onClick={(event) => void onDeleteProject?.(event)}
                variant="destructive"
              />
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
