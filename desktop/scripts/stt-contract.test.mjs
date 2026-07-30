import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  getExtractionTotal,
  getLocalISODate,
  getSttFailureMessage,
  isISODate,
  isKnownAudioFileName,
  isMeetingDocument,
  isSupportedAudioFileName,
  STT_DOCUMENT_TYPE,
  STT_SAFE_EXTENSIONS,
  STT_SAFE_MAX_FILE_BYTES,
} from "../src/stt.ts";

const appSource = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
const filesPanelSource = readFileSync(
  new URL("../src/projectFiles.tsx", import.meta.url),
  "utf8",
);
const projectDetailSource = readFileSync(
  new URL("../src/ProjectDetailPage.tsx", import.meta.url),
  "utf8",
);
const audioUploadDialogSource = readFileSync(
  new URL("../src/AudioUploadDialog.tsx", import.meta.url),
  "utf8",
);
const nativeSource = readFileSync(
  new URL("../src-tauri/src/lib.rs", import.meta.url),
  "utf8",
);

function sourceBetween(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);

  assert.notEqual(start, -1, `missing source marker: ${startMarker}`);
  assert.notEqual(end, -1, `missing source marker: ${endMarker}`);
  return source.slice(start, end);
}

test("STT uses the CLOVA meeting-audio contract and excludes WMA", () => {
  assert.deepEqual([...STT_SAFE_EXTENSIONS], [
    "mp3",
    "mp4",
    "m4a",
    "wav",
    "aac",
    "ac3",
    "ogg",
    "flac",
  ]);
  for (const extension of STT_SAFE_EXTENSIONS) {
    assert.equal(isSupportedAudioFileName(`meeting.${extension}`), true);
  }
  assert.equal(isSupportedAudioFileName("meeting.wma"), false);
  assert.equal(isKnownAudioFileName("meeting.WMA"), true);
  assert.equal(STT_SAFE_MAX_FILE_BYTES, 25 * 1024 * 1024);
  assert.equal(STT_DOCUMENT_TYPE, "meeting");
  assert.equal(isMeetingDocument("meeting"), true);
  assert.equal(isMeetingDocument("pdf"), false);
});

test("meeting date accepts only real ISO calendar dates", () => {
  assert.equal(isISODate("2026-07-30"), true);
  assert.equal(isISODate("2024-02-29"), true);
  assert.equal(isISODate("2026-02-29"), false);
  assert.equal(isISODate("2026-13-01"), false);
  assert.equal(isISODate("07/30/2026"), false);
  assert.equal(
    getLocalISODate(new Date(2026, 6, 30, 23, 59, 59)),
    "2026-07-30",
  );
});

test("STT failure codes and extraction counts are presentation-safe", () => {
  assert.equal(
    getSttFailureMessage("STT_MISSING_CREDENTIALS"),
    "음성 전사 서비스 인증 정보가 설정되지 않았습니다",
  );
  assert.equal(
    getSttFailureMessage("secret provider response"),
    "회의 음성을 처리하지 못했습니다",
  );
  assert.equal(
    getExtractionTotal({ action: 2, decision: 1, issue: 3, risk: 0 }),
    6,
  );
});

test("desktop routes audio through the STT endpoint with native size preflight", () => {
  assert.match(appSource, /`\/projects\/\$\{apiProject\.apiProjectId\}\/audio`/);
  assert.match(appSource, /formData\.append\("date", draft\.date\)/);
  assert.match(appSource, /maxBytes: STT_SAFE_MAX_FILE_BYTES/);
  assert.match(appSource, /AUDIO_STATUS_POLL_TIMEOUT_MS = 15 \* 60 \* 1000/);
  assert.match(appSource, /documentType: STT_DOCUMENT_TYPE/);
  assert.match(appSource, /enqueuePendingDocumentDelete/);
  assert.match(appSource, /needsProjectDocumentStatusHydration/);
  assert.match(appSource, /reconcileProjectDocumentAttachments/);
  assert.match(filesPanelSource, /회의 음성 추가/);
  assert.match(nativeSource, /metadata\.len\(\) > limit/);
  assert.match(nativeSource, /FILE_TOO_LARGE/);
});

test("meeting audio polling supports delayed recovery without duplicate status requests", () => {
  const pollingSource = sourceBetween(
    appSource,
    "function fetchDocumentStatusOnce",
    "async function syncProjectDocuments",
  );

  assert.match(pollingSource, /documentStatusRequestsRef\.current\.get/);
  assert.match(pollingSource, /AUDIO_STATUS_POLL_INTERVAL_MS \* 2 \*\*/);
  assert.match(pollingSource, /documentStatus: "delayed"/);
  assert.match(pollingSource, /async function handleRefreshProjectDocumentStatus/);
  assert.match(pollingSource, /fetchDocumentStatusOnce/);
  assert.match(pollingSource, /syncProjectDocuments/);
  assert.match(pollingSource, /refreshProjectMemoryCounts/);
  assert.match(filesPanelSource, /상태 새로고침/);
  assert.match(projectDetailSource, /상태 새로고침/);
});

test("project drops route only top-level single audio through the shared STT draft", () => {
  const dropSource = sourceBetween(
    appSource,
    "async function addDroppedPathsToProject",
    "// 프로젝트 자료함에 개별 파일을 루트 자료로 추가한다.",
  );
  const directorySource = sourceBetween(
    appSource,
    "async function createProjectDirectoryEntry",
    "// 프로젝트 자료함에 단일 파일을 트리의 루트 항목으로 추가한다.",
  );

  assert.match(dropSource, /entry\.kind === "file"/);
  assert.match(dropSource, /isSupportedAudioFileName/);
  assert.match(dropSource, /회의 음성은 한 번에 하나씩 올려 주세요/);
  assert.match(dropSource, /prepareProjectAudioUpload\(projectId, audioPaths\[0\]\)/);
  assert.match(dropSource, /registerProjectEntries\(projectId, entries\)/);
  assert.match(directorySource, /createProjectFileEntry/);
});

test("session attachments reject audio before creating local chips", () => {
  const attachmentSource = sourceBetween(
    appSource,
    "async function appendAttachmentPaths",
    "// 로컬 이미지 파일이면 프론트 표시용 미리보기 URL을 만든다.",
  );

  assert.match(attachmentSource, /isKnownAudioFileName/);
  assert.match(
    attachmentSource,
    /음성 파일은 프로젝트 자료함의 회의 녹음 업로드를 이용해 주세요\./,
  );
  assert.ok(
    attachmentSource.indexOf("isKnownAudioFileName") <
      attachmentSource.indexOf("createAttachment"),
  );
});

test("audio selection stays available offline while transcription observes server state", () => {
  const openAudioSource = sourceBetween(
    appSource,
    "async function handleOpenProjectAudio",
    "function closeAudioUploadDialog",
  );
  const confirmAudioSource = sourceBetween(
    appSource,
    "async function handleConfirmAudioUpload",
    "// 서버 업로드는 로컬 파일을 base64로 읽어",
  );
  const dialogInvocationSource = sourceBetween(
    appSource,
    "<AudioUploadDialog",
    "/>",
  );

  assert.doesNotMatch(openAudioSource, /shouldSkipProjectMutation\s*\(/);
  assert.doesNotMatch(openAudioSource, /serverStatus/);
  assert.match(openAudioSource, /const selectedPath = await open\s*\(/);
  assert.match(openAudioSource, /prepareProjectAudioUpload\(projectId, path\)/);
  assert.match(appSource, /function prepareProjectAudioUpload[\s\S]*?setAudioUploadDraft\s*\(/);

  assert.match(
    confirmAudioSource,
    /if \(serverStatus !== "online"\) \{[\s\S]*?서버에 다시 연결한 뒤 전사를 시작할 수 있습니다[\s\S]*?return;/,
  );
  assert.match(
    dialogInvocationSource,
    /isServerOnline=\{serverStatus === "online"\}/,
  );
  assert.match(audioUploadDialogSource, /isServerOnline: boolean/);
  assert.match(
    audioUploadDialogSource,
    /isDisabled=\{\s*!isServerOnline\s*\|\|/,
  );
  assert.match(
    audioUploadDialogSource,
    /!isServerOnline[\s\S]*?서버에 다시 연결한 뒤 전사를 시작할 수 있습니다/,
  );
});
