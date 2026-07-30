import {
  AudioLines,
  ArrowLeft,
  ChevronRight,
  Ellipsis,
  Folder,
  FolderOpen,
  LoaderCircle,
  RefreshCw,
  Search,
  Upload,
  X,
} from "lucide-react";
import { Badge, type BadgeVariant } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { BreadcrumbItem, Breadcrumbs } from "@astryxdesign/core/Breadcrumbs";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Center } from "@astryxdesign/core/Center";
import { ClickableCard } from "@astryxdesign/core/ClickableCard";
import { CodeBlock } from "@astryxdesign/core/CodeBlock";
import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Spinner } from "@astryxdesign/core/Spinner";
import { TextInput } from "@astryxdesign/core/TextInput";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";

import { useI18n } from "./i18n";
import {
  clampProjectFileTreeWidth,
  countProjectFileEntries,
  getProjectFileVisualMeta,
  MAX_PROJECT_FILE_TREE_WIDTH,
  MIN_PROJECT_FILE_TREE_WIDTH,
  type ProjectFileGroup,
  type ProjectFileVisualMeta,
} from "./projectFileUtils";
import { getExtractionTotal, isMeetingDocument } from "./stt";
import type {
  Attachment,
  DemoStatus,
  ProjectDocumentStatus,
  ProjectFilePreview,
  ProjectSourcesMode,
} from "./types";

const PROJECT_FILE_TREE_KEYBOARD_STEP = 10;
const PROJECT_FILE_TREE_KEYBOARD_LARGE_STEP = 50;

function getProjectSourceManageButtonId(sourceId: string) {
  return `project-source-manage-${sourceId}`;
}

type ProjectSourceCardProps = {
  children: ReactNode;
  isMeeting: boolean;
  label: string;
  onOpen: () => void;
};

function ProjectSourceCard({
  children,
  isMeeting,
  label,
  onOpen,
}: ProjectSourceCardProps) {
  if (isMeeting) {
    return (
      <Card
        aria-label={label}
        className="project-source-card"
        padding={2}
        role="group"
      >
        {children}
      </Card>
    );
  }

  return (
    <ClickableCard
      className="project-source-card"
      label={label}
      onClick={onOpen}
      padding={2}
    >
      {children}
    </ClickableCard>
  );
}

type ProjectFileTreeProps = {
  canManage: boolean;
  entries: Attachment[];
  loadingEntryIds: ReadonlySet<string>;
  level?: number;
  onDelete: (entry: Attachment) => void;
  onSelect: (entry: Attachment) => void;
  onToggle: (entry: Attachment) => void;
  reviewingDeleteEntryId?: string | null;
  selectedEntryId?: string;
};

type ProjectFilesPanelProps = {
  attachments: Attachment[];
  canManage: boolean;
  demoStatus: DemoStatus | null;
  filteredTreeFiles: Attachment[];
  groupedFiles: ProjectFileGroup[];
  isSelectedSourceFile: boolean;
  isMaximized: boolean;
  isImporting: boolean;
  isTreeCollapsed: boolean;
  loadingEntryIds: string[];
  mode: ProjectSourcesMode;
  onBackToLibrary: () => void;
  onClosePreview: () => void;
  onCancelImport: () => void;
  onOpenAudio: () => void;
  onOpenDirectory: () => void;
  onOpenFiles: () => void;
  onOpenSource: (source: Attachment) => void;
  onRefreshDocumentStatus: (source: Attachment) => void;
  onConfirmDelete: (source: Attachment) => Promise<boolean>;
  onQueryChange: (query: string) => void;
  onSelectFile: (entry: Attachment) => void;
  onToggleFile: (entry: Attachment) => void;
  onToggleTreeCollapsed: () => void;
  onTreeResizeStart: (event: PointerEvent<HTMLDivElement>) => void;
  onTreeWidthChange: (width: number) => void;
  preview: ProjectFilePreview | null;
  query: string;
  statusRevision: number;
  treeAttachments: Attachment[];
  treeFileCount: number;
  treeWidth: number;
};

function getProjectFileRootLabel(entries: Attachment[], multipleLocationsLabel: string) {
  if (entries.length === 0) {
    return "/";
  }

  return entries.length === 1 ? entries[0].name : multipleLocationsLabel;
}

function countLinkedProjectDocuments(entry: Attachment) {
  const linkedDocumentIds = new Set<number>();

  function collectLinkedDocuments(currentEntry: Attachment) {
    if (typeof currentEntry.docId === "number") {
      linkedDocumentIds.add(currentEntry.docId);
    }
    currentEntry.children?.forEach(collectLinkedDocuments);
  }

  collectLinkedDocuments(entry);
  return linkedDocumentIds.size;
}

function ProjectFileDeleteConfirmation({
  entry,
  isDeleting,
  onCancel,
  onConfirm,
}: {
  entry: Attachment;
  isDeleting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const { t } = useI18n();
  const entryKind = t(entry.kind === "directory" ? "폴더" : "파일");
  const linkedDocumentCount = countLinkedProjectDocuments(entry);

  return (
    <Banner
      className="project-file-delete-confirmation"
      container="card"
      description={
        <div style={{ display: "grid", gap: 4 }}>
          <span>
            {t(
              "PaiM의 로컬 파일 목록에서 이 {kind} 참조를 제거합니다. 디스크의 원본은 삭제하지 않습니다.",
              { kind: entryKind },
            )}
          </span>
          <span>
            {linkedDocumentCount > 0
              ? t(
                  "확인된 연결 서버 문서 {count}개를 삭제하며, 해당 문서에서 파생된 메모리가 변경되거나 사라질 수 있습니다.",
                  { count: linkedDocumentCount },
                )
              : t(
                  "연결 상태에 따라 서버 문서와 해당 문서에서 파생된 메모리가 변경되거나 사라질 수 있습니다.",
                )}
          </span>
          <strong>
            {t("서버에서 삭제된 문서와 파생 데이터는 PaiM에서 되돌릴 수 없습니다.")}
          </strong>
        </div>
      }
      endContent={
        <>
          <Button
            isDisabled={isDeleting}
            label={t("취소")}
            onClick={onCancel}
            size="sm"
            variant="ghost"
          />
          <Button
            isDisabled={isDeleting}
            isLoading={isDeleting}
            label={t("삭제")}
            onClick={onConfirm}
            size="sm"
            variant="destructive"
          />
        </>
      }
      id="project-file-delete-confirmation"
      onKeyDown={(event) => {
        if (event.key === "Escape" && !isDeleting) {
          event.preventDefault();
          event.stopPropagation();
          onCancel();
        }
      }}
      status="warning"
      title={t("{kind} “{name}” 삭제 확인", { kind: entryKind, name: entry.name })}
    />
  );
}

function getProjectDocumentStatusPriority(status?: ProjectDocumentStatus) {
  const priorities: Record<ProjectDocumentStatus, number> = {
    failed: 5,
    delayed: 4,
    uploading: 3,
    processing: 2,
    uploaded: 2,
    indexed: 1,
  };

  return status ? priorities[status] : 0;
}

function findProjectDocumentStatusSource(source: Attachment): Attachment | null {
  let currentSource = source.documentStatus ? source : null;

  for (const child of source.children ?? []) {
    const childSource = findProjectDocumentStatusSource(child);

    if (
      childSource &&
      getProjectDocumentStatusPriority(childSource.documentStatus) >
        getProjectDocumentStatusPriority(currentSource?.documentStatus)
    ) {
      currentSource = childSource;
    }
  }

  return currentSource;
}

function getProjectDocumentStatusMeta(
  source: Attachment,
): { label: string; title: string; variant: BadgeVariant } | null {
  const statusSource = findProjectDocumentStatusSource(source);

  if (!statusSource?.documentStatus) {
    return null;
  }

  if (statusSource.documentStatus === "uploading") {
    return { label: "업로드중", title: "서버로 업로드 중", variant: "yellow" };
  }

  if (statusSource.documentStatus === "uploaded" || statusSource.documentStatus === "processing") {
    return { label: "처리중", title: "서버에서 문서를 처리 중", variant: "yellow" };
  }

  if (statusSource.documentStatus === "indexed") {
    return { label: "완료", title: "서버 인덱싱 완료", variant: "green" };
  }

  if (statusSource.documentStatus === "delayed") {
    return {
      label: "처리 지연",
      title: statusSource.lastError ?? "처리 지연 — 나중에 다시 확인",
      variant: "neutral",
    };
  }

  return {
    label: "실패",
    title: statusSource.lastError ?? "문서 처리 실패",
    variant: "red",
  };
}

function getProjectFilePathSegments(path: string) {
  return path.split(/[\\/]+/).filter(Boolean).slice(-4);
}

function getProjectFilePreviewLanguage(name: string) {
  const lowerName = name.toLowerCase();
  const extension = lowerName.includes(".") ? lowerName.split(".").pop() : "";
  const languageByExtension: Record<string, string> = {
    css: "css",
    html: "html",
    js: "javascript",
    json: "json",
    jsx: "jsx",
    md: "markdown",
    py: "python",
    sh: "bash",
    svg: "svg",
    ts: "typescript",
    tsx: "tsx",
    xml: "xml",
    yaml: "yaml",
    yml: "yaml",
    zsh: "bash",
  };

  return languageByExtension[extension ?? ""] ?? "plaintext";
}

function hasVisibleProjectFileEntry(entries: Attachment[], entryId: string): boolean {
  return entries.some(
    (entry) =>
      entry.id === entryId ||
      (entry.kind === "directory" &&
        Boolean(entry.isExpanded) &&
        Boolean(entry.children && hasVisibleProjectFileEntry(entry.children, entryId))),
  );
}

// Codex 파일 패널처럼 폴더를 접고 펼칠 수 있는 프로젝트 파일 트리를 렌더링한다.
function ProjectFileTree({
  canManage,
  entries,
  loadingEntryIds,
  level = 0,
  onDelete,
  onSelect,
  onToggle,
  reviewingDeleteEntryId,
  selectedEntryId,
}: ProjectFileTreeProps) {
  const { t } = useI18n();

  function handleTreeItemKeyDown(
    event: KeyboardEvent<HTMLDivElement>,
    entry: Attachment,
    isDirectory: boolean,
    isExpanded: boolean,
  ) {
    if (event.target !== event.currentTarget) {
      return;
    }

    const rootTree = event.currentTarget.closest<HTMLElement>('[role="tree"]');
    const visibleItems = rootTree
      ? Array.from(rootTree.querySelectorAll<HTMLElement>('[role="treeitem"]')).filter(
          (item) => item.getClientRects().length > 0,
        )
      : [];
    const currentIndex = visibleItems.indexOf(event.currentTarget);

    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      const offset = event.key === "ArrowDown" ? 1 : -1;
      const nextItem = visibleItems[currentIndex + offset];
      if (nextItem) {
        event.preventDefault();
        nextItem.focus();
      }
      return;
    }

    if (event.key === "Home" || event.key === "End") {
      const nextItem =
        event.key === "Home" ? visibleItems[0] : visibleItems[visibleItems.length - 1];
      if (nextItem) {
        event.preventDefault();
        nextItem.focus();
      }
      return;
    }

    if (event.key === "ArrowRight" && isDirectory) {
      event.preventDefault();
      if (!isExpanded) {
        onToggle(entry);
      } else {
        event.currentTarget.parentElement
          ?.querySelector<HTMLElement>('[role="group"] [role="treeitem"]')
          ?.focus();
      }
      return;
    }

    if (event.key === "ArrowLeft" && isDirectory) {
      event.preventDefault();
      if (isExpanded) {
        onToggle(entry);
      } else {
        event.currentTarget.parentElement?.parentElement?.parentElement
          ?.querySelector<HTMLElement>(':scope > [role="treeitem"]')
          ?.focus();
      }
      return;
    }

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (isDirectory) {
        onToggle(entry);
      } else {
        onSelect(entry);
      }
      return;
    }

    if (event.key === "Delete" && canManage) {
      event.preventDefault();
      onDelete(entry);
    }
  }

  return (
    <div className="project-file-tree" role={level === 0 ? "tree" : "group"}>
      {entries.map((entry) => {
        const isDirectory = entry.kind === "directory";
        const isExpanded = Boolean(entry.isExpanded);
        const fileVisualMeta: ProjectFileVisualMeta = isDirectory
          ? { Icon: isExpanded ? FolderOpen : Folder, color: "var(--muted)" }
          : getProjectFileVisualMeta(entry.name);
        const ProjectFileIcon = fileVisualMeta.Icon;
        const isLoading = loadingEntryIds.has(entry.id);

        return (
          <div className="project-file-node" key={entry.id}>
            <div
              aria-expanded={isDirectory ? isExpanded : undefined}
              aria-busy={isLoading || undefined}
              aria-keyshortcuts={canManage ? "Delete" : undefined}
              className="project-file-row"
              data-kind={isDirectory ? "directory" : "file"}
              data-selected={entry.id === selectedEntryId ? "true" : undefined}
              aria-selected={!isDirectory ? entry.id === selectedEntryId : undefined}
              onClick={() => {
                if (isDirectory && !isLoading) {
                  onToggle(entry);
                } else {
                  onSelect(entry);
                }
              }}
              onKeyDown={(event) =>
                handleTreeItemKeyDown(event, entry, isDirectory, isExpanded)
              }
              role="treeitem"
              style={{ "--file-depth": level } as CSSProperties}
              tabIndex={
                entry.id === selectedEntryId ||
                (level === 0 &&
                  entry.id === entries[0]?.id &&
                  (!selectedEntryId || !hasVisibleProjectFileEntry(entries, selectedEntryId)))
                  ? 0
                  : -1
              }
            >
              {isDirectory ? (
                <IconButton
                  className="project-file-disclosure"
                  icon={
                    isLoading ? (
                      <LoaderCircle aria-hidden="true" className="project-file-loading-icon" size={14} />
                    ) : (
                      <ChevronRight size={16} />
                    )
                  }
                  isDisabled={isLoading}
                  label={t(isExpanded ? "{name} 접기" : "{name} 펼치기", { name: entry.name })}
                  onClick={(event) => {
                    event.stopPropagation();
                    onToggle(entry);
                  }}
                  size="sm"
                  tabIndex={-1}
                  tooltip={t(isExpanded ? "{name} 접기" : "{name} 펼치기", { name: entry.name })}
                  variant="ghost"
                />
              ) : (
                <span className="project-file-disclosure" />
              )}
              <ProjectFileIcon
                aria-hidden="true"
                className="project-file-icon"
                size={isDirectory ? 16 : 15}
                style={{ color: fileVisualMeta.color }}
              />
              <span
                className="project-file-name"
                data-muted={fileVisualMeta.muted ? "true" : undefined}
                title={entry.path}
              >
                {entry.name}
              </span>
              <IconButton
                aria-controls={
                  reviewingDeleteEntryId === entry.id
                    ? "project-file-delete-confirmation"
                    : undefined
                }
                aria-expanded={reviewingDeleteEntryId === entry.id}
                className="project-file-remove"
                icon={<X size={13} />}
                isDisabled={!canManage}
                label={t("{name} 제거", { name: entry.name })}
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(entry);
                }}
                size="sm"
                tabIndex={-1}
                tooltip={t("{name} 제거", { name: entry.name })}
                variant="ghost"
              />
            </div>
            {isDirectory && isExpanded && entry.children ? (
              <ProjectFileTree
                canManage={canManage}
                entries={entry.children}
                level={level + 1}
                loadingEntryIds={loadingEntryIds}
                onDelete={onDelete}
                onSelect={onSelect}
                onToggle={onToggle}
                reviewingDeleteEntryId={reviewingDeleteEntryId}
                selectedEntryId={selectedEntryId}
              />
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

// 우측 프로젝트 패널의 자료함과 파일 트리 화면을 렌더링한다.
export function ProjectFilesPanel({
  attachments,
  canManage,
  demoStatus,
  filteredTreeFiles,
  groupedFiles,
  isSelectedSourceFile,
  isMaximized,
  isImporting,
  isTreeCollapsed,
  loadingEntryIds,
  mode,
  onBackToLibrary,
  onClosePreview,
  onCancelImport,
  onOpenAudio,
  onOpenDirectory,
  onOpenFiles,
  onOpenSource,
  onRefreshDocumentStatus,
  onConfirmDelete,
  onQueryChange,
  onSelectFile,
  onToggleFile,
  onToggleTreeCollapsed,
  onTreeResizeStart,
  onTreeWidthChange,
  preview,
  query,
  statusRevision,
  treeAttachments,
  treeFileCount,
  treeWidth,
}: ProjectFilesPanelProps) {
  const { t } = useI18n();
  const [deleteReview, setDeleteReview] = useState<Attachment | null>(null);
  const [isDeletingReview, setIsDeletingReview] = useState(false);
  const deleteConfirmationRef = useRef<HTMLDivElement | null>(null);
  const deleteReturnFocusRef = useRef<HTMLElement | null>(null);
  const clampedTreeWidth = clampProjectFileTreeWidth(treeWidth);
  const isCompactPreview = Boolean(preview && !isMaximized && !isSelectedSourceFile);
  const loadingEntryIdSet = new Set(loadingEntryIds);
  const importStatus = isImporting ? (
    <div className="project-file-import-status" role="status">
      <Spinner label={t("폴더 구조를 읽는 중...")} shade="subtle" />
      <Button
        label={t("가져오기 중지")}
        onClick={onCancelImport}
        size="sm"
        variant="ghost"
      />
    </div>
  ) : null;

  useEffect(() => {
    if (!deleteReview) {
      return;
    }

    const frame = window.requestAnimationFrame(() => {
      deleteConfirmationRef.current?.querySelector<HTMLElement>("button")?.focus();
    });
    return () => window.cancelAnimationFrame(frame);
  }, [deleteReview]);

  function openDeleteReview(entry: Attachment) {
    const activeElement =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    deleteReturnFocusRef.current =
      activeElement?.closest<HTMLElement>('[role="treeitem"]') ??
      document.getElementById(getProjectSourceManageButtonId(entry.id)) ??
      activeElement;
    setIsDeletingReview(false);
    setDeleteReview(entry);
  }

  function cancelDeleteReview() {
    const returnTarget =
      deleteReturnFocusRef.current?.closest<HTMLElement>('[role="treeitem"]') ??
      deleteReturnFocusRef.current;
    setDeleteReview(null);
    setIsDeletingReview(false);
    window.requestAnimationFrame(() => returnTarget?.focus({ preventScroll: true }));
  }

  async function confirmDeleteReview() {
    if (!deleteReview) {
      return;
    }

    const returnTarget =
      deleteReturnFocusRef.current?.closest<HTMLElement>('[role="treeitem"]') ??
      deleteReturnFocusRef.current;
    const isTreeDelete = returnTarget?.matches('[role="treeitem"]') ?? false;
    const focusCandidates = isTreeDelete
      ? (() => {
          const visibleTreeItems = Array.from(
            returnTarget
              ?.closest<HTMLElement>('[role="tree"]')
              ?.querySelectorAll<HTMLElement>('[role="treeitem"]') ?? [],
          ).filter((item) => item.getClientRects().length > 0);
          const currentIndex = returnTarget ? visibleTreeItems.indexOf(returnTarget) : -1;
          return [
            visibleTreeItems[currentIndex + 1],
            visibleTreeItems[currentIndex - 1],
          ];
        })()
      : (() => {
          const manageButtons = Array.from(
            document.querySelectorAll<HTMLElement>(".project-source-actions button"),
          );
          const currentIndex = returnTarget ? manageButtons.indexOf(returnTarget) : -1;
          return [
            manageButtons[currentIndex + 1],
            manageButtons[currentIndex - 1],
          ];
        })();

    setIsDeletingReview(true);
    const deleted = await onConfirmDelete(deleteReview);

    if (!deleted) {
      setIsDeletingReview(false);
      window.requestAnimationFrame(() => {
        deleteConfirmationRef.current
          ?.querySelectorAll<HTMLElement>("button")
          .item(1)
          ?.focus({ preventScroll: true });
      });
      return;
    }

    setDeleteReview(null);
    setIsDeletingReview(false);
    window.requestAnimationFrame(() => {
      const fallback = isTreeDelete
        ? document.querySelector<HTMLElement>(".project-files-search input") ??
          document.querySelector<HTMLElement>(".project-files-open-button")
        : document.querySelector<HTMLElement>(".project-files-open-button");
      const focusTarget = focusCandidates.find((candidate) => candidate?.isConnected) ?? fallback;
      focusTarget?.focus({ preventScroll: true });
    });
  }

  const deleteConfirmation = deleteReview ? (
    <div ref={deleteConfirmationRef}>
      <ProjectFileDeleteConfirmation
        entry={deleteReview}
        isDeleting={isDeletingReview}
        onCancel={cancelDeleteReview}
        onConfirm={() => void confirmDeleteReview()}
      />
    </div>
  ) : null;

  function handleTreeResizeKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const step = event.shiftKey
      ? PROJECT_FILE_TREE_KEYBOARD_LARGE_STEP
      : PROJECT_FILE_TREE_KEYBOARD_STEP;
    let nextWidth: number | null = null;

    if (event.key === "ArrowLeft") {
      nextWidth = clampedTreeWidth + step;
    } else if (event.key === "ArrowRight") {
      nextWidth = clampedTreeWidth - step;
    } else if (event.key === "Home") {
      nextWidth = MIN_PROJECT_FILE_TREE_WIDTH;
    } else if (event.key === "End") {
      nextWidth = MAX_PROJECT_FILE_TREE_WIDTH;
    }

    if (nextWidth === null) {
      return;
    }

    event.preventDefault();
    event.stopPropagation();
    onTreeWidthChange(clampProjectFileTreeWidth(nextWidth));
  }

  if (mode === "library") {
    return (
      <div className="project-panel-content project-sources-panel" data-drop-zone="project-files">
        <div className="project-sources-header">
          <div className="project-sources-actions">
            <DropdownMenu
              button={{
                className: "project-files-open-button",
                icon: <Upload size={15} />,
                isDisabled: !canManage,
                label: t("자료 추가"),
                size: "sm",
                tooltip: t("자료 추가"),
                variant: "secondary",
              }}
              items={[
                { label: t("파일 추가"), onClick: onOpenFiles },
                { label: t("폴더 추가"), onClick: onOpenDirectory },
                {
                  icon: <AudioLines size={15} />,
                  label: t("회의 음성 추가"),
                  onClick: onOpenAudio,
                },
              ]}
            />
          </div>
          {attachments.length > 0 ? (
            <TextInput
              className="project-files-search project-sources-search"
              hasClear
              isLabelHidden
              label={t("프로젝트 자료 검색")}
              onChange={onQueryChange}
              placeholder={t("자료 검색...")}
              startIcon={<Search size={15} />}
              value={query}
              width="100%"
            />
          ) : null}
        </div>
        {importStatus}
        {deleteConfirmation}

        <section className="project-sources-section" aria-label={t("프로젝트 자료")}>
          <div className="project-sources-section-title">
            <h2>{t("업로드한 자료")}</h2>
            <span>{t("{count}개", { count: attachments.length })}</span>
          </div>
          {attachments.length > 0 ? (
            groupedFiles.length > 0 ? (
              <div className="project-source-timeline">
                {groupedFiles.map((group) => (
                  <div className="project-source-time-group" key={group.label}>
                    <span className="project-source-time-label">{group.label}</span>
                    <div className="project-source-list">
                      {group.sources.map((source) => {
                        const sourceCount = countProjectFileEntries([source]);
                        const sourceMeta =
                          source.kind === "directory"
                            ? { Icon: FolderOpen, color: "var(--muted)" }
                            : getProjectFileVisualMeta(source.name);
                        const SourceIcon = sourceMeta.Icon;
                        const documentStatusMeta = getProjectDocumentStatusMeta(source);

                        return (
                          <ProjectSourceCard
                            isMeeting={isMeetingDocument(source.documentType)}
                            key={source.id}
                            label={
                              isMeetingDocument(source.documentType)
                                ? t("{name} 회의 음성 상태", { name: source.name })
                                : t("{name} 열기", { name: source.name })
                            }
                            onOpen={() => onOpenSource(source)}
                          >
                            <div className="project-source-icon">
                              <SourceIcon size={18} style={{ color: sourceMeta.color }} />
                            </div>
                            <div className="project-source-body">
                              <strong title={source.path}>{source.name}</strong>
                              <span>
                                {source.kind === "directory"
                                  ? t("폴더 · {count}개 항목", { count: sourceCount })
                                  : isMeetingDocument(source.documentType)
                                    ? source.transcriptionProvider
                                      ? t("회의 음성 · {provider}", {
                                          provider: source.transcriptionProvider,
                                        })
                                      : t("회의 음성")
                                  : t("파일")}
                              </span>
                              {documentStatusMeta ? (
                                <span title={t(documentStatusMeta.title)}>
                                  <Badge
                                    className="project-document-status"
                                    label={t(documentStatusMeta.label)}
                                    variant={documentStatusMeta.variant}
                                  />
                                </span>
                              ) : null}
                              {isMeetingDocument(source.documentType) &&
                              source.documentStatus === "processing" &&
                              typeof source.processingProgressDone === "number" &&
                              typeof source.processingProgressTotal === "number" ? (
                                <small>
                                  {t("메모리 분석 {done}/{total}", {
                                    done: source.processingProgressDone,
                                    total: source.processingProgressTotal,
                                  })}
                                </small>
                              ) : null}
                              {isMeetingDocument(source.documentType) &&
                              source.documentStatus === "indexed" &&
                              getExtractionTotal(source.extracted) > 0 ? (
                                <small>
                                  {t("프로젝트 메모리 {count}개 추출", {
                                    count: getExtractionTotal(source.extracted),
                                  })}
                                </small>
                              ) : null}
                              {isMeetingDocument(source.documentType) &&
                              (source.documentStatus === "failed" ||
                                source.documentStatus === "delayed") ? (
                                <small
                                  className="project-source-status-detail"
                                  data-tone={source.documentStatus}
                                >
                                  {t(
                                    source.lastError ||
                                      documentStatusMeta?.title ||
                                      "회의 음성을 처리하지 못했습니다",
                                  )}
                                </small>
                              ) : null}
                            </div>
                            <div className="project-source-actions">
                              {isMeetingDocument(source.documentType) &&
                              (source.documentStatus === "processing" ||
                                source.documentStatus === "delayed") ? (
                                <Button
                                  icon={<RefreshCw size={14} />}
                                  isIconOnly
                                  label={t("상태 새로고침")}
                                  onClick={() => onRefreshDocumentStatus(source)}
                                  size="sm"
                                  tooltip={t("상태 새로고침")}
                                  variant="ghost"
                                />
                              ) : null}
                              <DropdownMenu
                                button={{
                                  icon: <Ellipsis size={15} />,
                                  id: getProjectSourceManageButtonId(source.id),
                                  isIconOnly: true,
                                  isDisabled: !canManage,
                                  label: t("{name} 관리", { name: source.name }),
                                  size: "sm",
                                  tooltip: t("{name} 관리", { name: source.name }),
                                  variant: "ghost",
                                }}
                                items={[
                                  {
                                    label:
                                      deleteReview?.id === source.id
                                        ? t("삭제 확인 열림")
                                        : t("삭제…"),
                                    onClick: () => openDeleteReview(source),
                                  },
                                ]}
                                menuWidth={112}
                              />
                            </div>
                          </ProjectSourceCard>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <EmptyState
                className="project-panel-empty-state"
                icon={<Search size={17} />}
                isCompact
                title={t("검색 결과가 없습니다.")}
              />
            )
          ) : (
            <EmptyState
              className="project-sources-empty"
              description={t("PaiM에게 제공할 파일·폴더·회의 음성을 업로드하세요.")}
              icon={<FolderOpen size={32} />}
              title={t("등록된 자료가 없습니다")}
            />
          )}
        </section>
      </div>
    );
  }

  return (
    <div
      className="project-panel-content project-files-panel"
      data-drop-zone="project-files"
      data-compact-preview={isCompactPreview ? "true" : undefined}
      data-single-file={isSelectedSourceFile ? "true" : undefined}
      data-tree-collapsed={isTreeCollapsed}
    >
      <div className="project-files-header">
        <div className="project-files-toolbar">
          <Button
            className="project-sources-secondary"
            label={t("자료함")}
            onClick={onBackToLibrary}
            size="sm"
            variant="ghost"
          />
          <Badge className="project-files-count" label={treeFileCount} />
        </div>
        <div className="project-files-pathbar">
          <p className="project-files-root">
            {getProjectFileRootLabel(
              treeAttachments,
              t("{count}개 위치", { count: treeAttachments.length }),
            )}
          </p>
          {isCompactPreview ? (
            <IconButton
              className="project-files-tree-toggle"
              icon={<ArrowLeft size={16} />}
              label={t("파일 목록으로 돌아가기")}
              onClick={onClosePreview}
              size="sm"
              tooltip={t("파일 목록으로 돌아가기")}
              variant="ghost"
            />
          ) : !isSelectedSourceFile ? (
            <IconButton
              className="project-files-tree-toggle"
              icon={<FolderOpen size={16} />}
              label={isTreeCollapsed ? t("파일 목록 펼치기") : t("파일 목록 접기")}
              onClick={onToggleTreeCollapsed}
              size="sm"
              tooltip={isTreeCollapsed ? t("파일 목록 펼치기") : t("파일 목록 접기")}
              variant="ghost"
            />
          ) : null}
        </div>
        {demoStatus && demoStatus.scope !== "github" ? (
          <Banner
            className="runtime-status project-panel-status"
            container="card"
            key={statusRevision}
            status={demoStatus.kind ?? (demoStatus.ok ? "success" : "error")}
            title={t(demoStatus.message)}
          />
        ) : null}
        {importStatus}
        {deleteConfirmation}
      </div>
      <div className="project-files-main">
        {preview ? (
          <div className="project-file-preview">
            <Breadcrumbs
              className="project-file-preview-path"
              label={t("{name} 경로", { name: preview.name })}
              separator={<ChevronRight size={14} />}
              variant="supporting"
            >
              {getProjectFilePathSegments(preview.path).map((segment, index, segments) => (
                <BreadcrumbItem
                  isCurrent={index === segments.length - 1}
                  key={`${segment}-${index}`}
                >
                  {segment}
                </BreadcrumbItem>
              ))}
            </Breadcrumbs>
            {preview.isLoading ? (
              <Center height="100%" minHeight={0} width="100%">
                <Spinner label={t("파일을 읽는 중입니다...")} shade="subtle" />
              </Center>
            ) : preview.error ? (
              <Center height="100%" minHeight={0} width="100%">
                <EmptyState isCompact title={preview.error} />
              </Center>
            ) : (
              <CodeBlock
                className="project-file-code"
                code={preview.content}
                container="section"
                hasLineNumbers
                language={getProjectFilePreviewLanguage(preview.name)}
                maxHeight="100%"
                size="sm"
                title={preview.name}
                width="100%"
              />
            )}
          </div>
        ) : (
          <EmptyState
            className="project-files-preview-empty"
            description={t("파일 목록에서 파일을 선택하세요")}
            icon={<FolderOpen size={34} />}
            title={t("파일 열기")}
          />
        )}
      </div>
      {!isSelectedSourceFile ? (
        <div className="project-files-tree-pane">
          <div
            aria-keyshortcuts="ArrowLeft ArrowRight Home End"
            aria-label={t("파일 목록 너비 조절")}
            aria-orientation="vertical"
            aria-valuemax={MAX_PROJECT_FILE_TREE_WIDTH}
            aria-valuemin={MIN_PROJECT_FILE_TREE_WIDTH}
            aria-valuenow={clampedTreeWidth}
            aria-valuetext={`${clampedTreeWidth}px`}
            className="project-files-tree-resize-handle"
            onKeyDown={handleTreeResizeKeyDown}
            onPointerDown={onTreeResizeStart}
            role="separator"
            tabIndex={0}
          />
          <TextInput
            className="project-files-search"
            hasClear
            isLabelHidden
            label={t("파일 필터링")}
            onChange={onQueryChange}
            placeholder={t("파일 필터링...")}
            startIcon={<Search size={15} />}
            value={query}
            width="100%"
          />
          {treeAttachments.length > 0 ? (
            filteredTreeFiles.length > 0 ? (
              <ProjectFileTree
                canManage={canManage}
                entries={filteredTreeFiles}
                loadingEntryIds={loadingEntryIdSet}
                onDelete={openDeleteReview}
                onSelect={onSelectFile}
                onToggle={onToggleFile}
                reviewingDeleteEntryId={deleteReview?.id}
                selectedEntryId={preview?.id}
              />
            ) : (
              <EmptyState
                className="project-panel-empty-state"
                icon={<Search size={17} />}
                isCompact
                title={t("검색 결과가 없습니다.")}
              />
            )
          ) : (
              <EmptyState
                className="project-panel-empty-state"
                icon={<FolderOpen size={18} />}
                isCompact
                title={t("파일 목록이 비어 있습니다.")}
              />
          )}
        </div>
      ) : null}
    </div>
  );
}
