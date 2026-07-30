import assert from "node:assert/strict";
import test from "node:test";

import {
  classifyPendingDocumentDeleteError,
  createPendingDocumentDeleteQueue,
  getPendingDocumentDeletesStorageKey,
  loadPendingDocumentDeletes,
  persistPendingDocumentDeletes,
} from "../src/pendingDocumentDeletes.ts";

class MemoryStorage {
  values = new Map();
  writes = [];

  getItem(key) {
    return this.values.get(key) ?? null;
  }

  removeItem(key) {
    this.writes.push({ key, type: "remove" });
    this.values.delete(key);
  }

  setItem(key, value) {
    this.writes.push({ key, type: "set", value });
    this.values.set(key, value);
  }
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, reject, resolve };
}

test("storage key inherits the existing account and server scope", () => {
  const accountKey = getPendingDocumentDeletesStorageKey(
    "paim.projects.v8.account.server%7C42%7Cuser%40example.com",
  );
  const otherAccountKey = getPendingDocumentDeletesStorageKey(
    "paim.projects.v8.account.server%7C99%7Cother%40example.com",
  );

  assert.equal(
    accountKey,
    "paim.projects.v8.account.server%7C42%7Cuser%40example.com.pending-document-deletes.v1",
  );
  assert.notEqual(accountKey, otherAccountKey);
});

test("enqueue persists a tombstone before invoking DELETE and completes on success", async () => {
  const storage = new MemoryStorage();
  const storageKey = "pending";
  let sawWriteAheadTombstone = false;
  const queue = createPendingDocumentDeleteQueue({
    storage,
    storageKey,
    deleteDocument: async ({ apiProjectId, docId }) => {
      const stored = loadPendingDocumentDeletes(storage, storageKey);
      sawWriteAheadTombstone = stored.some(
        (entry) => entry.apiProjectId === apiProjectId && entry.docId === docId,
      );
    },
    now: () => 100,
  });

  const result = await queue.enqueue({ apiProjectId: 7, docId: 81 });

  assert.equal(sawWriteAheadTombstone, true);
  assert.deepEqual(result, {
    entry: {
      apiProjectId: 7,
      attempts: 0,
      createdAt: 100,
      docId: 81,
      nextAttemptAt: 100,
    },
    outcome: "completed",
    reason: "deleted",
  });
  assert.equal(queue.size(), 0);
  assert.equal(storage.getItem(storageKey), null);
});

test("concurrent duplicate enqueues share one DELETE and one tombstone", async () => {
  const storage = new MemoryStorage();
  const request = deferred();
  let deleteCalls = 0;
  const queue = createPendingDocumentDeleteQueue({
    storage,
    storageKey: "pending",
    deleteDocument: async () => {
      deleteCalls += 1;
      await request.promise;
    },
    now: () => 200,
  });

  const first = queue.enqueue({ apiProjectId: 3, docId: 9 });
  const second = queue.enqueue({ apiProjectId: 3, docId: 9 });

  assert.strictEqual(first, second);
  assert.equal(deleteCalls, 1);
  assert.equal(queue.size(), 1);
  assert.equal(loadPendingDocumentDeletes(storage, "pending").length, 1);

  request.resolve();
  await Promise.all([first, second]);
  assert.equal(queue.size(), 0);
});

test("404 is idempotent completion and does not remain queued", async () => {
  const storage = new MemoryStorage();
  const queue = createPendingDocumentDeleteQueue({
    storage,
    storageKey: "pending",
    deleteDocument: async () => {
      throw { status: 404 };
    },
  });

  const result = await queue.enqueue({ apiProjectId: 2, docId: 4 });

  assert.equal(result.outcome, "completed");
  assert.equal(result.reason, "not-found");
  assert.equal(queue.size(), 0);
  assert.equal(storage.getItem("pending"), null);
});

test("transient failure survives restart and observes exponential backoff", async () => {
  const storage = new MemoryStorage();
  let now = 1_000;
  const firstQueue = createPendingDocumentDeleteQueue({
    storage,
    storageKey: "pending",
    deleteDocument: async () => {
      throw { status: 503 };
    },
    now: () => now,
    retryDelaysMs: [1_000, 5_000],
  });

  const failed = await firstQueue.enqueue({ apiProjectId: 5, docId: 12 });
  assert.equal(failed.outcome, "retry-scheduled");
  assert.deepEqual(firstQueue.list(), [
    {
      apiProjectId: 5,
      attempts: 1,
      createdAt: 1_000,
      docId: 12,
      nextAttemptAt: 2_000,
    },
  ]);

  let resumedDeleteCalls = 0;
  const resumedQueue = createPendingDocumentDeleteQueue({
    storage,
    storageKey: "pending",
    deleteDocument: async () => {
      resumedDeleteCalls += 1;
      if (resumedDeleteCalls === 1) {
        throw { status: 503 };
      }
    },
    now: () => now,
    retryDelaysMs: [1_000, 5_000],
  });

  assert.equal(resumedQueue.nextRetryAt(), 2_000);
  assert.deepEqual(await resumedQueue.flush(), []);
  assert.equal(resumedDeleteCalls, 0);

  now = 2_000;
  const failedAgain = await resumedQueue.flush();
  assert.equal(resumedDeleteCalls, 1);
  assert.equal(failedAgain[0]?.outcome, "retry-scheduled");
  assert.equal(resumedQueue.nextRetryAt(), 7_000);

  now = 6_999;
  assert.deepEqual(await resumedQueue.flush(), []);
  now = 7_000;
  const resumed = await resumedQueue.flush();
  assert.equal(resumedDeleteCalls, 2);
  assert.equal(resumed[0]?.outcome, "completed");
  assert.equal(resumedQueue.size(), 0);
});

test("non-retryable authorization failures pause until a forced flush", async () => {
  const storage = new MemoryStorage();
  let calls = 0;
  const queue = createPendingDocumentDeleteQueue({
    storage,
    storageKey: "pending",
    deleteDocument: async () => {
      calls += 1;
      if (calls === 1) {
        throw { status: 403 };
      }
    },
    now: () => 500,
  });

  const paused = await queue.enqueue({ apiProjectId: 8, docId: 13 });
  assert.equal(paused.outcome, "paused");
  assert.equal(queue.nextRetryAt(), null);
  assert.deepEqual(await queue.flush(), []);

  const resumed = await queue.flush({ force: true });
  assert.equal(calls, 2);
  assert.equal(resumed[0]?.outcome, "completed");
  assert.equal(queue.size(), 0);
});

test("restart parser ignores corrupt entries and deduplicates valid targets", () => {
  const storage = new MemoryStorage();
  const storageKey = "pending";
  const valid = {
    apiProjectId: 1,
    attempts: 2,
    createdAt: 10,
    docId: 2,
    nextAttemptAt: 20,
  };
  storage.setItem(
    storageKey,
    JSON.stringify({
      entries: [
        { ...valid, attempts: -1 },
        valid,
        { ...valid, attempts: 3, nextAttemptAt: 30 },
        { ...valid, docId: 0 },
      ],
      version: 1,
    }),
  );

  assert.deepEqual(loadPendingDocumentDeletes(storage, storageKey), [
    { ...valid, attempts: 3, nextAttemptAt: 30 },
  ]);

  storage.setItem(storageKey, "{not-json");
  assert.deepEqual(loadPendingDocumentDeletes(storage, storageKey), []);
});

test("persistence failure keeps the in-memory tombstone and still attempts DELETE", async () => {
  const storage = new MemoryStorage();
  storage.setItem = () => {
    throw new Error("quota exceeded");
  };
  let persistenceErrors = 0;
  let deleteCalls = 0;
  const request = deferred();
  const queue = createPendingDocumentDeleteQueue({
    storage,
    storageKey: "pending",
    deleteDocument: async () => {
      deleteCalls += 1;
      await request.promise;
    },
    onPersistenceError: () => {
      persistenceErrors += 1;
    },
  });

  const result = queue.enqueue({ apiProjectId: 1, docId: 3 });

  assert.equal(queue.has({ apiProjectId: 1, docId: 3 }), true);
  assert.equal(deleteCalls, 1);
  assert.equal(persistenceErrors, 1);

  request.resolve();
  await result;
});

test("default error classification retries only transient failures", () => {
  assert.equal(classifyPendingDocumentDeleteError(new TypeError("offline")), "retry");
  assert.equal(classifyPendingDocumentDeleteError({ status: 408 }), "retry");
  assert.equal(classifyPendingDocumentDeleteError({ status: 429 }), "retry");
  assert.equal(classifyPendingDocumentDeleteError({ status: 500 }), "retry");
  assert.equal(classifyPendingDocumentDeleteError({ status: 404 }), "complete");
  assert.equal(classifyPendingDocumentDeleteError({ status: 401 }), "pause");
  assert.equal(classifyPendingDocumentDeleteError({ status: 403 }), "pause");
  assert.equal(classifyPendingDocumentDeleteError({ status: 400 }), "pause");
});

test("standalone persistence round-trips the versioned format", () => {
  const storage = new MemoryStorage();
  const entries = [
    {
      apiProjectId: 10,
      attempts: 0,
      createdAt: 1,
      docId: 20,
      nextAttemptAt: null,
    },
  ];

  persistPendingDocumentDeletes(storage, "pending", entries);
  assert.deepEqual(loadPendingDocumentDeletes(storage, "pending"), entries);
});
