import { fetchPaimJson, isPaimApiError } from "./paimApi";

export type ProjectActivityActor = {
  email: string | null;
  id: number | null;
  name: string | null;
  profileImageUrl: string | null;
};

export type ProjectActivityEvent = {
  actor: ProjectActivityActor;
  createdAt: string;
  entityId: string | null;
  entityType: string;
  eventType: string;
  id: number;
  metadata: Record<string, unknown>;
  projectId: number;
};

type ProjectActivityApiItem = {
  actor_email?: string | null;
  actor_name?: string | null;
  actor_profile_image_url?: string | null;
  actor_user_id?: number | null;
  created_at: string;
  entity_id?: string | null;
  entity_type: string;
  event_type: string;
  id: number;
  metadata?: Record<string, unknown> | null;
  project_id: number;
};

type ProjectActivityApiPage = {
  items: ProjectActivityApiItem[];
  next_cursor: string | null;
};

export type ProjectActivityPage = {
  items: ProjectActivityEvent[];
  nextCursor: string | null;
};

export async function fetchProjectActivity(
  projectId: number,
  limit = 50,
): Promise<ProjectActivityPage | null> {
  try {
    const page = await fetchPaimJson<ProjectActivityApiPage>(
      `/projects/${projectId}/activity?limit=${limit}`,
    );
    return {
      items: page.items.map((item) => ({
        actor: {
          email: item.actor_email ?? null,
          id: item.actor_user_id ?? null,
          name: item.actor_name ?? null,
          profileImageUrl: item.actor_profile_image_url ?? null,
        },
        createdAt: item.created_at,
        entityId: item.entity_id ?? null,
        entityType: item.entity_type,
        eventType: item.event_type,
        id: item.id,
        metadata: item.metadata ?? {},
        projectId: item.project_id,
      })),
      nextCursor: page.next_cursor,
    };
  } catch (error) {
    // AWS가 신규 activity API보다 한 버전 이전이면 로컬 기록으로 자연스럽게 대체한다.
    if (isPaimApiError(error) && error.status === 404) {
      return null;
    }
    throw error;
  }
}
