import type { PaimUser } from "./auth";
import { fetchPaimJson } from "./paimApi";

export const PROJECT_ROLES = ["viewer", "member", "admin", "owner"] as const;
export type ProjectRole = (typeof PROJECT_ROLES)[number];
export type AssignableProjectRole = Exclude<ProjectRole, "owner">;

export const ASSIGNABLE_PROJECT_ROLES: readonly AssignableProjectRole[] = [
  "viewer",
  "member",
  "admin",
];

export const PROJECT_ROLE_RANK: Readonly<Record<ProjectRole, number>> = {
  viewer: 0,
  member: 1,
  admin: 2,
  owner: 3,
};

export type ProjectMember = Pick<PaimUser, "email" | "name" | "profile_image_url"> & {
  user_id: PaimUser["id"];
  role: ProjectRole;
  created_at?: string | null;
  last_seen_at?: string | null;
};

export type ProjectMemberRoleUpdate = {
  user_id: PaimUser["id"];
  role: AssignableProjectRole;
};

export function canRole(
  role: ProjectRole | null | undefined,
  minimumRole: ProjectRole,
) {
  return role !== null && role !== undefined && PROJECT_ROLE_RANK[role] >= PROJECT_ROLE_RANK[minimumRole];
}

export function getCurrentProjectMember(members: ProjectMember[], user: PaimUser) {
  return members.find((member) => member.user_id === user.id) ?? null;
}

export function canAddProjectMember(role: ProjectRole | null | undefined) {
  return role === "owner";
}

export function canChangeProjectMemberRole(
  role: ProjectRole | null | undefined,
  currentUser: PaimUser,
  target: ProjectMember,
) {
  return role === "owner" && target.role !== "owner" && target.user_id !== currentUser.id;
}

export function canRemoveProjectMember(
  role: ProjectRole | null | undefined,
  currentUser: PaimUser,
  target: ProjectMember,
) {
  if (role === "owner") {
    return target.role !== "owner";
  }

  return canRole(role, "member") && target.user_id === currentUser.id;
}

export async function fetchProjectMembers(projectId: number, init?: RequestInit) {
  return fetchPaimJson<ProjectMember[]>(
    `/projects/${projectId}/members`,
    init,
  );
}

export async function addProjectMember(
  projectId: number,
  email: string,
  role: AssignableProjectRole = "member",
) {
  return fetchPaimJson<ProjectMember>(`/projects/${projectId}/members`, {
    method: "POST",
    body: JSON.stringify({ email: email.trim().toLowerCase(), role }),
  });
}

export async function updateProjectMemberRole(
  projectId: number,
  memberUserId: PaimUser["id"],
  role: AssignableProjectRole,
) {
  return fetchPaimJson<ProjectMemberRoleUpdate>(
    `/projects/${projectId}/members/${memberUserId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ role }),
    },
  );
}

export async function removeProjectMember(
  projectId: number,
  memberUserId: PaimUser["id"],
) {
  return fetchPaimJson<void>(`/projects/${projectId}/members/${memberUserId}`, {
    method: "DELETE",
  });
}
