export const PENDING_DOCUMENT_DELETE_STORAGE_SUFFIX = ".pending-document-deletes.v1";
export const PENDING_DOCUMENT_DELETE_RETRY_DELAYS_MS = [
  1_000,
  5_000,
  30_000,
  120_000,
  300_000,
] as const;

export type PendingDocumentDeleteTarget = {
  apiProjectId: number;
  docId: number;
};

export type PendingDocumentDelete = PendingDocumentDeleteTarget & {
  attempts: number;
  createdAt: number;
  nextAttemptAt: number | null;
};

export type PendingDocumentDeleteStorage = {
  getItem: (key: string) => string | null;
  removeItem: (key: string) => void;
  setItem: (key: string, value: string) => void;
};

export type PendingDocumentDeleteErrorAction = "complete" | "pause" | "retry";

export type PendingDocumentDeleteAttemptResult =
  | {
      entry: PendingDocumentDelete;
      outcome: "completed";
      reason: "deleted" | "not-found";
    }
  | {
      entry: PendingDocumentDelete;
      error: unknown;
      outcome: "paused";
    }
  | {
      entry: PendingDocumentDelete;
      error: unknown;
      outcome: "retry-scheduled";
    }
  | {
      entry?: PendingDocumentDelete;
      outcome: "skipped";
      reason: "missing" | "not-due" | "paused";
    };

type StoredPendingDocumentDeletes = {
  entries: PendingDocumentDelete[];
  version: 1;
};

type PendingDocumentDeleteQueueOptions = {
  classifyError?: (error: unknown) => PendingDocumentDeleteErrorAction;
  deleteDocument: (target: PendingDocumentDeleteTarget) => Promise<void>;
  now?: () => number;
  onPersistenceError?: (error: unknown) => void;
  retryDelaysMs?: readonly number[];
  storage: PendingDocumentDeleteStorage;
  storageKey: string;
};

export type PendingDocumentDeleteQueue = {
  enqueue: (
    target: PendingDocumentDeleteTarget,
  ) => Promise<PendingDocumentDeleteAttemptResult>;
  flush: (options?: { force?: boolean }) => Promise<PendingDocumentDeleteAttemptResult[]>;
  forget: (target: PendingDocumentDeleteTarget) => boolean;
  has: (target: PendingDocumentDeleteTarget) => boolean;
  list: () => PendingDocumentDelete[];
  nextRetryAt: () => number | null;
  size: () => number;
};

export function getPendingDocumentDeletesStorageKey(projectStorageKey: string) {
  return `${projectStorageKey}${PENDING_DOCUMENT_DELETE_STORAGE_SUFFIX}`;
}

export function getPendingDocumentDeleteKey(target: PendingDocumentDeleteTarget) {
  return `${target.apiProjectId}:${target.docId}`;
}

function isPositiveSafeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function parsePendingDocumentDelete(value: unknown): PendingDocumentDelete | null {
  if (!value || typeof value !== "object") {
    return null;
  }

  const candidate = value as Partial<PendingDocumentDelete>;
  if (
    !isPositiveSafeInteger(candidate.apiProjectId) ||
    !isPositiveSafeInteger(candidate.docId) ||
    typeof candidate.attempts !== "number" ||
    !Number.isSafeInteger(candidate.attempts) ||
    candidate.attempts < 0 ||
    typeof candidate.createdAt !== "number" ||
    !Number.isFinite(candidate.createdAt) ||
    candidate.createdAt < 0 ||
    !(
      candidate.nextAttemptAt === null ||
      (typeof candidate.nextAttemptAt === "number" &&
        Number.isFinite(candidate.nextAttemptAt) &&
        candidate.nextAttemptAt >= 0)
    )
  ) {
    return null;
  }

  return {
    apiProjectId: candidate.apiProjectId,
    attempts: candidate.attempts,
    createdAt: candidate.createdAt,
    docId: candidate.docId,
    nextAttemptAt: candidate.nextAttemptAt,
  };
}

export function loadPendingDocumentDeletes(
  storage: Pick<PendingDocumentDeleteStorage, "getItem">,
  storageKey: string,
) {
  try {
    const raw = storage.getItem(storageKey);
    if (!raw) {
      return [];
    }

    const stored = JSON.parse(raw) as Partial<StoredPendingDocumentDeletes>;
    if (stored.version !== 1 || !Array.isArray(stored.entries)) {
      return [];
    }

    const entriesByKey = new Map<string, PendingDocumentDelete>();
    stored.entries.forEach((value) => {
      const entry = parsePendingDocumentDelete(value);
      if (entry) {
        entriesByKey.set(getPendingDocumentDeleteKey(entry), entry);
      }
    });
    return Array.from(entriesByKey.values());
  } catch {
    return [];
  }
}

export function persistPendingDocumentDeletes(
  storage: Pick<PendingDocumentDeleteStorage, "removeItem" | "setItem">,
  storageKey: string,
  entries: readonly PendingDocumentDelete[],
) {
  if (entries.length === 0) {
    storage.removeItem(storageKey);
    return;
  }

  const stored: StoredPendingDocumentDeletes = {
    entries: [...entries],
    version: 1,
  };
  storage.setItem(storageKey, JSON.stringify(stored));
}

function getErrorStatus(error: unknown) {
  if (!error || typeof error !== "object" || !("status" in error)) {
    return undefined;
  }

  const status = (error as { status?: unknown }).status;
  return typeof status === "number" && Number.isFinite(status) ? status : undefined;
}

export function classifyPendingDocumentDeleteError(
  error: unknown,
): PendingDocumentDeleteErrorAction {
  const status = getErrorStatus(error);
  if (status === 404) {
    return "complete";
  }
  if (
    status === undefined ||
    status === 408 ||
    status === 425 ||
    status === 429 ||
    status >= 500
  ) {
    return "retry";
  }
  return "pause";
}

function normalizeRetryDelays(delays: readonly number[]) {
  const normalized = delays.filter(
    (delay) => typeof delay === "number" && Number.isFinite(delay) && delay >= 0,
  );
  return normalized.length > 0
    ? normalized
    : [...PENDING_DOCUMENT_DELETE_RETRY_DELAYS_MS];
}

function assertValidTarget(target: PendingDocumentDeleteTarget) {
  if (!isPositiveSafeInteger(target.apiProjectId) || !isPositiveSafeInteger(target.docId)) {
    throw new TypeError("apiProjectId와 docId는 양의 정수여야 합니다");
  }
}

export function createPendingDocumentDeleteQueue({
  classifyError = classifyPendingDocumentDeleteError,
  deleteDocument,
  now = Date.now,
  onPersistenceError,
  retryDelaysMs = PENDING_DOCUMENT_DELETE_RETRY_DELAYS_MS,
  storage,
  storageKey,
}: PendingDocumentDeleteQueueOptions): PendingDocumentDeleteQueue {
  const delays = normalizeRetryDelays(retryDelaysMs);
  const entries = new Map(
    loadPendingDocumentDeletes(storage, storageKey).map((entry) => [
      getPendingDocumentDeleteKey(entry),
      entry,
    ]),
  );
  const inFlight = new Map<string, Promise<PendingDocumentDeleteAttemptResult>>();

  function list() {
    return Array.from(entries.values()).sort(
      (left, right) =>
        left.createdAt - right.createdAt ||
        left.apiProjectId - right.apiProjectId ||
        left.docId - right.docId,
    );
  }

  function persist() {
    try {
      persistPendingDocumentDeletes(storage, storageKey, list());
    } catch (error) {
      try {
        onPersistenceError?.(error);
      } catch {
        // A notification failure must not prevent the best-effort server delete.
      }
    }
  }

  function complete(
    key: string,
    entry: PendingDocumentDelete,
    reason: "deleted" | "not-found",
  ): PendingDocumentDeleteAttemptResult {
    entries.delete(key);
    persist();
    return { entry, outcome: "completed", reason };
  }

  function attempt(
    key: string,
    force: boolean,
  ): Promise<PendingDocumentDeleteAttemptResult> {
    const activeAttempt = inFlight.get(key);
    if (activeAttempt) {
      return activeAttempt;
    }

    const entry = entries.get(key);
    if (!entry) {
      return Promise.resolve({ outcome: "skipped", reason: "missing" });
    }
    if (!force && entry.nextAttemptAt === null) {
      return Promise.resolve({ entry, outcome: "skipped", reason: "paused" });
    }
    if (!force && entry.nextAttemptAt !== null && entry.nextAttemptAt > now()) {
      return Promise.resolve({ entry, outcome: "skipped", reason: "not-due" });
    }

    const activePromise = (async (): Promise<PendingDocumentDeleteAttemptResult> => {
      try {
        await deleteDocument({
          apiProjectId: entry.apiProjectId,
          docId: entry.docId,
        });
        return complete(key, entry, "deleted");
      } catch (error) {
        let action: PendingDocumentDeleteErrorAction;
        try {
          action = classifyError(error);
        } catch {
          action = "pause";
        }

        if (action === "complete") {
          return complete(key, entry, "not-found");
        }

        const currentEntry = entries.get(key);
        if (!currentEntry) {
          return { outcome: "skipped", reason: "missing" };
        }

        const attempts = currentEntry.attempts + 1;
        const nextEntry: PendingDocumentDelete = {
          ...currentEntry,
          attempts,
          nextAttemptAt:
            action === "retry"
              ? now() + delays[Math.min(attempts - 1, delays.length - 1)]
              : null,
        };
        entries.set(key, nextEntry);
        persist();

        return action === "retry"
          ? { entry: nextEntry, error, outcome: "retry-scheduled" }
          : { entry: nextEntry, error, outcome: "paused" };
      }
    })();

    inFlight.set(key, activePromise);
    void activePromise.finally(() => {
      if (inFlight.get(key) === activePromise) {
        inFlight.delete(key);
      }
    });
    return activePromise;
  }

  return {
    enqueue(target) {
      assertValidTarget(target);
      const key = getPendingDocumentDeleteKey(target);
      const existingEntry = entries.get(key);

      if (!existingEntry) {
        entries.set(key, {
          ...target,
          attempts: 0,
          createdAt: now(),
          nextAttemptAt: now(),
        });
        // Write-ahead: the tombstone is persisted before deleteDocument can run.
        persist();
      } else if (existingEntry.nextAttemptAt === null && !inFlight.has(key)) {
        entries.set(key, { ...existingEntry, nextAttemptAt: now() });
        persist();
      }

      return attempt(key, true);
    },
    async flush(options) {
      const force = options?.force === true;
      const keys = Array.from(entries.entries())
        .filter(([, entry]) => {
          if (force) {
            return true;
          }
          return entry.nextAttemptAt !== null && entry.nextAttemptAt <= now();
        })
        .map(([key]) => key);
      return Promise.all(keys.map((key) => attempt(key, force)));
    },
    forget(target) {
      assertValidTarget(target);
      const deleted = entries.delete(getPendingDocumentDeleteKey(target));
      if (deleted) {
        persist();
      }
      return deleted;
    },
    has(target) {
      assertValidTarget(target);
      return entries.has(getPendingDocumentDeleteKey(target));
    },
    list,
    nextRetryAt() {
      let earliest: number | null = null;
      entries.forEach((entry, key) => {
        if (entry.nextAttemptAt === null || inFlight.has(key)) {
          return;
        }
        earliest =
          earliest === null ? entry.nextAttemptAt : Math.min(earliest, entry.nextAttemptAt);
      });
      return earliest;
    },
    size() {
      return entries.size;
    },
  };
}
