import type { Attachment, ProjectDocumentStatus } from "./types";

export type ServerDocumentAttachment = Attachment & {
  docId: number;
  documentStatus: ProjectDocumentStatus;
  documentType: string | null;
};

function isDocumentId(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isMeetingAttachment(attachment: Attachment) {
  return attachment.documentType?.trim().toLowerCase() === "meeting";
}

function withoutStaleStatusDetails(attachment: Attachment): Attachment {
  const {
    extracted: _extracted,
    lastError: _lastError,
    processingProgressDone: _processingProgressDone,
    processingProgressTotal: _processingProgressTotal,
    ...current
  } = attachment;

  return current;
}

function mergeServerDocument(
  attachment: Attachment,
  serverDocument: ServerDocumentAttachment,
): Attachment {
  const current =
    attachment.documentStatus === serverDocument.documentStatus
      ? attachment
      : withoutStaleStatusDetails(attachment);

  return {
    ...current,
    uploadName: serverDocument.uploadName ?? serverDocument.name,
    documentStatus: serverDocument.documentStatus,
    documentType: serverDocument.documentType ?? attachment.documentType ?? null,
  };
}

/**
 * Reconcile the saved local attachment tree with one authoritative server snapshot.
 *
 * Local files remain useful even when their old server document no longer exists, so
 * only missing `serverOnly` entries are removed. Tombstones are stronger: they hide a
 * document everywhere until its server-side delete has been observed.
 */
export function reconcileProjectDocumentAttachments(
  attachments: readonly Attachment[],
  serverDocuments: readonly ServerDocumentAttachment[],
  tombstonedDocumentIds: ReadonlySet<number> = new Set<number>(),
): Attachment[] {
  const serverDocumentsById = new Map<number, ServerDocumentAttachment>();

  serverDocuments.forEach((document) => {
    if (
      isDocumentId(document.docId) &&
      !tombstonedDocumentIds.has(document.docId)
    ) {
      serverDocumentsById.set(document.docId, document);
    }
  });

  const visibleServerDocuments = [...serverDocumentsById.values()];
  const matchedDocumentIds = new Set<number>();

  const reconcileTree = (entries: readonly Attachment[]): Attachment[] =>
    entries.flatMap((attachment) => {
      const docId = attachment.docId;

      if (isDocumentId(docId) && tombstonedDocumentIds.has(docId)) {
        return [];
      }

      const serverDocument = isDocumentId(docId)
        ? serverDocumentsById.get(docId)
        : undefined;

      if (attachment.serverOnly && isDocumentId(docId) && !serverDocument) {
        return [];
      }

      const children = attachment.children
        ? reconcileTree(attachment.children)
        : undefined;
      let reconciled = serverDocument
        ? mergeServerDocument(attachment, serverDocument)
        : attachment;

      if (serverDocument) {
        matchedDocumentIds.add(serverDocument.docId);
      }

      if (attachment.children && children !== attachment.children) {
        reconciled = { ...reconciled, children };
      }

      return [reconciled];
    });

  const reconciledAttachments = reconcileTree(attachments);
  const missingServerAttachments = visibleServerDocuments
    .filter((document) => !matchedDocumentIds.has(document.docId))
    .map((document) => ({ ...document, serverOnly: true }));

  return [...missingServerAttachments, ...reconciledAttachments];
}

/**
 * A list response only carries coarse status. Completed meeting documents need one
 * detail request after restart to restore their extraction counts (including zero).
 */
export function needsProjectDocumentStatusHydration(attachment: Attachment) {
  return (
    isDocumentId(attachment.docId) &&
    isMeetingAttachment(attachment) &&
    (attachment.documentStatus === "indexed" ||
      attachment.documentStatus === "failed") &&
    attachment.extracted === undefined
  );
}

/**
 * Once a meeting generation is indexed, discard only strictly older generations with
 * the same name. A newer upload may already be processing and a local entry may not
 * have received its document ID yet; neither is safe to remove.
 */
export function removeOlderMeetingDocumentGenerations(
  attachments: readonly Attachment[],
  completedAttachment: Attachment,
): Attachment[] {
  const completedDocId = completedAttachment.docId;

  if (
    !isDocumentId(completedDocId) ||
    !isMeetingAttachment(completedAttachment) ||
    completedAttachment.documentStatus !== "indexed"
  ) {
    return attachments as Attachment[];
  }

  const pruneTree = (entries: readonly Attachment[]): Attachment[] =>
    entries.flatMap((attachment) => {
      const docId = attachment.docId;
      const isOlderGeneration =
        isDocumentId(docId) &&
        docId < completedDocId &&
        isMeetingAttachment(attachment) &&
        attachment.name === completedAttachment.name;

      if (isOlderGeneration) {
        return [];
      }

      if (!attachment.children) {
        return [attachment];
      }

      const children = pruneTree(attachment.children);
      return children.length === attachment.children.length &&
        children.every((child, index) => child === attachment.children?.[index])
        ? [attachment]
        : [{ ...attachment, children }];
    });

  return pruneTree(attachments);
}
