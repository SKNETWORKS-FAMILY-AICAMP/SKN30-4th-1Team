import { fetchPaimJson } from "./paimApi";

export type DocumentCapability = {
  extensions: string[];
  max_file_bytes: number;
};

export type QueryAttachmentCapability = DocumentCapability & {
  max_total_bytes: number;
};

export type PaimCapabilities = {
  schema_version: 1;
  project_documents: DocumentCapability;
  query_attachments: QueryAttachmentCapability;
};

export async function fetchPaimCapabilities(signal?: AbortSignal) {
  return fetchPaimJson<PaimCapabilities>("/capabilities", { signal });
}

export function getFileExtension(name: string) {
  return name.includes(".") ? name.split(".").pop()?.toLowerCase() ?? "" : "";
}

export function supportsExtension(name: string, extensions: string[]) {
  return extensions.includes(getFileExtension(name));
}

export function formatExtensions(extensions: string[]) {
  return extensions.map((extension) => `.${extension}`).join(", ");
}

export function formatBytesAsMiB(bytes: number) {
  const mib = bytes / (1024 * 1024);
  return `${Number.isInteger(mib) ? mib : mib.toFixed(1)} MiB`;
}
