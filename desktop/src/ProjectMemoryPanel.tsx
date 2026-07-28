import {
  Check,
  ChevronDown,
  GripVertical,
  LoaderCircle,
  Pencil,
  Save,
  Trash2,
  X,
} from "lucide-react";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import type { ISODateString } from "@astryxdesign/core/Calendar";
import { CheckboxInput } from "@astryxdesign/core/CheckboxInput";
import { DateInput } from "@astryxdesign/core/DateInput";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { ProgressBar } from "@astryxdesign/core/ProgressBar";
import { TextArea } from "@astryxdesign/core/TextArea";
import { TextInput } from "@astryxdesign/core/TextInput";
import {
  Fragment,
  type FormEvent,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { useI18n } from "./i18n";
import { fetchPaimJson, getErrorMessage, isPaimApiError } from "./paimApi";
import type {
  ProjectMemoryCategory,
  ProjectMemoryItem,
  ProjectMemorySuggestion,
  ProjectWorkspace,
} from "./types";
import type { SuggestionMinConfidence } from "./settings";

type MemoryLoadState = "idle" | "loading" | "loaded" | "error";
type Translate = ReturnType<typeof useI18n>["t"];

type ProjectMemoryPanelProps = {
  canManage: boolean;
  isMaximized: boolean;
  project: ProjectWorkspace;
  reloadRevision: number;
  suggestionMin: SuggestionMinConfidence;
};

type MemoryDraft = {
  content: string;
  owner: string;
  dueDate: string;
};

function toISODateInputValue(value: string): ISODateString | undefined {
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? (value as ISODateString) : undefined;
}

type MemoryPatchPayload = {
  content?: string;
  owner?: string;
  due_date?: string | null;
  completed?: boolean;
  sort_order?: number | null;
};

type ActionDropPlacement = "before" | "after";

type ActionDropTarget = {
  id: number;
  placement: ActionDropPlacement;
};

type MemoryDraftSession = {
  addDraft: MemoryDraft;
  addingCategory: ProjectMemoryCategory | null;
  editDraft: MemoryDraft;
  editingItemId: number | null;
};

type MemoryFocusReturnTarget =
  | { category: ProjectMemoryCategory; kind: "add" }
  | { itemId: number; kind: "edit" };

type MemoryOperationStatus = {
  message: string;
  state: "progress" | "success";
};

type CompletedActionDeleteResult = {
  deletedCount: number;
  remainingCount: number;
};

type ActionDragPointerState = {
  activated: boolean;
  content: string;
  pointerId: number;
  sourceId: number;
  startX: number;
  startY: number;
  target: HTMLElement;
};

const SUMMARY_ITEM_LIMIT = 5;
const MANAGE_DECISION_LIMIT = 8;
const DESTRUCTIVE_CONFIRMATION_TIMEOUT_MS = 6000;
const OPERATION_SUCCESS_TIMEOUT_MS = 4000;
const DRAG_HYSTERESIS_PX = 10;
const REFRESHABLE_SUGGESTION_ERROR_STATUSES = new Set([400, 404, 409]);
const memoryDraftSessions = new Map<string, MemoryDraftSession>();
const MEMORY_CATEGORIES: ProjectMemoryCategory[] = ["action", "decision", "issue", "risk"];
const MEMORY_CATEGORY_META: Record<
  ProjectMemoryCategory,
  {
    empty: string;
    label: string;
  }
> = {
  decision: {
    empty: "서버에 저장된 결정사항이 없습니다",
    label: "결정",
  },
  action: {
    empty: "서버에 저장된 액션이 없습니다",
    label: "액션",
  },
  issue: {
    empty: "서버에 저장된 이슈가 없습니다",
    label: "이슈",
  },
  risk: {
    empty: "서버에 저장된 리스크가 없습니다",
    label: "리스크",
  },
};

function isProjectMemoryItem(value: ProjectMemoryItem) {
  return MEMORY_CATEGORIES.includes(value.category) && Boolean(value.content?.trim());
}

function createEmptyDraft(): MemoryDraft {
  return {
    content: "",
    owner: "",
    dueDate: "",
  };
}

function createEmptyDraftSession(): MemoryDraftSession {
  return {
    addDraft: createEmptyDraft(),
    addingCategory: null,
    editDraft: createEmptyDraft(),
    editingItemId: null,
  };
}

function getMemoryDraftSessionKey(project: ProjectWorkspace) {
  return `${project.id}:${project.apiProjectId ?? "local"}`;
}

function getMemoryAddButtonId(apiProjectId: number | undefined, category: ProjectMemoryCategory) {
  return `project-memory-add-${apiProjectId ?? "local"}-${category}`;
}

function getMemoryEditButtonId(apiProjectId: number | undefined, itemId: number) {
  return `project-memory-edit-${apiProjectId ?? "local"}-${itemId}`;
}

function getMemoryDeleteButtonId(apiProjectId: number | undefined, itemId: number) {
  return `project-memory-delete-${apiProjectId ?? "local"}-${itemId}`;
}

function getMemoryDeleteConfirmationId(apiProjectId: number | undefined, itemId: number) {
  return `project-memory-delete-confirmation-${apiProjectId ?? "local"}-${itemId}`;
}

function createDraftFromItem(item: ProjectMemoryItem): MemoryDraft {
  return {
    content: item.content,
    owner: item.owner ?? "",
    dueDate: item.due_date ?? "",
  };
}

function isMemoryItemCompleted(item: ProjectMemoryItem) {
  return Boolean(item.completed_at);
}

function isMemoryItemVerified(item: ProjectMemoryItem) {
  return item.created_by === "user" || Boolean(item.is_user_verified);
}

function formatMemoryDate(value?: string | null) {
  if (!value) {
    return "";
  }

  return value.split("T")[0] || value;
}

function formatCompactMemoryDate(value?: string | null) {
  const normalizedDate = formatMemoryDate(value);

  if (!normalizedDate) {
    return "";
  }

  const [, month, day] = normalizedDate.split("-");

  return month && day ? `${Number(month)}/${Number(day)}` : normalizedDate;
}

function getTodayDateString() {
  const today = new Date();
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const day = String(today.getDate()).padStart(2, "0");

  return `${year}-${month}-${day}`;
}

function formatActionDueDate(value: string | null | undefined, isOverdue: boolean, t: Translate) {
  const compactDate = formatCompactMemoryDate(value);

  if (!compactDate) {
    return "";
  }

  return isOverdue
    ? t("{date} 지남", { date: compactDate })
    : t("마감 {date}", { date: compactDate });
}

function formatActionCompletedDate(value: string | null | undefined, t: Translate) {
  const compactDate = formatCompactMemoryDate(value);

  return compactDate ? t("{date} 완료", { date: compactDate }) : "";
}

function isActionOverdue(item: ProjectMemoryItem) {
  const dueDate = formatMemoryDate(item.due_date);

  return Boolean(dueDate) && !isMemoryItemCompleted(item) && dueDate < getTodayDateString();
}

function getActionDropTarget(clientX: number, clientY: number): ActionDropTarget | null {
  const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-action-drop-row="true"]'));

  if (rows.length === 0) {
    return null;
  }

  const firstRect = rows[0].getBoundingClientRect();
  const lastRect = rows[rows.length - 1].getBoundingClientRect();
  const bottomDropPadding = Math.max(64, lastRect.height * 1.5);
  const left = Math.min(...rows.map((row) => row.getBoundingClientRect().left));
  const right = Math.max(...rows.map((row) => row.getBoundingClientRect().right));

  if (
    clientX < left ||
    clientX > right ||
    clientY < firstRect.top - 12 ||
    clientY > lastRect.bottom + bottomDropPadding
  ) {
    return null;
  }

  let row = rows.find((candidate) => {
    const rect = candidate.getBoundingClientRect();

    return clientY >= rect.top && clientY <= rect.bottom;
  });

  if (!row) {
    row = clientY > lastRect.bottom ? rows[rows.length - 1] : rows[0];
  }

  const rect = row.getBoundingClientRect();
  const rawId = Number(row.dataset.actionId);

  if (!Number.isFinite(rawId)) {
    return null;
  }

  return {
    id: rawId,
    placement: clientY > rect.top + rect.height / 2 ? "after" : "before",
  };
}

function getActionDisplayItems(items: ProjectMemoryItem[]) {
  return [...items].sort((left, right) => {
    const leftDone = isMemoryItemCompleted(left);
    const rightDone = isMemoryItemCompleted(right);

    if (leftDone !== rightDone) {
      return leftDone ? 1 : -1;
    }

    const leftOrder = left.sort_order;
    const rightOrder = right.sort_order;
    const leftHasOrder = typeof leftOrder === "number";
    const rightHasOrder = typeof rightOrder === "number";

    if (leftHasOrder && rightHasOrder && leftOrder !== rightOrder) {
      return leftOrder - rightOrder;
    }

    if (leftHasOrder !== rightHasOrder) {
      return leftHasOrder ? -1 : 1;
    }

    return 0;
  });
}

function formatSuggestionTitle(title: string) {
  const trimmed = title.trim();

  return trimmed.length > 56 ? `${trimmed.slice(0, 56).trim()}...` : trimmed;
}

function isMeaningfulMemoryPatch(payload: MemoryPatchPayload) {
  return Object.prototype.hasOwnProperty.call(payload, "content");
}

function shouldRefreshSuggestionState(error: unknown) {
  return (
    isPaimApiError(error) &&
    REFRESHABLE_SUGGESTION_ERROR_STATUSES.has(error.status)
  );
}

function createMemoryPatch(item: ProjectMemoryItem, draft: MemoryDraft): MemoryPatchPayload {
  const payload: MemoryPatchPayload = {};

  const content = draft.content.trim();
  const owner = draft.owner.trim();
  const dueDate = draft.dueDate.trim();

  if (item.content !== content) {
    payload.content = content;
  }
  if ((item.owner ?? "") !== owner) {
    payload.owner = owner;
  }
  if ((item.due_date ?? "") !== dueDate) {
    payload.due_date = dueDate || null;
  }

  return payload;
}

function createMemoryPostBody(category: ProjectMemoryCategory, draft: MemoryDraft) {
  const body: Record<string, string> = {
    category,
    content: draft.content.trim(),
  };
  const owner = draft.owner.trim();
  const dueDate = draft.dueDate.trim();

  if (owner) {
    body.owner = owner;
  }
  if (dueDate) {
    body.due_date = dueDate;
  }

  return body;
}

function groupMemoryItems(items: ProjectMemoryItem[]) {
  return MEMORY_CATEGORIES.reduce(
    (groups, category) => ({
      ...groups,
      [category]: items.filter((item) => item.category === category),
    }),
    {} as Record<ProjectMemoryCategory, ProjectMemoryItem[]>,
  );
}

function getMemoryItemMeta(item: ProjectMemoryItem) {
  return [item.topic, item.owner, item.date, item.source].filter(Boolean).join(" · ");
}

function getActionMetaParts(item: ProjectMemoryItem, t: Translate) {
  const completedAt = formatActionCompletedDate(item.completed_at, t);
  const actionIsOverdue = isActionOverdue(item);
  const dueDateLabel = formatActionDueDate(item.due_date, actionIsOverdue, t);
  const parts: Array<{
    isOverdue?: boolean;
    isVerified?: boolean;
    key: string;
    label: string;
  }> = [];

  if (isMemoryItemVerified(item)) {
    parts.push({ isVerified: true, key: "verified", label: t("✓ 검증됨") });
  }

  if (item.owner && !completedAt) {
    parts.push({ key: "owner", label: t("담당 {name}", { name: item.owner }) });
  }

  if (completedAt) {
    parts.push({ key: "completed", label: completedAt });
  } else if (dueDateLabel) {
    parts.push({
      isOverdue: actionIsOverdue,
      key: "due",
      label: dueDateLabel,
    });
  }

  return parts;
}

function renderMetaParts(parts: ReturnType<typeof getActionMetaParts>) {
  if (parts.length === 0) {
    return null;
  }

  return (
    <>
      {parts.map((part, index) => (
        <Fragment key={part.key}>
          {index > 0 ? <i>·</i> : null}
          <em
            data-overdue={part.isOverdue ? "true" : undefined}
            data-verified={part.isVerified ? "true" : undefined}
          >
            {part.label}
          </em>
        </Fragment>
      ))}
    </>
  );
}

function MemoryItemRows({
  category,
  items,
  limit,
  variant = "manage",
}: {
  category: ProjectMemoryCategory;
  items: ProjectMemoryItem[];
  limit?: number;
  variant?: "manage" | "summary";
}) {
  const { t } = useI18n();
  const visibleItems = typeof limit === "number" ? items.slice(0, limit) : items;
  const hiddenCount = Math.max(items.length - visibleItems.length, 0);

  if (items.length === 0) {
    return (
      <p className="project-memory-empty-row">{t(MEMORY_CATEGORY_META[category].empty)}</p>
    );
  }

  return (
    <>
      {visibleItems.map((item) => {
        const meta = getMemoryItemMeta(item);

        if (variant === "summary") {
          return (
            <p
              className="project-memory-summary-item"
              data-completed={isMemoryItemCompleted(item)}
              key={item.id}
            >
              <span className="project-memory-bullet">·</span>
              <span className="project-memory-content" title={item.content}>
                {item.content}
              </span>
              {meta ? (
                <small className="project-memory-meta" title={meta}>
                  {meta}
                </small>
              ) : null}
            </p>
          );
        }

        return (
          <p key={item.id}>
            <span>·</span>
            {item.content}
            {meta ? <small className="project-memory-meta">{meta}</small> : null}
          </p>
        );
      })}
      {hiddenCount > 0 ? (
        <p className="project-memory-summary-more">{t("외 {count}개", { count: hiddenCount })}</p>
      ) : null}
    </>
  );
}

export function ProjectMemoryPanel({
  canManage,
  isMaximized,
  project,
  reloadRevision,
  suggestionMin,
}: ProjectMemoryPanelProps) {
  const { t } = useI18n();
  const apiProjectId = project.apiProjectId;
  const draftSessionKey = getMemoryDraftSessionKey(project);
  const initialDraftSession = memoryDraftSessions.get(draftSessionKey) ?? createEmptyDraftSession();
  const [memoryItems, setMemoryItems] = useState<ProjectMemoryItem[]>([]);
  const [memorySuggestions, setMemorySuggestions] = useState<ProjectMemorySuggestion[]>([]);
  const [loadState, setLoadState] = useState<MemoryLoadState>("idle");
  const [errorMessage, setErrorMessage] = useState("");
  const [operationError, setOperationError] = useState("");
  const [operationStatus, setOperationStatus] = useState<MemoryOperationStatus | null>(null);
  const [editingItemId, setEditingItemId] = useState<number | null>(
    initialDraftSession.editingItemId,
  );
  const [editDraft, setEditDraft] = useState<MemoryDraft>(initialDraftSession.editDraft);
  const [addingCategory, setAddingCategory] = useState<ProjectMemoryCategory | null>(
    initialDraftSession.addingCategory,
  );
  const [addDraft, setAddDraft] = useState<MemoryDraft>(initialDraftSession.addDraft);
  const [pendingDeleteId, setPendingDeleteId] = useState<number | null>(null);
  const [savingItemIds, setSavingItemIds] = useState<number[]>([]);
  const [isAdding, setIsAdding] = useState(false);
  const [isReordering, setIsReordering] = useState(false);
  const [resolvingSuggestionIds, setResolvingSuggestionIds] = useState<number[]>([]);
  const [draggingActionId, setDraggingActionId] = useState<number | null>(null);
  const [dragOverActionId, setDragOverActionId] = useState<number | null>(null);
  const [dragOverPlacement, setDragOverPlacement] = useState<ActionDropPlacement | null>(null);
  const [dragPreview, setDragPreview] = useState<{ content: string; x: number; y: number } | null>(null);
  const [showAllDecisions, setShowAllDecisions] = useState(false);
  const [showCompletedActions, setShowCompletedActions] = useState(false);
  const [pendingCompletedActionDelete, setPendingCompletedActionDelete] = useState(false);
  const [isDeletingCompletedActions, setIsDeletingCompletedActions] = useState(false);
  const [completedActionDeleteResult, setCompletedActionDeleteResult] =
    useState<CompletedActionDeleteResult | null>(null);
  const memoryLoadGenerationRef = useRef(0);
  const suggestionLoadGenerationRef = useRef(0);
  const dragPointerRef = useRef<ActionDragPointerState | null>(null);
  const draftSessionRef = useRef<MemoryDraftSession>(initialDraftSession);
  const focusReturnTargetRef = useRef<MemoryFocusReturnTarget | null>(
    initialDraftSession.addingCategory
      ? { category: initialDraftSession.addingCategory, kind: "add" }
      : initialDraftSession.editingItemId !== null
        ? { itemId: initialDraftSession.editingItemId, kind: "edit" }
        : null,
  );
  const previousApiProjectIdRef = useRef(apiProjectId);
  const previousDraftSessionKeyRef = useRef(draftSessionKey);
  const panelRef = useRef<HTMLDivElement>(null);
  const groupedItems = useMemo(() => groupMemoryItems(memoryItems), [memoryItems]);
  const memoryItemsById = useMemo(
    () => new Map(memoryItems.map((item) => [item.id, item])),
    [memoryItems],
  );
  const actionItems = useMemo(() => getActionDisplayItems(groupedItems.action), [groupedItems]);
  const actionTodoItems = useMemo(
    () => actionItems.filter((item) => !isMemoryItemCompleted(item)),
    [actionItems],
  );

  draftSessionRef.current = {
    addDraft,
    addingCategory,
    editDraft,
    editingItemId,
  };

  useEffect(() => {
    const session = draftSessionRef.current;

    if (session.addingCategory === null && session.editingItemId === null) {
      memoryDraftSessions.delete(draftSessionKey);
      return;
    }

    memoryDraftSessions.set(draftSessionKey, session);
  }, [addDraft, addingCategory, draftSessionKey, editDraft, editingItemId]);

  useEffect(
    () => () => {
      const session = draftSessionRef.current;

      if (session.addingCategory === null && session.editingItemId === null) {
        memoryDraftSessions.delete(draftSessionKey);
      } else {
        memoryDraftSessions.set(draftSessionKey, session);
      }

      const dragPointer = dragPointerRef.current;
      if (dragPointer?.target.hasPointerCapture(dragPointer.pointerId)) {
        dragPointer.target.releasePointerCapture(dragPointer.pointerId);
      }
      dragPointerRef.current = null;
    },
    [draftSessionKey],
  );

  useEffect(() => {
    if (operationStatus?.state !== "success") {
      return;
    }

    const completedStatus = operationStatus;
    const timeoutId = window.setTimeout(() => {
      setOperationStatus((current) => (current === completedStatus ? null : current));
    }, OPERATION_SUCCESS_TIMEOUT_MS);

    return () => window.clearTimeout(timeoutId);
  }, [operationStatus]);

  useEffect(() => {
    if (!pendingCompletedActionDelete) {
      return;
    }

    const timeoutId = window.setTimeout(
      () => setPendingCompletedActionDelete(false),
      DESTRUCTIVE_CONFIRMATION_TIMEOUT_MS,
    );
    return () => window.clearTimeout(timeoutId);
  }, [pendingCompletedActionDelete]);
  const completedActionItems = useMemo(
    () => actionItems.filter(isMemoryItemCompleted),
    [actionItems],
  );
  const visibleMemorySuggestions = useMemo(
    () =>
      suggestionMin === "high"
        ? memorySuggestions.filter((suggestion) => suggestion.confidence === "high")
        : memorySuggestions,
    [memorySuggestions, suggestionMin],
  );
  const suggestedActionIds = useMemo(
    () =>
      new Set(
        visibleMemorySuggestions
          .filter((suggestion) => suggestion.kind === "complete_action")
          .map((suggestion) => suggestion.memory_id),
      ),
    [visibleMemorySuggestions],
  );
  const actionCompletedCount = groupedItems.action.filter(isMemoryItemCompleted).length;
  const totalCount = memoryItems.length;
  const showManageUi = isMaximized && canManage && typeof apiProjectId === "number";

  function setItemSaving(memoryId: number, saving: boolean) {
    setSavingItemIds((current) =>
      saving
        ? [...new Set([...current, memoryId])]
        : current.filter((itemId) => itemId !== memoryId),
    );
  }

  function isItemSaving(memoryId: number) {
    return savingItemIds.includes(memoryId) || isReordering;
  }

  function setSuggestionResolving(suggestionId: number, resolving: boolean) {
    setResolvingSuggestionIds((current) =>
      resolving
        ? [...new Set([...current, suggestionId])]
        : current.filter((itemId) => itemId !== suggestionId),
    );
  }

  function replaceMemoryItem(nextItem: ProjectMemoryItem) {
    setMemoryItems((current) =>
      current.map((item) => (item.id === nextItem.id ? nextItem : item)),
    );
  }

  async function patchMemoryItem(memoryId: number, payload: MemoryPatchPayload) {
    return fetchPaimJson<ProjectMemoryItem>(
      `/projects/${apiProjectId}/memory/${memoryId}`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
      },
    );
  }

  async function fetchMemorySuggestions() {
    if (typeof apiProjectId !== "number") {
      return [];
    }

    return fetchPaimJson<ProjectMemorySuggestion[]>(
      `/projects/${apiProjectId}/suggestions?status=pending&kind=all`,
    );
  }

  async function reloadMemorySuggestions() {
    const loadGeneration = ++suggestionLoadGenerationRef.current;

    try {
      const suggestions = await fetchMemorySuggestions();
      if (loadGeneration === suggestionLoadGenerationRef.current) {
        setMemorySuggestions(suggestions);
      }
    } catch (error) {
      if (loadGeneration === suggestionLoadGenerationRef.current) {
        setOperationError(getErrorMessage(error, t("메모리 제안을 다시 불러올 수 없습니다")));
      }
    }
  }

  async function loadProjectMemory(
    options: {
      preserveCurrentDataOnError?: boolean;
      preserveOperationError?: boolean;
    } = {},
  ) {
    const loadGeneration = ++memoryLoadGenerationRef.current;
    const suggestionLoadGeneration = ++suggestionLoadGenerationRef.current;

    if (typeof apiProjectId !== "number") {
      setMemoryItems([]);
      setMemorySuggestions([]);
      setLoadState("idle");
      setErrorMessage("");
      setOperationError("");
      return;
    }

    setLoadState("loading");
    setErrorMessage("");
    if (!options.preserveOperationError) {
      setOperationError("");
    }

    try {
      const [items, suggestions] = await Promise.all([
        fetchPaimJson<ProjectMemoryItem[]>(`/projects/${apiProjectId}/memory`),
        fetchMemorySuggestions(),
      ]);

      if (loadGeneration !== memoryLoadGenerationRef.current) {
        return;
      }

      setMemoryItems(items.filter(isProjectMemoryItem));
      if (suggestionLoadGeneration === suggestionLoadGenerationRef.current) {
        setMemorySuggestions(suggestions);
      }
      setLoadState("loaded");
    } catch (error) {
      if (loadGeneration !== memoryLoadGenerationRef.current) {
        return;
      }

      if (!options.preserveCurrentDataOnError) {
        setMemoryItems([]);
        setMemorySuggestions([]);
      }
      setErrorMessage(getErrorMessage(error, t("프로젝트 메모리를 불러올 수 없습니다")));
      setLoadState("error");
    }
  }

  useEffect(() => {
    void loadProjectMemory();

    return () => {
      memoryLoadGenerationRef.current += 1;
      suggestionLoadGenerationRef.current += 1;
    };
  }, [apiProjectId, canManage, reloadRevision]);

  useEffect(() => {
    if (previousApiProjectIdRef.current === apiProjectId) {
      return;
    }

    previousApiProjectIdRef.current = apiProjectId;
    memoryDraftSessions.delete(previousDraftSessionKeyRef.current);
    memoryDraftSessions.delete(draftSessionKey);
    previousDraftSessionKeyRef.current = draftSessionKey;
    draftSessionRef.current = createEmptyDraftSession();
    setEditingItemId(null);
    setEditDraft(createEmptyDraft());
    setAddingCategory(null);
    setAddDraft(createEmptyDraft());
    setPendingDeleteId(null);
    setOperationError("");
    setOperationStatus(null);
    setResolvingSuggestionIds([]);
    setDraggingActionId(null);
    setDragOverActionId(null);
    setDragOverPlacement(null);
    setDragPreview(null);
    setShowAllDecisions(false);
    setShowCompletedActions(false);
    setPendingCompletedActionDelete(false);
    setCompletedActionDeleteResult(null);
    focusReturnTargetRef.current = null;
  }, [apiProjectId]);

  useEffect(() => {
    if (completedActionItems.length === 0) {
      setShowCompletedActions(false);
      setPendingCompletedActionDelete(false);
      setCompletedActionDeleteResult(null);
    }
  }, [completedActionItems.length]);

  function startEdit(item: ProjectMemoryItem) {
    focusReturnTargetRef.current = { itemId: item.id, kind: "edit" };
    setEditingItemId(item.id);
    setEditDraft(createDraftFromItem(item));
    setAddingCategory(null);
    setAddDraft(createEmptyDraft());
    setPendingDeleteId(null);
    setOperationError("");
    setOperationStatus(null);
  }

  function startAdd(category: ProjectMemoryCategory) {
    focusReturnTargetRef.current = { category, kind: "add" };
    setAddingCategory(category);
    setAddDraft(createEmptyDraft());
    setEditingItemId(null);
    setEditDraft(createEmptyDraft());
    setPendingDeleteId(null);
    setOperationError("");
    setOperationStatus(null);
  }

  function restoreDraftTriggerFocus(target: MemoryFocusReturnTarget | null) {
    focusReturnTargetRef.current = null;
    if (!target) {
      return;
    }

    const targetId =
      target.kind === "add"
        ? getMemoryAddButtonId(apiProjectId, target.category)
        : getMemoryEditButtonId(apiProjectId, target.itemId);

    window.requestAnimationFrame(() => {
      const element = panelRef.current?.querySelector<HTMLElement>(`[id="${targetId}"]`);
      element?.focus({ preventScroll: true });
    });
  }

  function clearPersistedDraftSession() {
    draftSessionRef.current = createEmptyDraftSession();
    memoryDraftSessions.delete(draftSessionKey);
  }

  function closeEditAndRestoreFocus() {
    const returnTarget = focusReturnTargetRef.current ??
      (editingItemId !== null ? { itemId: editingItemId, kind: "edit" as const } : null);
    setEditingItemId(null);
    setEditDraft(createEmptyDraft());
    setOperationError("");
    setOperationStatus(null);
    clearPersistedDraftSession();
    restoreDraftTriggerFocus(returnTarget);
  }

  function closeAddAndRestoreFocus() {
    const returnTarget = focusReturnTargetRef.current ??
      (addingCategory ? { category: addingCategory, kind: "add" as const } : null);
    setAddingCategory(null);
    setAddDraft(createEmptyDraft());
    setOperationError("");
    setOperationStatus(null);
    clearPersistedDraftSession();
    restoreDraftTriggerFocus(returnTarget);
  }

  function setOperationProgress(label: string) {
    setOperationStatus({ message: `${label} · ${t("처리 중")}`, state: "progress" });
  }

  function setOperationSuccess(label: string) {
    setOperationStatus({ message: `${label} · ${t("완료")}`, state: "success" });
  }

  async function handleSaveEdit(item: ProjectMemoryItem, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (typeof apiProjectId !== "number") {
      return;
    }

    const content = editDraft.content.trim();
    if (!content) {
      setOperationStatus(null);
      setOperationError(t("내용을 입력해 주세요."));
      return;
    }

    const payload = createMemoryPatch(item, editDraft);
    if (Object.keys(payload).length === 0) {
      closeEditAndRestoreFocus();
      return;
    }

    const previousItem = item;
    const optimisticItem: ProjectMemoryItem = {
      ...item,
      content,
      owner: editDraft.owner.trim(),
      due_date: editDraft.dueDate.trim() || null,
      is_user_verified: 1,
      updated_by: "user",
    };

    setOperationError("");
    setOperationProgress(t("메모리 수정"));
    setItemSaving(item.id, true);
    replaceMemoryItem(optimisticItem);

    try {
      const updatedItem = await patchMemoryItem(item.id, payload);
      replaceMemoryItem(updatedItem);
      const returnTarget = focusReturnTargetRef.current ?? { itemId: item.id, kind: "edit" };
      setEditingItemId(null);
      setEditDraft(createEmptyDraft());
      clearPersistedDraftSession();
      setOperationSuccess(t("메모리 수정"));
      restoreDraftTriggerFocus(returnTarget);
      if (isMeaningfulMemoryPatch(payload)) {
        await reloadMemorySuggestions();
      }
    } catch (error) {
      replaceMemoryItem(previousItem);
      setOperationStatus(null);
      setOperationError(getErrorMessage(error, t("메모리를 수정할 수 없습니다")));
    } finally {
      setItemSaving(item.id, false);
    }
  }

  async function handleCreateMemory(category: ProjectMemoryCategory, event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (typeof apiProjectId !== "number") {
      return;
    }

    if (!addDraft.content.trim()) {
      setOperationStatus(null);
      setOperationError(t("내용을 입력해 주세요."));
      return;
    }

    const operationLabel = `${t("메모리")} · ${t("추가")}`;
    setOperationError("");
    setOperationProgress(operationLabel);
    setIsAdding(true);

    try {
      const createdItem = await fetchPaimJson<ProjectMemoryItem>(
        `/projects/${apiProjectId}/memory`,
        {
          method: "POST",
          body: JSON.stringify(createMemoryPostBody(category, addDraft)),
        },
      );

      setMemoryItems((current) => [createdItem, ...current]);
      const returnTarget = focusReturnTargetRef.current ?? { category, kind: "add" };
      setAddingCategory(null);
      setAddDraft(createEmptyDraft());
      clearPersistedDraftSession();
      setOperationSuccess(operationLabel);
      restoreDraftTriggerFocus(returnTarget);
    } catch (error) {
      setOperationStatus(null);
      setOperationError(getErrorMessage(error, t("메모리를 추가할 수 없습니다")));
    } finally {
      setIsAdding(false);
    }
  }

  function handleRequestDeleteMemory(item: ProjectMemoryItem) {
    setPendingDeleteId(item.id);
    setOperationError("");
    setOperationStatus(null);
    window.requestAnimationFrame(() => {
      document
        .getElementById(getMemoryDeleteConfirmationId(apiProjectId, item.id))
        ?.querySelector<HTMLElement>("button")
        ?.focus();
    });
  }

  function handleCancelDeleteMemory(item: ProjectMemoryItem) {
    setPendingDeleteId(null);
    window.requestAnimationFrame(() => {
      document.getElementById(getMemoryDeleteButtonId(apiProjectId, item.id))?.focus();
    });
  }

  async function handleConfirmDeleteMemory(
    item: ProjectMemoryItem,
    category: ProjectMemoryCategory,
  ) {
    if (typeof apiProjectId !== "number") {
      return;
    }

    const operationLabel = t("메모리 삭제");
    const currentEditButton = document.getElementById(
      getMemoryEditButtonId(apiProjectId, item.id),
    );
    const sectionEditButtons = Array.from(
      currentEditButton
        ?.closest(".project-memory-manage-section")
        ?.querySelectorAll<HTMLElement>('[id^="project-memory-edit-"]') ?? [],
    );
    const currentIndex = sectionEditButtons.indexOf(currentEditButton as HTMLElement);
    const focusCandidateIds = [
      sectionEditButtons[currentIndex + 1]?.id,
      sectionEditButtons[currentIndex - 1]?.id,
      getMemoryAddButtonId(apiProjectId, category),
    ].filter((id): id is string => Boolean(id));
    setOperationError("");
    setOperationProgress(operationLabel);
    setItemSaving(item.id, true);

    const finishDelete = () => {
      setMemoryItems((current) => current.filter((candidate) => candidate.id !== item.id));
      setPendingDeleteId(null);
      setOperationSuccess(operationLabel);
      window.requestAnimationFrame(() => {
        focusCandidateIds
          .map((id) => panelRef.current?.querySelector<HTMLElement>(`[id="${id}"]`))
          .find(Boolean)
          ?.focus({ preventScroll: true });
      });
    };

    try {
      await fetchPaimJson<void>(`/projects/${apiProjectId}/memory/${item.id}`, {
        method: "DELETE",
      });
      finishDelete();
    } catch (error) {
      if (isPaimApiError(error) && error.status === 404) {
        finishDelete();
        return;
      }

      setOperationStatus(null);
      setOperationError(getErrorMessage(error, t("메모리를 삭제할 수 없습니다")));
    } finally {
      setItemSaving(item.id, false);
    }
  }

  async function handleDeleteCompletedActions() {
    if (typeof apiProjectId !== "number" || completedActionItems.length === 0) {
      return;
    }

    const isRetryingPartialDelete =
      completedActionDeleteResult !== null &&
      completedActionDeleteResult.remainingCount === completedActionItems.length;

    if (!pendingCompletedActionDelete && !isRetryingPartialDelete) {
      setPendingCompletedActionDelete(true);
      setCompletedActionDeleteResult(null);
      setOperationError("");
      setOperationStatus(null);
      return;
    }

    const itemsToDelete = completedActionItems;
    const deletingIds = itemsToDelete.map((item) => item.id);
    const operationLabel = t("완료 항목 모두 삭제");
    const previouslyDeletedCount = isRetryingPartialDelete
      ? completedActionDeleteResult.deletedCount
      : 0;
    let deletedThisAttempt = 0;
    let nextItems = memoryItems;

    setOperationError("");
    setOperationProgress(operationLabel);
    setPendingCompletedActionDelete(false);
    setIsDeletingCompletedActions(true);
    setSavingItemIds((current) => [...new Set([...current, ...deletingIds])]);

    try {
      for (const item of itemsToDelete) {
        try {
          await fetchPaimJson<void>(`/projects/${apiProjectId}/memory/${item.id}`, {
            method: "DELETE",
          });
        } catch (error) {
          if (!(isPaimApiError(error) && error.status === 404)) {
            throw error;
          }
        }

        nextItems = nextItems.filter((candidate) => candidate.id !== item.id);
        deletedThisAttempt += 1;
        setMemoryItems(nextItems);
      }

      setPendingCompletedActionDelete(false);
      setCompletedActionDeleteResult(null);
      setShowCompletedActions(false);
      setOperationSuccess(operationLabel);
      restoreDraftTriggerFocus({ category: "action", kind: "add" });
    } catch (error) {
      const deletedCount = previouslyDeletedCount + deletedThisAttempt;
      const remainingCount = Math.max(itemsToDelete.length - deletedThisAttempt, 0);

      setCompletedActionDeleteResult({ deletedCount, remainingCount });
      setOperationStatus(null);
      setOperationError(
        `${t("{deleted}개 삭제 · {remaining}개 남음", {
          deleted: deletedCount,
          remaining: remainingCount,
        })} · ${getErrorMessage(error, t("완료 항목 삭제가 중단되었습니다"))}`,
      );
    } finally {
      setSavingItemIds((current) => current.filter((itemId) => !deletingIds.includes(itemId)));
      setIsDeletingCompletedActions(false);
    }
  }

  async function handleToggleCompleted(item: ProjectMemoryItem) {
    if (typeof apiProjectId !== "number") {
      return;
    }

    const previousItem = item;
    const completed = !isMemoryItemCompleted(item);

    setOperationError("");
    setOperationProgress(t("메모리 수정"));
    setItemSaving(item.id, true);
    replaceMemoryItem({
      ...item,
      completed_at: completed ? new Date().toISOString() : null,
    });

    try {
      const updatedItem = await patchMemoryItem(item.id, { completed });
      replaceMemoryItem(updatedItem);
      setOperationSuccess(t("메모리 수정"));
    } catch (error) {
      replaceMemoryItem(previousItem);
      setOperationStatus(null);
      setOperationError(getErrorMessage(error, t("완료 상태를 변경할 수 없습니다")));
    } finally {
      setItemSaving(item.id, false);
    }
  }

  async function handleResolveSuggestion(suggestion: ProjectMemorySuggestion, resolution: "accept" | "reject") {
    if (typeof apiProjectId !== "number") {
      return;
    }

    setOperationError("");
    setOperationStatus(null);
    setSuggestionResolving(suggestion.id, true);

    try {
      await fetchPaimJson<void>(
        `/projects/${apiProjectId}/suggestions/${suggestion.id}/${resolution}`,
        { method: "POST" },
      );
      await loadProjectMemory({ preserveCurrentDataOnError: true });
    } catch (error) {
      setOperationError(getErrorMessage(error, t("제안을 처리할 수 없습니다")));

      if (shouldRefreshSuggestionState(error)) {
        await loadProjectMemory({
          preserveCurrentDataOnError: true,
          preserveOperationError: true,
        });
      }
    } finally {
      setSuggestionResolving(suggestion.id, false);
    }
  }

  async function reorderActionItems(sourceId: number, target: ActionDropTarget) {
    if (typeof apiProjectId !== "number") {
      return;
    }

    const currentIndex = actionTodoItems.findIndex((candidate) => candidate.id === sourceId);
    const targetIndex = actionTodoItems.findIndex((candidate) => candidate.id === target.id);

    if (currentIndex < 0 || targetIndex < 0) {
      return;
    }

    const reorderedItems = [...actionTodoItems];
    const [movedItem] = reorderedItems.splice(currentIndex, 1);
    if (!movedItem) {
      return;
    }

    let nextIndex = target.placement === "after" ? targetIndex + 1 : targetIndex;

    if (currentIndex < nextIndex) {
      nextIndex -= 1;
    }

    nextIndex = Math.max(0, Math.min(nextIndex, reorderedItems.length));
    reorderedItems.splice(nextIndex, 0, movedItem);
    const nextOrders = new Map(reorderedItems.map((candidate, index) => [candidate.id, index + 1]));
    const changedItems = reorderedItems
      .map((candidate) => ({
        id: candidate.id,
        sort_order: nextOrders.get(candidate.id) ?? null,
      }))
      .filter(({ id, sort_order }) => {
        const currentItem = memoryItems.find((candidate) => candidate.id === id);
        return currentItem?.sort_order !== sort_order;
      });

    if (changedItems.length === 0) {
      return;
    }

    const previousItems = memoryItems;
    const operationLabel = `${t("{content} 순서 변경", {
      content: formatSuggestionTitle(movedItem.content),
    })} · ${nextIndex + 1}/${reorderedItems.length}`;
    setOperationError("");
    setOperationProgress(operationLabel);
    setIsReordering(true);
    setMemoryItems((current) =>
      current.map((candidate) => {
        const nextOrder = nextOrders.get(candidate.id);

        return typeof nextOrder === "number"
          ? { ...candidate, sort_order: nextOrder }
          : candidate;
      }),
    );

    try {
      for (const changedItem of changedItems) {
        const updatedItem = await patchMemoryItem(changedItem.id, {
          sort_order: changedItem.sort_order,
        });
        replaceMemoryItem(updatedItem);
      }
      setOperationSuccess(operationLabel);
    } catch (error) {
      setMemoryItems(previousItems);
      setOperationStatus(null);
      setOperationError(getErrorMessage(error, t("액션 순서를 변경할 수 없습니다")));
    } finally {
      setIsReordering(false);
    }
  }

  function handleActionPointerDown(event: ReactPointerEvent<HTMLElement>, item: ProjectMemoryItem) {
    if (event.button !== 0 || !event.isPrimary || isReordering) {
      return;
    }

    event.currentTarget.setPointerCapture(event.pointerId);
    dragPointerRef.current = {
      activated: false,
      content: item.content,
      pointerId: event.pointerId,
      sourceId: item.id,
      startX: event.clientX,
      startY: event.clientY,
      target: event.currentTarget,
    };
    setDragOverActionId(null);
    setDragOverPlacement(null);
  }

  function handleActionPointerMove(event: ReactPointerEvent<HTMLElement>) {
    const dragPointer = dragPointerRef.current;
    if (!dragPointer || event.pointerId !== dragPointer.pointerId) {
      return;
    }

    if (!dragPointer.activated) {
      const distance = Math.hypot(
        event.clientX - dragPointer.startX,
        event.clientY - dragPointer.startY,
      );
      if (distance < DRAG_HYSTERESIS_PX) {
        return;
      }

      dragPointer.activated = true;
      setDraggingActionId(dragPointer.sourceId);
      setDragPreview({
        content: dragPointer.content,
        x: event.clientX,
        y: event.clientY,
      });
    }

    event.preventDefault();
    const target = getActionDropTarget(event.clientX, event.clientY);
    setDragPreview((current) =>
      current ? { ...current, x: event.clientX, y: event.clientY } : current,
    );
    setDragOverActionId(
      target && target.id !== dragPointer.sourceId ? target.id : null,
    );
    setDragOverPlacement(
      target && target.id !== dragPointer.sourceId ? target.placement : null,
    );
  }

  function clearActionPointerState(pointerId: number) {
    const dragPointer = dragPointerRef.current;
    if (!dragPointer || dragPointer.pointerId !== pointerId) {
      return;
    }

    if (dragPointer.target.hasPointerCapture(pointerId)) {
      dragPointer.target.releasePointerCapture(pointerId);
    }
    dragPointerRef.current = null;
    setDraggingActionId(null);
    setDragOverActionId(null);
    setDragOverPlacement(null);
    setDragPreview(null);
  }

  function handleActionPointerUp(event: ReactPointerEvent<HTMLElement>) {
    const dragPointer = dragPointerRef.current;
    if (!dragPointer || event.pointerId !== dragPointer.pointerId) {
      return;
    }

    const target = dragPointer.activated
      ? getActionDropTarget(event.clientX, event.clientY)
      : null;
    const sourceId = dragPointer.sourceId;
    const wasActivated = dragPointer.activated;
    clearActionPointerState(event.pointerId);

    if (wasActivated && target && target.id !== sourceId) {
      void reorderActionItems(sourceId, target);
    }
  }

  function handleActionPointerCancel(event: ReactPointerEvent<HTMLElement>) {
    clearActionPointerState(event.pointerId);
  }

  function handleActionReorderKeyDown(
    event: KeyboardEvent<HTMLButtonElement>,
    item: ProjectMemoryItem,
  ) {
    if (isReordering) {
      return;
    }

    const currentIndex = actionTodoItems.findIndex((candidate) => candidate.id === item.id);
    if (currentIndex < 0) {
      return;
    }

    let target: ActionDropTarget | null = null;
    if (event.key === "ArrowUp" && currentIndex > 0) {
      target = { id: actionTodoItems[currentIndex - 1].id, placement: "before" };
    } else if (event.key === "ArrowDown" && currentIndex < actionTodoItems.length - 1) {
      target = { id: actionTodoItems[currentIndex + 1].id, placement: "after" };
    } else if (event.key === "Home" && currentIndex > 0) {
      target = { id: actionTodoItems[0].id, placement: "before" };
    } else if (event.key === "End" && currentIndex < actionTodoItems.length - 1) {
      target = { id: actionTodoItems[actionTodoItems.length - 1].id, placement: "after" };
    }

    if (!target) {
      return;
    }

    event.preventDefault();
    void reorderActionItems(item.id, target);
  }

  function renderDraftFields(
    draft: MemoryDraft,
    onChange: (draft: MemoryDraft) => void,
    disabled: boolean,
  ) {
    return (
      <>
        <TextArea
          hasAutoFocus
          isDisabled={disabled}
          isLabelHidden
          label={t("메모리 내용")}
          onChange={(content) => onChange({ ...draft, content })}
          placeholder={t("내용")}
          isRequired
          rows={3}
          value={draft.content}
          width="100%"
        />
        <div className="project-memory-form-grid">
          <TextInput
            isDisabled={disabled}
            isLabelHidden
            label={t("담당자")}
            onChange={(owner) => onChange({ ...draft, owner })}
            placeholder={t("담당자")}
            value={draft.owner}
            width="100%"
          />
          <DateInput
            hasClear
            isDisabled={disabled}
            isLabelHidden
            label={t("마감일")}
            onChange={(dueDate) => onChange({ ...draft, dueDate: dueDate ?? "" })}
            placeholder={t("마감일")}
            size="md"
            value={toISODateInputValue(draft.dueDate)}
          />
        </div>
      </>
    );
  }

  function renderAddForm(category: ProjectMemoryCategory) {
    const disabled = isAdding;

    return (
      <form
        aria-busy={disabled}
        className="project-memory-edit-form"
        onKeyDown={(event) => {
          if (event.key === "Escape" && !disabled) {
            event.preventDefault();
            event.stopPropagation();
            closeAddAndRestoreFocus();
          }
        }}
        onSubmit={(event) => void handleCreateMemory(category, event)}
      >
        {renderDraftFields(addDraft, setAddDraft, disabled)}
        <div className="project-memory-form-actions">
          <Button
            icon={<Save size={13} />}
            isDisabled={disabled || !addDraft.content.trim()}
            isLoading={disabled}
            label={t("저장")}
            type="submit"
            variant="primary"
          />
          <Button
            icon={<X size={13} />}
            isDisabled={disabled}
            label={t("취소")}
            onClick={closeAddAndRestoreFocus}
            variant="secondary"
          />
        </div>
      </form>
    );
  }

  function renderActionMeta(item: ProjectMemoryItem) {
    const parts = getActionMetaParts(item, t);
    const hasSuggestion = suggestedActionIds.has(item.id);

    if (parts.length === 0 && !hasSuggestion) {
      return null;
    }

    return (
      <div className="project-memory-action-meta project-memory-meta">
        {renderMetaParts(parts)}
        {parts.length > 0 && hasSuggestion ? <i>·</i> : null}
        {hasSuggestion ? (
          <Badge
            className="project-memory-suggestion-mark"
            label={t("완료 제안")}
            variant="warning"
          />
        ) : null}
      </div>
    );
  }

  function renderSuggestionInbox() {
    if (visibleMemorySuggestions.length === 0) {
      return null;
    }

    return (
      <section className="project-memory-suggestion-inbox" aria-label={t("메모리 제안")}>
        <div className="project-memory-suggestion-head">
          <h2>{t("제안 {count}건", { count: visibleMemorySuggestions.length })}</h2>
        </div>
        <div className="project-memory-suggestion-list">
          {visibleMemorySuggestions.map((suggestion) => {
            const resolving = resolvingSuggestionIds.includes(suggestion.id);
            const targetItem = memoryItemsById.get(suggestion.memory_id);
            const supersedingItem =
              suggestion.kind === "supersede"
                ? memoryItemsById.get(suggestion.evidence.superseding_memory_id)
                : null;

            return (
              <Card
                aria-busy={resolving}
                className="project-memory-suggestion-card"
                key={suggestion.id}
                padding={2}
              >
                <div className="project-memory-suggestion-copy">
                  {suggestion.kind === "complete_action" ? (
                    <>
                      <p className="project-memory-suggestion-title">
                        {t("PR #{number} “{title}”이 이 액션을 해결한 것으로 보입니다", {
                          number: suggestion.evidence.number,
                          title: formatSuggestionTitle(suggestion.evidence.title),
                        })}
                        {suggestion.confidence === "medium" ? (
                          <Badge
                            className="project-memory-suggestion-badge"
                            label={t("추정")}
                            variant="warning"
                          />
                        ) : null}
                        {resolving ? (
                          <Badge
                            className="project-memory-suggestion-badge"
                            label={t("처리 중")}
                            variant="info"
                          />
                        ) : null}
                      </p>
                      <p
                        className="project-memory-suggestion-action"
                        title={targetItem?.content ?? ""}
                      >
                        {targetItem?.content ?? t("대상 액션을 찾을 수 없습니다")}
                      </p>
                      <p className="project-memory-suggestion-rationale">
                        {suggestion.rationale}
                      </p>
                      {suggestion.evidence.url ? (
                        <a
                          className="project-memory-suggestion-link"
                          href={suggestion.evidence.url}
                          rel="noreferrer"
                          target="_blank"
                        >
                          {t("PR 링크")}
                        </a>
                      ) : null}
                    </>
                  ) : (
                    <>
                      <p className="project-memory-suggestion-title">
                        {t("기존 결정을 새 결정으로 대체할 것을 제안합니다")}
                        {suggestion.confidence === "medium" ? (
                          <Badge
                            className="project-memory-suggestion-badge"
                            label={t("추정")}
                            variant="warning"
                          />
                        ) : null}
                        {resolving ? (
                          <Badge
                            className="project-memory-suggestion-badge"
                            label={t("처리 중")}
                            variant="info"
                          />
                        ) : null}
                      </p>
                      <p
                        className="project-memory-suggestion-action"
                        title={targetItem?.content ?? ""}
                      >
                        {t("기존 결정 · {content}", {
                          content: targetItem?.content ?? t("기존 결정을 찾을 수 없습니다"),
                        })}
                      </p>
                      <p
                        className="project-memory-suggestion-action"
                        title={supersedingItem?.content ?? ""}
                      >
                        {t("새 결정 · {content}", {
                          content:
                            supersedingItem?.content ?? t("새 결정을 찾을 수 없습니다"),
                        })}
                      </p>
                      <p className="project-memory-suggestion-rationale">
                        {t("변경 근거 · {rationale}", { rationale: suggestion.rationale })}
                      </p>
                    </>
                  )}
                  <p
                    className="project-memory-suggestion-rationale"
                    data-consequence="true"
                  >
                    {t(
                      suggestion.kind === "complete_action"
                        ? "승인하면 이 액션을 완료 처리합니다."
                        : "승인하면 기존 결정을 새 결정으로 대체합니다.",
                    )}
                  </p>
                </div>
                <div className="project-memory-suggestion-actions">
                  <Button
                    className="project-memory-suggestion-accept"
                    isDisabled={
                      resolving ||
                      !canManage ||
                      (suggestion.kind === "supersede" && !supersedingItem)
                    }
                    label={t("승인")}
                    onClick={() => void handleResolveSuggestion(suggestion, "accept")}
                    size="sm"
                    variant="primary"
                  />
                  <Button
                    className="project-memory-suggestion-reject"
                    isDisabled={resolving || !canManage}
                    label={t("거절")}
                    onClick={() => void handleResolveSuggestion(suggestion, "reject")}
                    size="sm"
                    variant="secondary"
                  />
                </div>
              </Card>
            );
          })}
        </div>
      </section>
    );
  }

  function renderMemoryItem(item: ProjectMemoryItem, category: ProjectMemoryCategory) {
    const completed = isMemoryItemCompleted(item);
    const verified = isMemoryItemVerified(item);
    const meta = getMemoryItemMeta(item);
    const itemOperationPending = savingItemIds.includes(item.id);
    const interactionsDisabled = itemOperationPending || isReordering;
    const isEditing = editingItemId === item.id;
    const isAction = category === "action";
    const canDragAction = isAction && !completed && !isEditing && !itemOperationPending;
    const isConfirmingDelete = pendingDeleteId === item.id;

    if (isEditing) {
      return (
        <form
          aria-busy={itemOperationPending}
          className="project-memory-edit-form project-memory-manage-item"
          data-completed={completed}
          data-editing="true"
          key={item.id}
          onKeyDown={(event) => {
            if (event.key === "Escape" && !itemOperationPending) {
              event.preventDefault();
              event.stopPropagation();
              closeEditAndRestoreFocus();
            }
          }}
          onSubmit={(event) => void handleSaveEdit(item, event)}
        >
          {renderDraftFields(editDraft, setEditDraft, itemOperationPending)}
          <div className="project-memory-form-actions">
            <Button
              icon={<Save size={13} />}
              isDisabled={itemOperationPending || !editDraft.content.trim()}
              isLoading={itemOperationPending}
              label={t("저장")}
              type="submit"
              variant="primary"
            />
            <Button
              icon={<X size={13} />}
              isDisabled={itemOperationPending}
              label={t("취소")}
              onClick={closeEditAndRestoreFocus}
              variant="secondary"
            />
          </div>
        </form>
      );
    }

    return (
      <Fragment key={item.id}>
        <div
          aria-busy={itemOperationPending}
          className="project-memory-manage-item"
          data-action-drop-row={canDragAction ? "true" : undefined}
          data-action-id={canDragAction ? item.id : undefined}
          data-action={isAction ? "true" : undefined}
          data-bullet={!isAction ? "true" : undefined}
          data-completed={completed}
          data-draggable={canDragAction ? "true" : undefined}
          data-drag-over={dragOverActionId === item.id ? "true" : undefined}
          data-drag-placement={dragOverActionId === item.id ? dragOverPlacement ?? undefined : undefined}
          data-dragging={draggingActionId === item.id ? "true" : undefined}
        >
          {isAction ? (
            <CheckboxInput
              className="project-memory-check-circle"
              isDisabled={interactionsDisabled}
              isLabelHidden
              label={t("{content} 완료", { content: item.content })}
              onChange={() => void handleToggleCompleted(item)}
              size="sm"
              value={completed}
            />
          ) : (
            <span className="project-memory-bullet">·</span>
          )}
          <div className="project-memory-manage-copy">
            <p title={item.content}>{item.content}</p>
            <div className="project-memory-manage-meta">
              {isAction ? (
                renderActionMeta(item)
              ) : (
                <>
                  {verified ? <em data-verified="true">{t("✓ 검증됨")}</em> : null}
                  {verified && meta ? <i>·</i> : null}
                  {meta ? <span>{meta}</span> : null}
                </>
              )}
            </div>
          </div>
          <div className="project-memory-item-actions">
            {canDragAction ? (
              <button
                aria-keyshortcuts="ArrowUp ArrowDown Home End"
                aria-label={t("{content} 순서 변경", { content: item.content })}
                className="project-memory-drag-handle"
                disabled={isReordering}
                onKeyDown={(event) => handleActionReorderKeyDown(event, item)}
                onLostPointerCapture={handleActionPointerCancel}
                onPointerCancel={handleActionPointerCancel}
                onPointerDown={(event) => handleActionPointerDown(event, item)}
                onPointerMove={handleActionPointerMove}
                onPointerUp={handleActionPointerUp}
                title={t("드래그하거나 방향키로 순서 변경")}
                type="button"
              >
                <GripVertical size={13} />
              </button>
            ) : null}
            <IconButton
              id={getMemoryEditButtonId(apiProjectId, item.id)}
              icon={<Pencil size={13} />}
              isDisabled={interactionsDisabled || addingCategory !== null || editingItemId !== null}
              label={t("메모리 수정")}
              onClick={() => startEdit(item)}
              size="sm"
              tooltip={t("수정")}
              variant="ghost"
            />
            <IconButton
              aria-controls={getMemoryDeleteConfirmationId(apiProjectId, item.id)}
              aria-expanded={isConfirmingDelete}
              data-confirming={isConfirmingDelete ? "true" : undefined}
              id={getMemoryDeleteButtonId(apiProjectId, item.id)}
              icon={<Trash2 size={13} />}
              isDisabled={interactionsDisabled || isConfirmingDelete}
              isLoading={itemOperationPending}
              label={t(isConfirmingDelete ? "메모리 삭제 확인" : "메모리 삭제")}
              onClick={() => handleRequestDeleteMemory(item)}
              size="sm"
              tooltip={t(isConfirmingDelete ? "삭제 확인" : "삭제")}
              variant={isConfirmingDelete ? "destructive" : "ghost"}
            />
          </div>
        </div>
        {isConfirmingDelete ? (
          <Banner
            className="project-memory-delete-confirmation"
            container="card"
            description={
              <div style={{ display: "grid", gap: 8 }}>
                <span>
                  {t(
                    "“{content}”을 서버에서 영구 삭제합니다. 이 작업은 되돌릴 수 없습니다.",
                    { content: item.content },
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
                    label={t("취소")}
                    onClick={() => handleCancelDeleteMemory(item)}
                    size="sm"
                    variant="secondary"
                  />
                  <Button
                    isDisabled={itemOperationPending}
                    isLoading={itemOperationPending}
                    label={t("삭제")}
                    onClick={() => void handleConfirmDeleteMemory(item, category)}
                    size="sm"
                    variant="destructive"
                  />
                </div>
              </div>
            }
            id={getMemoryDeleteConfirmationId(apiProjectId, item.id)}
            onKeyDown={(event) => {
              if (event.key === "Escape" && !itemOperationPending) {
                event.preventDefault();
                event.stopPropagation();
                handleCancelDeleteMemory(item);
              }
            }}
            status="warning"
            title={t("메모리 삭제 확인")}
          />
        ) : null}
      </Fragment>
    );
  }

  function renderCompletedActionGroup() {
    if (completedActionItems.length === 0) {
      return null;
    }

    const isRetryingPartialDelete =
      completedActionDeleteResult !== null &&
      completedActionDeleteResult.remainingCount === completedActionItems.length;
    const deleteLabel = isRetryingPartialDelete
      ? t("남은 {count}개 다시 삭제", { count: completedActionItems.length })
      : pendingCompletedActionDelete
        ? t("완료된 액션 {count}개를 삭제합니다 — 되돌릴 수 없음", {
            count: completedActionItems.length,
          })
        : t("완료 항목 모두 삭제");

    return (
      <div
        aria-busy={isDeletingCompletedActions}
        className="project-memory-completed-group"
        data-open={showCompletedActions ? "true" : undefined}
      >
        <Button
          aria-expanded={showCompletedActions}
          className="project-memory-completed-toggle"
          icon={<ChevronDown size={13} />}
          label={t("완료됨 {count}", { count: completedActionItems.length })}
          onClick={() => {
            setShowCompletedActions((current) => !current);
            setPendingCompletedActionDelete(false);
          }}
          size="sm"
          variant="ghost"
        />
        {showCompletedActions ? (
          <div className="project-memory-completed-body">
            <div
              className="project-memory-completed-actions"
              style={
                isRetryingPartialDelete
                  ? {
                      alignItems: "center",
                      flexWrap: "wrap",
                      gap: 8,
                      justifyContent: "space-between",
                    }
                  : undefined
              }
            >
              {isRetryingPartialDelete ? (
                <span className="project-memory-meta">
                  {t("{deleted}개 삭제 · {remaining}개 남음", {
                    deleted: completedActionDeleteResult.deletedCount,
                    remaining: completedActionDeleteResult.remainingCount,
                  })}
                </span>
              ) : null}
              <Button
                className="project-memory-completed-delete"
                data-confirming={pendingCompletedActionDelete ? "true" : undefined}
                icon={<Trash2 size={13} />}
                isDisabled={!showManageUi || isDeletingCompletedActions}
                isLoading={isDeletingCompletedActions}
                label={deleteLabel}
                onClick={() => void handleDeleteCompletedActions()}
                size="sm"
                variant="destructive"
              />
            </div>
            {completedActionItems.map((item) => renderMemoryItem(item, "action"))}
          </div>
        ) : null}
      </div>
    );
  }

  function renderManageSection(category: ProjectMemoryCategory) {
    const { label } = MEMORY_CATEGORY_META[category];
    const allItems = category === "action" ? actionTodoItems : groupedItems[category];
    const shouldLimitDecision = category === "decision" && !showAllDecisions;
    const items = shouldLimitDecision ? allItems.slice(0, MANAGE_DECISION_LIMIT) : allItems;
    const hiddenDecisionCount = Math.max(allItems.length - items.length, 0);
    const isActionSection = category === "action";
    const hasSectionItems = isActionSection ? groupedItems.action.length > 0 : allItems.length > 0;

    return (
      <article className="project-memory-manage-section" data-tone={category} key={category}>
        <div className="project-memory-manage-label">
          <h2 data-tone={category}>{t(label)}</h2>
          <small>
            {category === "action" && groupedItems.action.length > 0
              ? t("완료 {completed}/{total}", {
                  completed: actionCompletedCount,
                  total: groupedItems.action.length,
                })
              : groupedItems[category].length}
          </small>
          <span className="project-memory-label-spacer" />
          <Button
            id={getMemoryAddButtonId(apiProjectId, category)}
            isDisabled={isAdding || addingCategory !== null || editingItemId !== null || isReordering}
            label={t("＋ 추가")}
            onClick={() => startAdd(category)}
            size="sm"
            variant="ghost"
          />
        </div>
        {addingCategory === category ? renderAddForm(category) : null}
        <div className="project-memory-manage-list">
          {!hasSectionItems ? (
            <p className="project-memory-empty-row">{t(MEMORY_CATEGORY_META[category].empty)}</p>
          ) : (
            <>
              {items.map((item) => renderMemoryItem(item, category))}
              {isActionSection ? renderCompletedActionGroup() : null}
            </>
          )}
        </div>
        {category === "decision" && (hiddenDecisionCount > 0 || showAllDecisions) ? (
          <Button
            className="project-memory-more-button"
            label={
              showAllDecisions
                ? t("접기")
                : t("외 {count}개 모두 보기", { count: hiddenDecisionCount })
            }
            onClick={() => setShowAllDecisions((current) => !current)}
            size="sm"
            variant="ghost"
          />
        ) : null}
      </article>
    );
  }

  function renderStatsStrip() {
    return (
      <div className="project-memory-stats" aria-label={t("프로젝트 메모리 요약")}>
        {MEMORY_CATEGORIES.map((category) => (
          <div className="project-memory-stat" data-tone={category} key={category}>
            <strong>{groupedItems[category].length}</strong>
            <span>{t(MEMORY_CATEGORY_META[category].label)}</span>
            {category === "action" ? (
              <ProgressBar
                className="project-memory-action-progress"
                isLabelHidden
                label={t("완료 {completed}/{total}", {
                  completed: actionCompletedCount,
                  total: groupedItems.action.length,
                })}
                max={groupedItems.action.length || 1}
                value={actionCompletedCount}
                variant="accent"
              />
            ) : null}
          </div>
        ))}
      </div>
    );
  }

  return (
    <div
      className="project-panel-content project-memory"
      data-mode={showManageUi ? "manage" : "summary"}
      ref={panelRef}
    >
      <div className="project-memory-header">
        <div className="project-memory-heading">
          <p className="project-panel-project-name">{project.name}</p>
          <p className="project-memory-description">
            {typeof apiProjectId === "number"
              ? t("서버 분석 결과로 저장된 프로젝트 메모리를 표시합니다")
              : t("FastAPI 프로젝트 연결 후 메모리를 표시합니다")}
          </p>
          {!showManageUi ? renderStatsStrip() : null}
        </div>
      </div>
      {operationError ? (
        <p className="project-memory-operation-error" role="alert">
          {operationError}
        </p>
      ) : null}
      {operationStatus ? (
        <p
          aria-atomic="true"
          aria-live="polite"
          className="project-memory-operation-status"
          data-state={operationStatus.state}
          role="status"
        >
          {operationStatus.state === "progress" ? (
            <LoaderCircle aria-hidden="true" size={14} />
          ) : (
            <Check aria-hidden="true" size={14} />
          )}
          <span>{operationStatus.message}</span>
        </p>
      ) : null}
      {renderSuggestionInbox()}

      {typeof apiProjectId !== "number" ? (
        <EmptyState
          className="project-memory-server-state"
          isCompact
          title={t("서버 프로젝트가 연결되면 메모리를 불러옵니다.")}
        />
      ) : loadState === "loading" ? (
        <EmptyState
          className="project-memory-server-state"
          isCompact
          title={t("서버에서 프로젝트 메모리를 불러오는 중입니다.")}
        />
      ) : loadState === "error" ? (
        <EmptyState
          actions={
            <Button
              label={t("다시 시도")}
              onClick={() => void loadProjectMemory()}
              size="sm"
              variant="secondary"
            />
          }
          className="project-memory-server-state"
          isCompact
          title={errorMessage}
        />
      ) : totalCount === 0 && !showManageUi ? (
        <EmptyState
          className="project-memory-server-state"
          isCompact
          title={t("서버에 저장된 프로젝트 메모리가 없습니다.")}
        />
      ) : showManageUi ? (
        <>
          {renderStatsStrip()}

          <section
            aria-busy={isReordering}
            aria-label={t("프로젝트 메모리")}
            className="project-memory-manage"
          >
            <div className="project-memory-manage-column">
              {renderManageSection("action")}
              {renderManageSection("issue")}
              {renderManageSection("risk")}
            </div>
            <div className="project-memory-manage-column">
              {renderManageSection("decision")}
            </div>
          </section>
          {dragPreview ? (
            <div
              className="project-memory-drag-preview"
              style={{ left: dragPreview.x + 12, top: dragPreview.y + 12 }}
            >
              {dragPreview.content}
            </div>
          ) : null}
        </>
      ) : (
        <div className="project-memory-summary-body">
          <section
            className="project-memory-summary-section"
            data-tone="action"
            aria-label={t("프로젝트 액션")}
          >
            <div className="project-memory-section-head">
              <h2 data-tone="action">{t("Action")}</h2>
              <span className="project-memory-label-spacer" />
              <small>
                {groupedItems.action.length > 0
                  ? t("완료 {completed}/{total}", {
                      completed: actionCompletedCount,
                      total: groupedItems.action.length,
                    })
                  : groupedItems.action.length}
              </small>
            </div>
            <div className="project-memory-summary-actions">
              {actionItems.slice(0, SUMMARY_ITEM_LIMIT).map((item) => (
                <div
                  className="project-memory-summary-action"
                  data-completed={isMemoryItemCompleted(item)}
                  key={item.id}
                >
                  {canManage && typeof apiProjectId === "number" ? (
                    <CheckboxInput
                      className="project-memory-check-circle"
                      isDisabled={isItemSaving(item.id)}
                      isLabelHidden
                      label={t("{content} 완료", { content: item.content })}
                      onChange={() => void handleToggleCompleted(item)}
                      size="sm"
                      value={isMemoryItemCompleted(item)}
                    />
                  ) : (
                    <span className="project-memory-check-circle" aria-hidden="true" />
                  )}
                  <span className="project-memory-summary-content" title={item.content}>
                    {item.content}
                  </span>
                  {renderActionMeta(item)}
                </div>
              ))}
              {groupedItems.action.length === 0 ? (
                <p className="project-memory-empty-row">{t(MEMORY_CATEGORY_META.action.empty)}</p>
              ) : null}
              {actionItems.length > SUMMARY_ITEM_LIMIT ? (
                <p className="project-memory-summary-more">
                  {t("외 {count}개", { count: actionItems.length - SUMMARY_ITEM_LIMIT })}
                </p>
              ) : null}
            </div>
          </section>

          <section className="project-memory-summary-rest" aria-label={t("프로젝트 메모")}>
            {(["decision", "issue", "risk"] as const).map((category) => {
              const { label } = MEMORY_CATEGORY_META[category];

              return (
                <article
                  className="project-memory-summary-section"
                  data-tone={category}
                  key={category}
                >
                  <div className="project-memory-section-head">
                    <h2 data-tone={category}>{t(label)}</h2>
                    <span className="project-memory-label-spacer" />
                    <small>{groupedItems[category].length}</small>
                  </div>
                  <MemoryItemRows
                    category={category}
                    items={groupedItems[category]}
                    limit={2}
                    variant="summary"
                  />
                </article>
              );
            })}
          </section>
        </div>
      )}
    </div>
  );
}
