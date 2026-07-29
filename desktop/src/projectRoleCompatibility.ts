import type { PaimUser } from "./auth";
import type { ProjectMember, ProjectRole } from "./members";

export type ApiProjectWithOptionalRole = {
  id: number;
  current_user_role?: ProjectRole | null;
};

type ProjectMemberRole = Pick<ProjectMember, "role" | "user_id">;
type FetchProjectMembers = (
  projectId: number,
) => Promise<readonly ProjectMemberRole[]>;

/**
 * Older PaiM servers omit current_user_role from GET /projects. Resolve only
 * those omitted values from the authenticated user's membership row. A role
 * supplied by a newer server, including an explicit null, stays authoritative.
 */
export async function fillMissingProjectRoles<
  Project extends ApiProjectWithOptionalRole,
>(
  projects: readonly Project[],
  currentUser: Pick<PaimUser, "id"> | null,
  fetchMembers: FetchProjectMembers,
): Promise<Project[]> {
  if (!currentUser) {
    return [...projects];
  }

  return Promise.all(
    projects.map(async (project) => {
      if (project.current_user_role !== undefined) {
        return project;
      }

      const members = await fetchMembers(project.id);
      const role =
        members.find((member) => member.user_id === currentUser.id)?.role ??
        null;

      return {
        ...project,
        current_user_role: role,
      };
    }),
  );
}
