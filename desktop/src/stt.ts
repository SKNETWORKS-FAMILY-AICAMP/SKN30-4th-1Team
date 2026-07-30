export const STT_SAFE_EXTENSIONS = [
  "mp3",
  "mp4",
  "m4a",
  "wav",
  "aac",
  "ac3",
  "ogg",
  "flac",
] as const;
export const KNOWN_AUDIO_EXTENSIONS = [...STT_SAFE_EXTENSIONS, "wma"] as const;
export const STT_SAFE_MAX_FILE_BYTES = 25 * 1024 * 1024;
export const STT_DOCUMENT_TYPE = "meeting";

export type AudioUploadDraft = {
  date: string;
  name: string;
  path: string;
  projectId: string;
};

export type AudioUploadResponse = {
  diarization: boolean;
  doc_id: number;
  provider: string;
  status: "processing";
};

export type DocumentExtractionCounts = Partial<
  Record<"action" | "decision" | "issue" | "risk", number>
>;

const STT_FAILURE_MESSAGES: Record<string, string> = {
  STT_AUDIO_TOO_LARGE: "회의 음성 파일이 서버 허용 크기를 초과했습니다",
  STT_EMPTY_AUDIO: "회의 음성 파일이 비어 있습니다",
  STT_INGEST_FAILED: "전사 결과를 프로젝트 메모리로 반영하지 못했습니다",
  STT_MISSING_CREDENTIALS: "음성 전사 서비스 인증 정보가 설정되지 않았습니다",
  STT_MISSING_DEPENDENCY: "음성 전사에 필요한 서버 구성 요소가 없습니다",
  STT_NO_SPEECH: "회의 음성에서 인식할 수 있는 발화를 찾지 못했습니다",
  STT_PROVIDER_ERROR: "음성 전사 서비스에서 처리에 실패했습니다",
  STT_UNSUPPORTED_AUDIO_FORMAT: "서버가 이 회의 음성 형식을 지원하지 않습니다",
  UPLOAD_CANCELLED: "회의 음성 처리가 취소되었습니다",
  UPLOAD_PROCESSING_STALE: "회의 음성 처리가 중단되어 다시 업로드해야 합니다",
};

export function getLocalISODate(date = new Date()) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function isISODate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return false;
  }

  const [year, month, day] = value.split("-").map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

export function isMeetingDocument(documentType?: string | null) {
  return documentType === STT_DOCUMENT_TYPE;
}

function hasExtension(name: string, extensions: readonly string[]) {
  const extension = name.split(".").pop()?.toLowerCase();
  return Boolean(extension && extensions.includes(extension));
}

export function isSupportedAudioFileName(name: string) {
  return hasExtension(name, STT_SAFE_EXTENSIONS);
}

export function isKnownAudioFileName(name: string) {
  return hasExtension(name, KNOWN_AUDIO_EXTENSIONS);
}

export function getSttFailureMessage(code?: string | null) {
  if (!code) {
    return "회의 음성을 처리하지 못했습니다";
  }

  return STT_FAILURE_MESSAGES[code] ?? "회의 음성을 처리하지 못했습니다";
}

export function getExtractionTotal(extracted?: DocumentExtractionCounts | null) {
  if (!extracted) {
    return 0;
  }

  return Object.values(extracted).reduce(
    (total, count) => total + (typeof count === "number" ? count : 0),
    0,
  );
}
