import {
  Braces,
  CodeXml,
  Database,
  FileCode2,
  FileIcon,
  FileJson,
  FileText,
  GitBranch,
  Image,
  Lock,
  Music,
  NotebookTabs,
  Settings,
  Sparkles,
  Table,
  Terminal,
  type LucideIcon,
} from "lucide-react";

import type { Attachment, DirectoryChildEntry } from "./types";

export const DEFAULT_PROJECT_FILE_TREE_WIDTH = 300;
export const MIN_PROJECT_FILE_TREE_WIDTH = 220;
export const MAX_PROJECT_FILE_TREE_WIDTH = 520;

export type ProjectFileVisualMeta = {
  Icon: LucideIcon;
  color: string;
  muted?: boolean;
};

export type ProjectFileGroup = {
  label: string;
  sources: Attachment[];
};

export function clampProjectFileTreeWidth(width: number) {
  return Math.min(
    MAX_PROJECT_FILE_TREE_WIDTH,
    Math.max(MIN_PROJECT_FILE_TREE_WIDTH, width),
  );
}

export function countProjectFileEntries(entries: Attachment[]): number {
  return entries.reduce(
    (count, entry) => count + 1 + countProjectFileEntries(entry.children ?? []),
    0,
  );
}

function padTimePart(value: number) {
  return String(value).padStart(2, "0");
}

function getProjectSourceTimeLabel(source: Attachment) {
  if (!source.uploadedAt) {
    return "이전";
  }

  const date = new Date(source.uploadedAt);
  return `${date.getFullYear()}.${padTimePart(date.getMonth() + 1)}.${padTimePart(date.getDate())}`;
}

export function sortProjectSourcesByUploadedAt(sources: Attachment[]) {
  return [...sources].sort(
    (left, right) => (right.uploadedAt ?? 0) - (left.uploadedAt ?? 0),
  );
}

export function groupProjectSourcesByUploadedDate(sources: Attachment[]) {
  return sources.reduce<ProjectFileGroup[]>((groups, source) => {
    const label = getProjectSourceTimeLabel(source);
    const currentGroup = groups[groups.length - 1];

    if (currentGroup?.label === label) {
      currentGroup.sources.push(source);
    } else {
      groups.push({ label, sources: [source] });
    }

    return groups;
  }, []);
}

export function createProjectFileEntry(entry: DirectoryChildEntry): Attachment {
  return {
    id: `project-file-${crypto.randomUUID()}`,
    name: entry.name,
    path: entry.path,
    kind: entry.kind,
    children: entry.kind === "directory" ? [] : undefined,
    childrenLoaded: false,
    isExpanded: false,
  };
}

export function updateProjectFileEntry(
  entries: Attachment[],
  entryId: string,
  updater: (entry: Attachment) => Attachment,
): Attachment[] {
  return entries.map((entry) => {
    if (entry.id === entryId) {
      return updater(entry);
    }

    if (!entry.children) {
      return entry;
    }

    return {
      ...entry,
      children: updateProjectFileEntry(entry.children, entryId, updater),
    };
  });
}

export function deleteProjectFileEntry(entries: Attachment[], entryId: string): Attachment[] {
  return entries
    .filter((entry) => entry.id !== entryId)
    .map((entry) => ({
      ...entry,
      children: entry.children ? deleteProjectFileEntry(entry.children, entryId) : undefined,
    }));
}

export function filterProjectFileEntries(entries: Attachment[], query: string): Attachment[] {
  const normalizedQuery = query.trim().toLowerCase();

  if (!normalizedQuery) {
    return entries;
  }

  return entries.flatMap((entry) => {
    const filteredChildren = filterProjectFileEntries(entry.children ?? [], normalizedQuery);
    const matches =
      entry.name.toLowerCase().includes(normalizedQuery) ||
      entry.path.toLowerCase().includes(normalizedQuery);

    return matches || filteredChildren.length > 0
      ? [{ ...entry, children: filteredChildren, isExpanded: true }]
      : [];
  });
}

// 파일명과 확장자로 파일 트리 아이콘 톤을 정한다.
export function getProjectFileVisualMeta(name: string): ProjectFileVisualMeta {
  const lowerName = name.toLowerCase();

  if (lowerName === ".gitignore" || lowerName === ".gitattributes") {
    return { Icon: GitBranch, color: "var(--risk-fg)" };
  }

  if (lowerName === ".ds_store") {
    return { Icon: FileIcon, color: "var(--faint)", muted: true };
  }

  if (lowerName === ".env" || lowerName.startsWith(".env")) {
    return { Icon: Settings, color: "var(--issue-fg)" };
  }

  if (lowerName.endsWith(".python-version")) {
    return { Icon: FileCode2, color: "var(--action-fg)" };
  }

  const extension = lowerName.includes(".") ? lowerName.split(".").pop() : "";
  const extensionMeta: Record<string, ProjectFileVisualMeta> = {
    py: { Icon: FileCode2, color: "var(--action-fg)" },
    md: { Icon: FileText, color: "var(--decision-fg)" },
    txt: { Icon: FileText, color: "var(--muted)" },
    json: { Icon: FileJson, color: "var(--issue-fg)" },
    toml: { Icon: Settings, color: "var(--accent-purple)" },
    yaml: { Icon: Settings, color: "var(--accent-purple)" },
    yml: { Icon: Settings, color: "var(--accent-purple)" },
    lock: { Icon: Lock, color: "var(--muted)" },
    skill: { Icon: Sparkles, color: "var(--accent-purple)" },
    png: { Icon: Image, color: "var(--action-fg)" },
    jpg: { Icon: Image, color: "var(--action-fg)" },
    jpeg: { Icon: Image, color: "var(--action-fg)" },
    gif: { Icon: Image, color: "var(--action-fg)" },
    svg: { Icon: Image, color: "var(--issue-fg)" },
    csv: { Icon: Table, color: "var(--decision-fg)" },
    xlsx: { Icon: Table, color: "var(--decision-fg)" },
    pdf: { Icon: FileText, color: "var(--risk-fg)" },
    m4a: { Icon: Music, color: "var(--accent-purple)" },
    mp3: { Icon: Music, color: "var(--accent-purple)" },
    wav: { Icon: Music, color: "var(--accent-purple)" },
    js: { Icon: Braces, color: "var(--issue-fg)" },
    ts: { Icon: Braces, color: "var(--action-fg)" },
    jsx: { Icon: CodeXml, color: "var(--action-fg)" },
    tsx: { Icon: CodeXml, color: "var(--action-fg)" },
    html: { Icon: CodeXml, color: "var(--risk-fg)" },
    css: { Icon: CodeXml, color: "var(--action-fg)" },
    sh: { Icon: Terminal, color: "var(--decision-fg)" },
    ipynb: { Icon: NotebookTabs, color: "var(--issue-fg)" },
    sql: { Icon: Database, color: "var(--action-fg)" },
  };

  return extensionMeta[extension ?? ""] ?? { Icon: FileIcon, color: "var(--muted)" };
}
