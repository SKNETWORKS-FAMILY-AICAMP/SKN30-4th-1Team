import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Spinner } from "@astryxdesign/core/Spinner";
import { TextInput } from "@astryxdesign/core/TextInput";
import { LogOut, RefreshCw, Shield, Trash2, UserPlus, Users } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import type { PaimUser } from "./auth";
import { useI18n } from "./i18n";
import { ProfileAvatar } from "./ProfileAvatar";
import {
  ASSIGNABLE_PROJECT_ROLES,
  addProjectMember,
  canAddProjectMember,
  canChangeProjectMemberRole,
  canRemoveProjectMember,
  fetchProjectMembers,
  getCurrentProjectMember,
  removeProjectMember,
  updateProjectMemberRole,
  type AssignableProjectRole,
  type ProjectMember,
  type ProjectRole,
} from "./members";
import { getErrorMessage } from "./paimApi";

type MembersLoadState = "loading" | "loaded" | "error";
type MemberOperation = "add" | `role:${number}` | `remove:${number}` | null;
type FocusRequest =
  | { kind: "heading" }
  | { kind: "member"; memberId: number | null };
type VisibleMemberStatus = { id: number; message: string };

const PROJECT_ROLE_LABEL_KEYS: Record<ProjectRole, string> = {
  viewer: "조회자",
  member: "멤버",
  admin: "관리자",
  owner: "소유자",
};

const PROJECT_ROLE_DESCRIPTION_KEYS: Record<ProjectRole, string> = {
  viewer: "프로젝트와 멤버를 볼 수 있습니다. 내용 추가·수정은 할 수 없습니다.",
  member: "자료, 메모리와 대화를 추가·수정할 수 있습니다. 멤버 관리는 할 수 없습니다.",
  admin: "현재는 멤버와 같은 편집 권한입니다. 멤버 관리와 프로젝트 삭제는 할 수 없습니다.",
  owner: "프로젝트 편집, 멤버 관리, 역할 변경과 프로젝트 삭제를 할 수 있습니다.",
};

export type ProjectMembersPanelProps = {
  currentUser: PaimUser;
  projectId: number;
  reloadRevision?: number;
  onLeaveProject?: () => void;
  onMembersChange?: (members: ProjectMember[], currentRole: ProjectRole | null) => void;
};

function getMemberInitials(member: ProjectMember) {
  const words = member.name.trim().split(/\s+/).filter(Boolean);
  const initials = words.slice(0, 2).map((word) => Array.from(word)[0]).join("");
  return (initials || member.email.slice(0, 1) || "?").toUpperCase();
}

function getMemberRemoveButtonId(memberId: number) {
  return `project-member-remove-${memberId}`;
}

function getMemberRemovalConfirmationId(memberId: number) {
  return `project-member-removal-confirmation-${memberId}`;
}

export function ProjectMembersPanel({
  currentUser,
  projectId,
  reloadRevision = 0,
  onLeaveProject,
  onMembersChange,
}: ProjectMembersPanelProps) {
  const { t } = useI18n();
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [loadedProjectId, setLoadedProjectId] = useState<number | null>(null);
  const [loadState, setLoadState] = useState<MembersLoadState>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [email, setEmail] = useState("");
  const [addRole, setAddRole] = useState<AssignableProjectRole>("member");
  const [roleDrafts, setRoleDrafts] = useState<Record<number, AssignableProjectRole>>({});
  const [operation, setOperation] = useState<MemberOperation>(null);
  const [pendingRemovalId, setPendingRemovalId] = useState<number | null>(null);
  const [isRetrying, setIsRetrying] = useState(false);
  const [emailError, setEmailError] = useState("");
  const [statusMessage, setStatusMessage] = useState("");
  const [visibleStatus, setVisibleStatus] = useState<VisibleMemberStatus | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const panelHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const addEmailInputRef = useRef<HTMLInputElement | null>(null);
  const focusRequestRef = useRef<FocusRequest | null>(null);
  const visibleStatusIdRef = useRef(0);
  const projectIdRef = useRef(projectId);
  projectIdRef.current = projectId;

  const visibleMembers = loadedProjectId === projectId ? members : [];
  const currentMember = getCurrentProjectMember(visibleMembers, currentUser);
  const currentRole = currentMember?.role ?? null;
  const canAddMembers = canAddProjectMember(currentRole);
  const isBusy = operation !== null;

  useEffect(() => {
    if (!visibleStatus) {
      return;
    }

    const timeoutId = window.setTimeout(() => setVisibleStatus(null), 4000);
    return () => window.clearTimeout(timeoutId);
  }, [visibleStatus]);

  useEffect(() => {
    const focusRequest = focusRequestRef.current;
    if (!focusRequest || loadedProjectId !== projectId) {
      return;
    }

    const frameId = window.requestAnimationFrame(() => {
      if (focusRequestRef.current !== focusRequest) {
        return;
      }

      const activeElement = document.activeElement;
      const focusWasLost =
        activeElement === null ||
        activeElement === document.body ||
        activeElement === document.documentElement;

      if (!focusWasLost) {
        focusRequestRef.current = null;
        return;
      }

      let focusTarget: HTMLElement | null = null;
      if (focusRequest.kind === "member" && focusRequest.memberId !== null) {
        focusTarget = panelRef.current?.querySelector<HTMLElement>(
          `[data-member-id="${focusRequest.memberId}"] select:not(:disabled), ` +
            `[data-member-id="${focusRequest.memberId}"] button:not(:disabled):not([aria-disabled="true"])`,
        ) ?? null;
      }

      focusTarget ??= panelRef.current?.querySelector<HTMLElement>(
        ".project-members-list select:not(:disabled), " +
          '.project-members-list button:not(:disabled):not([aria-disabled="true"])',
      ) ?? null;
      (focusTarget ?? panelHeadingRef.current)?.focus({ preventScroll: true });
      focusRequestRef.current = null;
    });

    return () => window.cancelAnimationFrame(frameId);
  }, [loadedProjectId, members, projectId]);

  function applyMembers(nextMembers: ProjectMember[], targetProjectId = projectId) {
    if (projectIdRef.current !== targetProjectId) {
      return;
    }

    const nextRoleDrafts = Object.fromEntries(
      nextMembers
        .filter((member) => member.role !== "owner")
        .map((member) => [member.user_id, member.role as AssignableProjectRole]),
    );
    const nextCurrentRole = getCurrentProjectMember(nextMembers, currentUser)?.role ?? null;

    setMembers(nextMembers);
    setLoadedProjectId(targetProjectId);
    setRoleDrafts(nextRoleDrafts);
    setLoadState("loaded");
    setPendingRemovalId(null);
    onMembersChange?.(nextMembers, nextCurrentRole);
  }

  function showSuccessStatus(message: string) {
    visibleStatusIdRef.current += 1;
    setStatusMessage(message);
    setVisibleStatus({ id: visibleStatusIdRef.current, message });
  }

  async function refreshMembers(targetProjectId = projectId) {
    const nextMembers = await fetchProjectMembers(targetProjectId);
    applyMembers(nextMembers, targetProjectId);
    return nextMembers;
  }

  useEffect(() => {
    let isDisposed = false;
    const targetProjectId = projectId;

    setMembers([]);
    setLoadedProjectId(null);
    setLoadState("loading");
    setErrorMessage("");
    setEmail("");
    setAddRole("member");
    setRoleDrafts({});
    setOperation(null);
    setPendingRemovalId(null);
    setIsRetrying(false);
    setEmailError("");
    setStatusMessage("");
    setVisibleStatus(null);
    focusRequestRef.current = null;

    void fetchProjectMembers(targetProjectId)
      .then((nextMembers) => {
        if (!isDisposed) {
          applyMembers(nextMembers, targetProjectId);
          if (nextMembers.length > 0) {
            setStatusMessage(t("{count}명의 멤버를 불러왔습니다.", { count: nextMembers.length }));
          }
        }
      })
      .catch((error) => {
        if (!isDisposed) {
          setLoadState("error");
          setStatusMessage("");
          setErrorMessage(getErrorMessage(error, t("프로젝트 멤버를 불러올 수 없습니다.")));
        }
      });

    return () => {
      isDisposed = true;
    };
  }, [currentUser.id, projectId, reloadRevision]);

  async function handleRetry() {
    if (isRetrying) {
      return;
    }

    const targetProjectId = projectId;
    focusRequestRef.current = { kind: "heading" };
    setIsRetrying(true);
    setErrorMessage("");
    setStatusMessage(t("멤버 목록을 다시 불러오는 중입니다."));
    setVisibleStatus(null);

    try {
      const nextMembers = await refreshMembers(targetProjectId);
      if (projectIdRef.current === targetProjectId && nextMembers.length > 0) {
        setStatusMessage(t("{count}명의 멤버를 불러왔습니다.", { count: nextMembers.length }));
      }
    } catch (error) {
      if (projectIdRef.current === targetProjectId) {
        focusRequestRef.current = null;
        setLoadState("error");
        setStatusMessage("");
        setErrorMessage(getErrorMessage(error, t("프로젝트 멤버를 불러올 수 없습니다.")));
      }
    } finally {
      if (projectIdRef.current === targetProjectId) {
        setIsRetrying(false);
      }
    }
  }

  async function handleAddMember(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const normalizedEmail = email.trim().toLowerCase();
    if (!canAddMembers || isBusy) {
      return;
    }
    if (!normalizedEmail || addEmailInputRef.current?.validity.valid === false) {
      const nextEmailError = t("유효한 이메일 주소를 입력해 주세요.");
      setEmailError(nextEmailError);
      setStatusMessage("");
      window.requestAnimationFrame(() => addEmailInputRef.current?.focus());
      return;
    }

    const targetProjectId = projectId;
    setOperation("add");
    setPendingRemovalId(null);
    setEmailError("");
    setErrorMessage("");
    setStatusMessage(t("멤버 추가 중: {name}", { name: normalizedEmail }));
    setVisibleStatus(null);

    try {
      const addedMember = await addProjectMember(targetProjectId, normalizedEmail, addRole);
      if (projectIdRef.current === targetProjectId) {
        setEmail("");
        setAddRole("member");
      }
      await refreshMembers(targetProjectId);
      if (projectIdRef.current === targetProjectId) {
        showSuccessStatus(
          t("멤버를 추가했습니다: {name} · {role}", {
            name: addedMember.name || normalizedEmail,
            role: t(PROJECT_ROLE_LABEL_KEYS[addedMember.role]),
          }),
        );
      }
    } catch (error) {
      if (projectIdRef.current === targetProjectId) {
        setStatusMessage("");
        setVisibleStatus(null);
        setErrorMessage(getErrorMessage(error, t("멤버를 추가할 수 없습니다.")));
      }
    } finally {
      if (projectIdRef.current === targetProjectId) {
        setOperation(null);
      }
    }
  }

  async function handleRoleChange(member: ProjectMember) {
    const nextRole = roleDrafts[member.user_id];
    if (
      !nextRole ||
      nextRole === member.role ||
      !canChangeProjectMemberRole(currentRole, currentUser, member) ||
      isBusy
    ) {
      return;
    }

    const targetProjectId = projectId;
    const operationKey = `role:${member.user_id}` as const;
    setOperation(operationKey);
    setPendingRemovalId(null);
    setErrorMessage("");
    setStatusMessage(t("역할 변경 중: {name}", { name: member.name }));
    setVisibleStatus(null);

    try {
      await updateProjectMemberRole(targetProjectId, member.user_id, nextRole);
      await refreshMembers(targetProjectId);
      if (projectIdRef.current === targetProjectId) {
        showSuccessStatus(
          t("역할을 변경했습니다: {name} · {role}", {
            name: member.name,
            role: t(PROJECT_ROLE_LABEL_KEYS[nextRole]),
          }),
        );
      }
    } catch (error) {
      if (projectIdRef.current === targetProjectId) {
        setStatusMessage("");
        setVisibleStatus(null);
        setErrorMessage(getErrorMessage(error, t("멤버 역할을 변경할 수 없습니다.")));
      }
    } finally {
      if (projectIdRef.current === targetProjectId) {
        setOperation(null);
      }
    }
  }

  function handleRequestRemoveMember(member: ProjectMember) {
    if (!canRemoveProjectMember(currentRole, currentUser, member) || isBusy) {
      return;
    }

    const confirmationId = getMemberRemovalConfirmationId(member.user_id);
    setPendingRemovalId(member.user_id);
    setErrorMessage("");
    setVisibleStatus(null);
    setStatusMessage("");
    window.requestAnimationFrame(() => {
      document
        .getElementById(confirmationId)
        ?.querySelector<HTMLElement>('button:not(:disabled):not([aria-disabled="true"])')
        ?.focus({ preventScroll: true });
    });
  }

  function handleCancelRemoveMember(member: ProjectMember) {
    const operationKey = `remove:${member.user_id}` as const;
    if (operation === operationKey) {
      return;
    }

    const isSelf = member.user_id === currentUser.id;
    setPendingRemovalId(null);
    setErrorMessage("");
    setVisibleStatus(null);
    setStatusMessage(
      t(
        isSelf
          ? "프로젝트 탈퇴 확인을 취소했습니다."
          : "멤버 제외 확인을 취소했습니다.",
      ),
    );
    window.requestAnimationFrame(() => {
      document.getElementById(getMemberRemoveButtonId(member.user_id))?.focus({
        preventScroll: true,
      });
    });
  }

  async function handleConfirmRemoveMember(member: ProjectMember) {
    if (
      pendingRemovalId !== member.user_id ||
      !canRemoveProjectMember(currentRole, currentUser, member) ||
      isBusy
    ) {
      return;
    }

    const targetProjectId = projectId;
    const isSelf = member.user_id === currentUser.id;
    const operationKey = `remove:${member.user_id}` as const;
    const memberIndex = visibleMembers.findIndex(
      (candidate) => candidate.user_id === member.user_id,
    );
    const nextFocusMemberId =
      visibleMembers[memberIndex + 1]?.user_id ?? visibleMembers[memberIndex - 1]?.user_id ?? null;
    focusRequestRef.current = isSelf
      ? { kind: "heading" }
      : { kind: "member", memberId: nextFocusMemberId };
    setOperation(operationKey);
    setErrorMessage("");
    setVisibleStatus(null);
    setStatusMessage(
      t(isSelf ? "프로젝트에서 탈퇴하는 중입니다." : "멤버 제외 중: {name}", {
        name: member.name,
      }),
    );

    try {
      await removeProjectMember(targetProjectId, member.user_id);

      if (projectIdRef.current !== targetProjectId) {
        return;
      }

      if (isSelf) {
        applyMembers(
          visibleMembers.filter((candidate) => candidate.user_id !== member.user_id),
          targetProjectId,
        );
        showSuccessStatus(t("프로젝트에서 탈퇴했습니다."));
        window.requestAnimationFrame(() => {
          if (projectIdRef.current === targetProjectId) {
            onLeaveProject?.();
          }
        });
      } else {
        await refreshMembers(targetProjectId);
        if (projectIdRef.current === targetProjectId) {
          showSuccessStatus(t("멤버를 제외했습니다: {name}", { name: member.name }));
        }
      }
    } catch (error) {
      if (projectIdRef.current === targetProjectId) {
        focusRequestRef.current = null;
        setStatusMessage("");
        setVisibleStatus(null);
        setErrorMessage(
          getErrorMessage(
            error,
            t(isSelf ? "프로젝트에서 탈퇴할 수 없습니다." : "멤버를 제외할 수 없습니다."),
          ),
        );
      }
    } finally {
      if (projectIdRef.current === targetProjectId) {
        setOperation(null);
      }
    }
  }

  function getProjectRoleLabel(role: ProjectRole) {
    return t(PROJECT_ROLE_LABEL_KEYS[role]);
  }

  function getProjectRoleDescription(role: ProjectRole) {
    return t(PROJECT_ROLE_DESCRIPTION_KEYS[role]);
  }

  function renderMember(member: ProjectMember) {
    const isCurrentUser = member.user_id === currentUser.id;
    const canChangeRole = canChangeProjectMemberRole(currentRole, currentUser, member);
    const canRemove = canRemoveProjectMember(currentRole, currentUser, member);
    const isConfirmingRemoval = pendingRemovalId === member.user_id;
    const roleOperation = `role:${member.user_id}` as const;
    const removeOperation = `remove:${member.user_id}` as const;
    const roleDraft = member.role === "owner" ? "owner" : roleDrafts[member.user_id] ?? member.role;
    const roleDescriptionId = `project-member-role-description-${member.user_id}`;
    const removalConfirmationId = getMemberRemovalConfirmationId(member.user_id);
    const removalInProgress = operation === removeOperation;

    return (
      <li
        aria-busy={operation === roleOperation || operation === removeOperation || undefined}
        className="project-members-item"
        data-member-id={member.user_id}
        key={member.user_id}
      >
        <Card className="project-members-card" padding={2}>
          <div className="project-members-identity">
            <ProfileAvatar
              ariaHidden
              className="project-members-avatar"
              fallback={getMemberInitials(member)}
              imageUrl={member.profile_image_url}
              label={member.name || member.email}
            />
            <div className="project-members-copy">
              <div className="project-members-name-row">
                <strong>{member.name}</strong>
                {isCurrentUser ? <Badge label={t("나")} variant="blue" /> : null}
              </div>
              <span className="project-members-email">{member.email}</span>
            </div>
          </div>

          <div className="project-members-role" data-role={member.role}>
            {canChangeRole ? (
              <div style={{ display: "grid", gap: 4, maxWidth: 300, minWidth: 0 }}>
                <div
                  style={{
                    alignItems: "center",
                    display: "flex",
                    gap: 7,
                    justifyContent: "flex-end",
                  }}
                >
                  <label className="project-members-role-field">
                    <span className="project-members-visually-hidden">
                      {t("{name} 역할", { name: member.name })}
                    </span>
                    <select
                      aria-describedby={roleDescriptionId}
                      aria-label={t("{name} 역할", { name: member.name })}
                      className="project-members-role-select"
                      disabled={isBusy}
                      onChange={(event) =>
                        setRoleDrafts((current) => ({
                          ...current,
                          [member.user_id]: event.currentTarget.value as AssignableProjectRole,
                        }))
                      }
                      value={roleDraft}
                    >
                      {ASSIGNABLE_PROJECT_ROLES.map((role) => (
                        <option key={role} value={role}>
                          {getProjectRoleLabel(role)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    isDisabled={isBusy || roleDraft === member.role}
                    isLoading={operation === roleOperation}
                    label={t(
                      roleDraft === "admin" && roleDraft !== member.role
                        ? "관리자로 변경"
                        : "변경",
                    )}
                    onClick={() => void handleRoleChange(member)}
                    size="sm"
                    variant="secondary"
                  />
                </div>
                <span
                  className="project-members-permission-note"
                  id={roleDescriptionId}
                  style={{ textAlign: "right" }}
                >
                  {getProjectRoleDescription(roleDraft)}
                </span>
                {roleDraft === "admin" && roleDraft !== member.role ? (
                  <span
                    className="project-members-permission-note"
                    style={{ textAlign: "right" }}
                  >
                    {t(
                      "관리자로 변경해도 멤버 추가·역할 변경·프로젝트 삭제 권한은 부여되지 않습니다.",
                    )}
                  </span>
                ) : null}
              </div>
            ) : (
              <div style={{ display: "grid", gap: 4, maxWidth: 300, minWidth: 0 }}>
                <span className="project-members-role-label">
                  <Shield aria-hidden="true" size={13} />
                  {getProjectRoleLabel(member.role)}
                </span>
                <span
                  className="project-members-permission-note"
                  id={roleDescriptionId}
                  style={{ textAlign: "right" }}
                >
                  {getProjectRoleDescription(member.role)}
                </span>
              </div>
            )}
          </div>

          {canRemove ? (
            <Button
              aria-controls={removalConfirmationId}
              aria-expanded={isConfirmingRemoval}
              className="project-members-remove"
              id={getMemberRemoveButtonId(member.user_id)}
              icon={isCurrentUser ? <LogOut size={14} /> : <Trash2 size={14} />}
              isDisabled={isBusy || isConfirmingRemoval}
              label={t(isCurrentUser ? "프로젝트 탈퇴" : "멤버 제외")}
              onClick={() => handleRequestRemoveMember(member)}
              size="sm"
              variant="destructive"
            />
          ) : null}
        </Card>
        {isConfirmingRemoval ? (
          <Banner
            container="card"
            description={
              <div style={{ display: "grid", gap: 8 }}>
                <span>
                  {t(
                    isCurrentUser
                      ? "{name} · {role}. 탈퇴하면 이 프로젝트의 자료와 대화에 더 이상 접근할 수 없습니다."
                      : "{name} · {role}. 제외하면 이 사용자는 프로젝트의 자료와 대화에 더 이상 접근할 수 없습니다.",
                    {
                      name: member.name,
                      role: getProjectRoleLabel(member.role),
                    },
                  )}
                </span>
                <div
                  style={{
                    display: "flex",
                    flexWrap: "wrap",
                    gap: 6,
                    justifyContent: "flex-end",
                  }}
                >
                  <Button
                    isDisabled={removalInProgress}
                    label={t("취소")}
                    onClick={() => handleCancelRemoveMember(member)}
                    size="sm"
                    variant="secondary"
                  />
                  <Button
                    isDisabled={removalInProgress}
                    isLoading={removalInProgress}
                    label={t(isCurrentUser ? "프로젝트 탈퇴" : "멤버 제외")}
                    onClick={() => void handleConfirmRemoveMember(member)}
                    size="sm"
                    variant="destructive"
                  />
                </div>
              </div>
            }
            id={removalConfirmationId}
            onKeyDown={(event) => {
              if (event.key === "Escape" && !removalInProgress) {
                event.preventDefault();
                event.stopPropagation();
                handleCancelRemoveMember(member);
              }
            }}
            status="warning"
            title={t(
              isCurrentUser
                ? "프로젝트에서 탈퇴할까요?"
                : "{name}님을 프로젝트에서 제외할까요?",
              { name: member.name },
            )}
          />
        ) : null}
      </li>
    );
  }

  return (
    <section
      aria-labelledby="project-members-panel-title"
      className="project-members-panel"
      ref={panelRef}
    >
      <header className="project-members-header">
        <div className="project-members-heading">
          <Users aria-hidden="true" size={18} />
          <div>
            <h2
              id="project-members-panel-title"
              ref={panelHeadingRef}
              style={{ fontSize: 17, letterSpacing: "-0.02em" }}
              tabIndex={-1}
            >
              {t("프로젝트 멤버")}
            </h2>
            <p>{t("프로젝트에 참여하는 사용자와 역할을 관리합니다.")}</p>
          </div>
        </div>
        {loadState === "loaded" ? (
          <span className="project-members-count">
            {t("{count}명", { count: visibleMembers.length })}
          </span>
        ) : null}
      </header>

      <p
        aria-atomic="true"
        aria-live="polite"
        className="project-members-visually-hidden"
        role="status"
      >
        {visibleStatus ? "" : statusMessage}
      </p>

      {visibleStatus ? (
        <Banner
          container="card"
          isDismissable
          key={visibleStatus.id}
          onDismiss={() => setVisibleStatus(null)}
          status="success"
          title={visibleStatus.message}
        />
      ) : null}

      {errorMessage ? (
        <Banner
          className="project-members-error"
          container="card"
          status="error"
          title={errorMessage}
        />
      ) : null}

      {loadState === "loading" ? (
        <div className="project-members-loading">
          <Spinner label={t("멤버를 불러오는 중")} shade="subtle" size="md" />
        </div>
      ) : null}

      {loadState === "error" ? (
        <div className="project-members-retry">
          <Button
            icon={<RefreshCw size={14} />}
            isDisabled={isRetrying}
            isLoading={isRetrying}
            label={t("다시 시도")}
            onClick={() => void handleRetry()}
            variant="secondary"
          />
        </div>
      ) : null}

      {loadState === "loaded" ? (
        <>
          {canAddMembers ? (
            <Card className="project-members-add-card" padding={3}>
              <form
                aria-busy={operation === "add" || undefined}
                className="project-members-add-form"
                noValidate
                onSubmit={handleAddMember}
              >
                <div className="project-members-add-copy">
                  <UserPlus aria-hidden="true" size={17} />
                  <div>
                    <h2>{t("가입된 사용자 추가")}</h2>
                    <p>{t("PaiM에 가입한 이메일과 부여할 역할을 선택하세요.")}</p>
                  </div>
                </div>
                <div className="project-members-add-fields">
                  <TextInput
                    htmlName="member-email"
                    isDisabled={isBusy}
                    isLabelHidden
                    isRequired
                    label={t("추가할 멤버 이메일")}
                    onChange={(nextEmail) => {
                      setEmail(nextEmail);
                      if (emailError) {
                        setEmailError("");
                      }
                    }}
                    placeholder="name@example.com"
                    ref={addEmailInputRef}
                    status={emailError ? { type: "error", message: emailError } : undefined}
                    type="email"
                    value={email}
                    width="100%"
                  />
                  <label className="project-members-add-role-field">
                    <span className="project-members-visually-hidden">{t("추가할 멤버 역할")}</span>
                    <select
                      aria-describedby="project-members-add-role-description"
                      aria-label={t("추가할 멤버 역할")}
                      className="project-members-role-select"
                      disabled={isBusy}
                      onChange={(event) =>
                        setAddRole(event.currentTarget.value as AssignableProjectRole)
                      }
                      value={addRole}
                    >
                      {ASSIGNABLE_PROJECT_ROLES.map((role) => (
                        <option key={role} value={role}>
                          {getProjectRoleLabel(role)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    icon={<UserPlus size={14} />}
                    isDisabled={isBusy || !email.trim()}
                    isLoading={operation === "add"}
                    label={t("멤버 추가")}
                    type="submit"
                    variant="primary"
                  />
                </div>
                <p
                  className="project-members-permission-note"
                  id="project-members-add-role-description"
                >
                  {getProjectRoleDescription(addRole)}
                  {addRole === "admin"
                    ? ` ${t(
                        "관리자로 추가해도 멤버 추가·역할 변경·프로젝트 삭제 권한은 부여되지 않습니다.",
                      )}`
                    : ""}
                </p>
              </form>
            </Card>
          ) : (
            <p className="project-members-permission-note">
              {t(
                currentRole === "viewer"
                  ? "조회자는 멤버 목록만 볼 수 있습니다. 멤버 추가와 역할 변경은 소유자만, 프로젝트 탈퇴는 멤버 이상만 가능합니다."
                  : "멤버 추가와 역할 변경은 프로젝트 소유자만 할 수 있습니다.",
              )}
            </p>
          )}

          {visibleMembers.length > 0 ? (
            <ul className="project-members-list">{visibleMembers.map(renderMember)}</ul>
          ) : (
            <div className="project-members-empty" role="status">
              <Users aria-hidden="true" size={20} />
              <p>{t("표시할 프로젝트 멤버가 없습니다.")}</p>
            </div>
          )}
        </>
      ) : null}
    </section>
  );
}
