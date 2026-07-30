import assert from "node:assert/strict";
import test from "node:test";

import {
  needsProjectDocumentStatusHydration,
  reconcileProjectDocumentAttachments,
  removeOlderMeetingDocumentGenerations,
} from "../src/projectDocumentSync.ts";

function serverDocument(
  docId,
  name,
  documentStatus = "processing",
  documentType = "document",
) {
  return {
    id: `server-${docId}`,
    name,
    path: `server-document://${docId}/${name}`,
    kind: "file",
    docId,
    documentStatus,
    documentType,
    serverOnly: true,
  };
}

test("server reconciliation prunes missing server-only roots and children but preserves local entries", () => {
  const localWithoutDocument = {
    id: "local-only",
    name: "notes.md",
    path: "/workspace/notes.md",
    kind: "file",
  };
  const localWithMissingDocument = {
    id: "local-with-old-link",
    name: "still-on-disk.md",
    path: "/workspace/still-on-disk.md",
    kind: "file",
    docId: 90,
    documentStatus: "indexed",
  };
  const serverOnlyWithoutDocumentId = {
    id: "pending-server-entry",
    name: "pending.mp3",
    path: "",
    kind: "file",
    serverOnly: true,
    documentStatus: "uploading",
  };
  const directory = {
    id: "folder",
    name: "folder",
    path: "/workspace/folder",
    kind: "directory",
    children: [
      serverDocument(2, "missing-child.md", "indexed"),
      {
        id: "local-child",
        name: "draft.md",
        path: "/workspace/folder/draft.md",
        kind: "file",
      },
    ],
  };
  const input = [
    serverDocument(1, "missing-root.md", "indexed"),
    localWithoutDocument,
    localWithMissingDocument,
    serverOnlyWithoutDocumentId,
    directory,
  ];

  const result = reconcileProjectDocumentAttachments(input, []);

  assert.deepEqual(
    result.map((attachment) => attachment.id),
    ["local-only", "local-with-old-link", "pending-server-entry", "folder"],
  );
  assert.equal(result[0], localWithoutDocument);
  assert.equal(result[1], localWithMissingDocument);
  assert.equal(result[2], serverOnlyWithoutDocumentId);
  assert.deepEqual(result[3].children, [directory.children[1]]);
  assert.equal(input[4].children.length, 2, "input tree must not be mutated");
});

test("server reconciliation merges authoritative fields and clears detail only when status changes", () => {
  const changed = {
    id: "local-10",
    name: "old-name.mp3",
    uploadName: "old-name.mp3",
    path: "/workspace/old-name.mp3",
    kind: "file",
    docId: 10,
    documentType: "audio",
    documentStatus: "delayed",
    extracted: { action: 4 },
    lastError: "stale timeout",
    processingProgressDone: 2,
    processingProgressTotal: 9,
  };
  const unchanged = {
    id: "local-11",
    name: "old-label.mp3",
    path: "/workspace/old-label.mp3",
    kind: "file",
    docId: 11,
    documentType: "audio",
    documentStatus: "indexed",
    extracted: { action: 0, decision: 1 },
    lastError: "detail to retain",
    processingProgressDone: 9,
    processingProgressTotal: 9,
  };

  const result = reconcileProjectDocumentAttachments(
    [changed, { id: "folder", name: "folder", path: "/folder", kind: "directory", children: [unchanged] }],
    [
      serverDocument(10, "renamed.mp3", "processing", "meeting"),
      serverDocument(11, "canonical.mp3", "indexed", "meeting"),
    ],
  );
  const mergedChanged = result[0];
  const mergedUnchanged = result[1].children[0];

  assert.equal(mergedChanged.id, changed.id);
  assert.equal(mergedChanged.path, changed.path);
  assert.equal(mergedChanged.name, "old-name.mp3");
  assert.equal(mergedChanged.uploadName, "renamed.mp3");
  assert.equal(mergedChanged.documentType, "meeting");
  assert.equal(mergedChanged.documentStatus, "processing");
  assert.equal(Object.hasOwn(mergedChanged, "lastError"), false);
  assert.equal(Object.hasOwn(mergedChanged, "processingProgressDone"), false);
  assert.equal(Object.hasOwn(mergedChanged, "processingProgressTotal"), false);
  assert.equal(Object.hasOwn(mergedChanged, "extracted"), false);

  assert.equal(mergedUnchanged.name, "old-label.mp3");
  assert.equal(mergedUnchanged.uploadName, "canonical.mp3");
  assert.equal(mergedUnchanged.documentType, "meeting");
  assert.deepEqual(mergedUnchanged.extracted, { action: 0, decision: 1 });
  assert.equal(mergedUnchanged.lastError, "detail to retain");
  assert.equal(mergedUnchanged.processingProgressDone, 9);
  assert.equal(mergedUnchanged.processingProgressTotal, 9);
  assert.equal(changed.lastError, "stale timeout", "input objects must not be mutated");
});

test("tombstones win over the server snapshot and unmatched server documents are restored once", () => {
  const tombstonedRoot = {
    ...serverDocument(20, "cancelled.mp3", "processing", "meeting"),
    serverOnly: false,
  };
  const tombstonedChild = serverDocument(21, "cancelled-child.md", "processing");
  const folder = {
    id: "folder",
    name: "folder",
    path: "/folder",
    kind: "directory",
    children: [tombstonedChild],
  };

  const result = reconcileProjectDocumentAttachments(
    [tombstonedRoot, folder],
    [
      serverDocument(20, "cancelled.mp3", "processing", "meeting"),
      serverDocument(21, "cancelled-child.md", "processing"),
      serverDocument(22, "restored.md", "indexed"),
      serverDocument(22, "restored.md", "indexed"),
    ],
    new Set([20, 21]),
  );

  assert.deepEqual(
    result.map((attachment) => attachment.docId ?? attachment.id),
    [22, "folder"],
  );
  assert.equal(result[0].serverOnly, true);
  assert.deepEqual(result[1].children, []);
});

test("meeting status hydration is limited to server-backed indexed or failed entries without counts", () => {
  const base = {
    id: "meeting",
    name: "meeting.mp3",
    path: "",
    kind: "file",
    docId: 30,
    documentType: "meeting",
  };

  assert.equal(
    needsProjectDocumentStatusHydration({ ...base, documentStatus: "indexed" }),
    true,
  );
  assert.equal(
    needsProjectDocumentStatusHydration({ ...base, documentStatus: "failed" }),
    true,
  );
  assert.equal(
    needsProjectDocumentStatusHydration({
      ...base,
      documentStatus: "indexed",
      extracted: {},
    }),
    false,
  );
  assert.equal(
    needsProjectDocumentStatusHydration({ ...base, documentStatus: "processing" }),
    false,
  );
  assert.equal(
    needsProjectDocumentStatusHydration({ ...base, documentStatus: "delayed" }),
    false,
  );
  assert.equal(
    needsProjectDocumentStatusHydration({
      ...base,
      documentStatus: "indexed",
      documentType: "document",
    }),
    false,
  );
  assert.equal(
    needsProjectDocumentStatusHydration({
      ...base,
      documentStatus: "indexed",
      docId: undefined,
    }),
    false,
  );
});

test("completed meetings remove only strictly older same-name meeting generations at any depth", () => {
  const completed = {
    ...serverDocument(50, "weekly.mp3", "indexed", "meeting"),
    id: "completed",
  };
  const sameGeneration = { ...completed, id: "same-generation-copy" };
  const newerProcessing = {
    ...serverDocument(51, "weekly.mp3", "processing", "meeting"),
    id: "newer-processing",
  };
  const localPending = {
    id: "local-pending",
    name: "weekly.mp3",
    path: "/workspace/weekly.mp3",
    kind: "file",
    documentType: "meeting",
    documentStatus: "uploading",
  };
  const differentName = serverDocument(1, "other.mp3", "indexed", "meeting");
  const differentType = serverDocument(1, "weekly.mp3", "indexed", "document");
  const folder = {
    id: "folder",
    name: "folder",
    path: "/folder",
    kind: "directory",
    children: [
      serverDocument(49, "weekly.mp3", "failed", "meeting"),
      newerProcessing,
      localPending,
    ],
  };
  const input = [
    serverDocument(10, "weekly.mp3", "indexed", "meeting"),
    completed,
    sameGeneration,
    differentName,
    differentType,
    folder,
  ];

  const result = removeOlderMeetingDocumentGenerations(input, completed);

  assert.deepEqual(
    result.map((attachment) => attachment.id),
    ["completed", "same-generation-copy", "server-1", "server-1", "folder"],
  );
  assert.deepEqual(
    result.at(-1).children.map((attachment) => attachment.id),
    ["newer-processing", "local-pending"],
  );
  assert.equal(input.length, 6);
  assert.equal(input.at(-1).children.length, 3, "input tree must not be mutated");
});

test("failed, non-meeting, and ID-less completions never prune generations", () => {
  const attachments = [serverDocument(1, "weekly.mp3", "indexed", "meeting")];
  const failed = serverDocument(2, "weekly.mp3", "failed", "meeting");
  const nonMeeting = serverDocument(2, "weekly.mp3", "indexed", "document");
  const withoutId = {
    id: "local",
    name: "weekly.mp3",
    path: "",
    kind: "file",
    documentStatus: "indexed",
    documentType: "meeting",
  };

  assert.equal(removeOlderMeetingDocumentGenerations(attachments, failed), attachments);
  assert.equal(removeOlderMeetingDocumentGenerations(attachments, nonMeeting), attachments);
  assert.equal(removeOlderMeetingDocumentGenerations(attachments, withoutId), attachments);
});
