import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  FileText,
  FolderKanban,
  GitBranch,
  MessageSquare,
  Plus,
  RefreshCw,
  Users,
} from "lucide-react";
import { Button } from "@astryxdesign/core/Button";
import { Spinner } from "@astryxdesign/core/Spinner";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useEffect, useMemo, useState } from "react";
import { formatRelativeAge, parsePaimTimestamp } from "./format";
import { getErrorMessage } from "./paimApi";
import { ProfileAvatar } from "./ProfileAvatar";
import {
  fetchProjectOverviews,
  type ProjectHealth,
  type ProjectOverview,
  type ProjectOverviewMember,
} from "./projectOverview";
import type { LanguageSetting } from "./settings";
import type { ProjectWorkspace } from "./types";

type ProjectPortfolioPageProps = {
  language: LanguageSetting;
  localProjects: ProjectWorkspace[];
  onCreateProject: () => void;
  onOpenProject: (projectId: string) => void;
};

const HEALTH_COPY: Record<ProjectHealth, { ko: string; en: string }> = {
  active: { ko: "운영 중", en: "Active" },
  attention: { ko: "확인 필요", en: "Needs attention" },
  completed: { ko: "완료", en: "Completed" },
  setup: { ko: "설정 중", en: "Setup" },
  syncing: { ko: "동기화 중", en: "Syncing" },
};

function initials(member: ProjectOverviewMember) {
  const label = member.name?.trim() || member.email.split("@")[0] || "?";
  return label.slice(0, 2).toUpperCase();
}

function ProjectMemberAvatar({ member }: { member: ProjectOverviewMember }) {
  return (
    <ProfileAvatar
      ariaLabel={member.name || member.email}
      className="portfolio-avatar"
      fallback={initials(member)}
      imageUrl={member.profile_image_url}
      label={member.name || member.email}
    />
  );
}

function activityTime(value?: string | null) {
  if (!value || value.startsWith("1970-01-01")) {
    return null;
  }
  const parsed = parsePaimTimestamp(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function ProjectPortfolioPage({
  language,
  localProjects,
  onCreateProject,
  onOpenProject,
}: ProjectPortfolioPageProps) {
  const [overviews, setOverviews] = useState<ProjectOverview[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState("");

  async function loadOverview() {
    setIsLoading(true);
    setError("");
    try {
      setOverviews(await fetchProjectOverviews(localProjects));
    } catch (loadError) {
      setError(
        getErrorMessage(
          loadError,
          language === "ko"
            ? "프로젝트 현황을 불러오지 못했습니다"
            : "Could not load project overview",
        ),
      );
    } finally {
      setIsLoading(false);
    }
  }

  useEffect(() => {
    void loadOverview();
  }, [language, localProjects]);

  const cards = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return overviews
      .map((overview) => ({
        localProject:
          localProjects.find((project) => project.id === overview.local_project_id) ??
          localProjects.find((project) => project.apiProjectId === overview.id),
        overview,
      }))
      .filter(({ overview }) => overview.name.toLocaleLowerCase().includes(normalizedQuery));
  }, [localProjects, overviews, query]);

  const activeCount = overviews.filter(({ health }) =>
    ["active", "attention", "syncing"].includes(health),
  ).length;
  const attentionCount = overviews.filter(({ health }) => health === "attention").length;

  return (
    <section className="portfolio-page" aria-labelledby="portfolio-title">
      <header className="portfolio-header">
        <div>
          <p className="portfolio-eyebrow">
            <FolderKanban aria-hidden="true" size={14} />
            {language === "ko" ? "팀 워크스페이스" : "Team workspace"}
          </p>
          <h1 id="portfolio-title">{language === "ko" ? "프로젝트" : "Projects"}</h1>
          <p>
            {language === "ko"
              ? `${overviews.length}개 프로젝트 · 운영 중 ${activeCount}개${
                  attentionCount ? ` · 확인 필요 ${attentionCount}개` : ""
                }`
              : `${overviews.length} projects · ${activeCount} active${
                  attentionCount ? ` · ${attentionCount} need attention` : ""
                }`}
          </p>
        </div>
        <div className="portfolio-header-actions">
          <TextInput
            className="portfolio-search"
            isLabelHidden
            label={language === "ko" ? "프로젝트 검색" : "Search projects"}
            onChange={setQuery}
            placeholder={language === "ko" ? "프로젝트 이름 검색" : "Search project names"}
            size="sm"
            value={query}
            width="100%"
          />
          <Button
            className="portfolio-create"
            icon={<Plus size={15} />}
            label={language === "ko" ? "새 프로젝트 만들기" : "Create project"}
            onClick={onCreateProject}
            size="sm"
            tooltip={
              language === "ko"
                ? "새 프로젝트를 만들고 자료 추가 화면을 엽니다"
                : "Create a project and open the source setup screen"
            }
            variant="secondary"
          />
        </div>
      </header>

      {isLoading ? (
        <div className="portfolio-state" role="status">
          <Spinner size="md" />
          <p>{language === "ko" ? "프로젝트 현황을 계산하는 중" : "Calculating project health"}</p>
        </div>
      ) : error ? (
        <div className="portfolio-state" role="alert">
          <AlertTriangle aria-hidden="true" size={22} />
          <p>{error}</p>
          <Button
            icon={<RefreshCw size={14} />}
            label={language === "ko" ? "다시 시도" : "Retry"}
            onClick={() => void loadOverview()}
            size="sm"
            variant="secondary"
          />
        </div>
      ) : cards.length ? (
        <div className="portfolio-grid" role="list">
          {cards.map(({ localProject, overview }) => {
            const recentActivityAt = activityTime(overview.recent_activity_at);
            const completedActions = Math.max(0, overview.action_count - overview.open_actions);
            const sourceReady =
              overview.indexed_documents + overview.indexed_repositories;
            const sourceTotal = overview.document_count + overview.repository_count;

            return (
              <article
                className="portfolio-card"
                data-health={overview.health}
                key={`${overview.local_project_id ?? "server"}:${overview.id}`}
                role="listitem"
              >
                <button
                  aria-label={
                    language === "ko"
                      ? `${overview.name} 상세 보기`
                      : `View ${overview.name} details`
                  }
                  className="portfolio-card-hit-area"
                  disabled={!localProject}
                  onClick={() => localProject && onOpenProject(localProject.id)}
                  type="button"
                />
                <div className="portfolio-card-heading">
                  <div>
                    <span className="portfolio-status" data-health={overview.health}>
                      {overview.health === "completed" ? (
                        <CheckCircle2 aria-hidden="true" size={13} />
                      ) : overview.health === "syncing" ? (
                        <RefreshCw aria-hidden="true" size={13} />
                      ) : overview.health === "attention" ? (
                        <AlertTriangle aria-hidden="true" size={13} />
                      ) : (
                        <span aria-hidden="true" className="portfolio-status-dot" />
                      )}
                      {HEALTH_COPY[overview.health][language]}
                    </span>
                    <h2>{overview.name}</h2>
                  </div>
                  <span className="portfolio-activity">
                    <Clock3 aria-hidden="true" size={13} />
                    {recentActivityAt
                      ? formatRelativeAge(recentActivityAt, language)
                      : language === "ko"
                        ? "활동 없음"
                        : "No activity"}
                  </span>
                </div>

                <div className="portfolio-metric-primary">
                  <div>
                    <span>
                      {overview.progress_basis === "actions"
                        ? language === "ko"
                          ? "액션 완료"
                          : "Actions complete"
                        : language === "ko"
                          ? "자료 준비"
                          : "Sources ready"}
                    </span>
                    <strong>
                      {overview.progress_basis === "actions"
                        ? `${completedActions} / ${overview.action_count}`
                        : `${sourceReady} / ${sourceTotal}`}
                    </strong>
                  </div>
                  <span>{overview.progress_percent ?? 0}%</span>
                </div>
                <div
                  aria-label={`${overview.progress_percent ?? 0}%`}
                  className="portfolio-progress"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={overview.progress_percent ?? 0}
                >
                  <span style={{ width: `${overview.progress_percent ?? 0}%` }} />
                </div>

                <div className="portfolio-signals" aria-label={language === "ko" ? "운영 신호" : "Signals"}>
                  <span data-alert={overview.open_actions ? "true" : undefined}>
                    <CheckCircle2 aria-hidden="true" size={14} />
                    {language === "ko" ? `열린 액션 ${overview.open_actions}` : `${overview.open_actions} open`}
                  </span>
                  <span data-alert={overview.issue_count + overview.risk_count ? "true" : undefined}>
                    <AlertTriangle aria-hidden="true" size={14} />
                    {language === "ko"
                      ? `이슈·리스크 ${overview.issue_count + overview.risk_count}`
                      : `${overview.issue_count + overview.risk_count} issues`}
                  </span>
                  <span>
                    <FileText aria-hidden="true" size={14} />
                    {language === "ko" ? `자료 ${sourceTotal}` : `${sourceTotal} sources`}
                  </span>
                  <span>
                    <MessageSquare aria-hidden="true" size={14} />
                    {language === "ko" ? `메모리 ${overview.memory_count}` : `${overview.memory_count} memories`}
                  </span>
                </div>

                <footer className="portfolio-card-footer">
                  <div className="portfolio-members" aria-label={language === "ko" ? "팀원" : "Members"}>
                    <Users aria-hidden="true" size={14} />
                    <div className="portfolio-avatar-stack">
                      {overview.members.slice(0, 4).map((member) => (
                        <ProjectMemberAvatar key={member.id} member={member} />
                      ))}
                    </div>
                    <span>{overview.member_count}</span>
                  </div>
                  <span className="portfolio-open">
                    {language === "ko" ? "상세 보기" : "View details"}
                    <ArrowRight aria-hidden="true" size={15} />
                  </span>
                </footer>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="portfolio-state">
          <FolderKanban aria-hidden="true" size={24} />
          <p>
            {query
              ? language === "ko"
                ? "검색 결과가 없습니다"
                : "No matching projects"
              : language === "ko"
                ? "아직 프로젝트가 없습니다"
                : "No projects yet"}
          </p>
          {!query ? (
            <Button
              icon={<Plus size={14} />}
              label={language === "ko" ? "첫 프로젝트 만들기" : "Create first project"}
              onClick={onCreateProject}
              variant="primary"
            />
          ) : null}
        </div>
      )}

      <p className="portfolio-data-note">
        <GitBranch aria-hidden="true" size={13} />
        {language === "ko"
          ? "진행률은 액션 완료율을 우선 사용하며, 액션이 없으면 자료 인덱싱 비율을 표시합니다."
          : "Progress uses action completion first, then source indexing when no actions exist."}
      </p>
    </section>
  );
}
