import { useId } from "react";
import {
  AlertTriangle,
  AudioLines,
  CalendarDays,
  FileAudio,
  Sparkles,
  X,
} from "lucide-react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import {
  Layout,
  LayoutContent,
  LayoutFooter,
} from "@astryxdesign/core/Layout";

import { formatBytesAsMiB, formatExtensions } from "./capabilities";
import { useI18n } from "./i18n";
import {
  isISODate,
  STT_SAFE_EXTENSIONS,
  STT_SAFE_MAX_FILE_BYTES,
  type AudioUploadDraft,
} from "./stt";

type AudioUploadDialogProps = {
  draft: AudioUploadDraft | null;
  isServerOnline: boolean;
  isSubmitting: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  onDateChange: (date: string) => void;
};

export function AudioUploadDialog({
  draft,
  isServerOnline,
  isSubmitting,
  onCancel,
  onConfirm,
  onDateChange,
}: AudioUploadDialogProps) {
  const { t } = useI18n();
  const dateInputId = useId();
  const dateDescriptionId = `${dateInputId}-description`;
  const dateErrorId = `${dateInputId}-error`;
  const hasDateError = Boolean(draft?.date) && !isISODate(draft?.date ?? "");
  const capabilityLabel = `${formatExtensions([...STT_SAFE_EXTENSIONS])} · ${formatBytesAsMiB(
    STT_SAFE_MAX_FILE_BYTES,
  )}`;

  return (
    <Dialog
      aria-label={t("회의 음성 전사")}
      className="audio-upload-dialog"
      isOpen={Boolean(draft)}
      maxHeight="86vh"
      onOpenChange={(isOpen) => {
        if (!isOpen && !isSubmitting) {
          onCancel();
        }
      }}
      purpose="form"
      width={480}
    >
      <Layout
        height="auto"
        header={
          <DialogHeader
            endContent={
              isSubmitting ? undefined : (
                <Button
                  className="audio-upload-dialog-close"
                  icon={<X aria-hidden="true" size={16} />}
                  isIconOnly
                  label={t("닫기")}
                  onClick={onCancel}
                  tooltip={t("닫기")}
                  variant="ghost"
                />
              )
            }
            hasDivider
            subtitle={t("녹음 파일을 전사해 프로젝트 메모리로 반영합니다.")}
            title={t("회의 음성 전사")}
          />
        }
        content={
          <LayoutContent className="audio-upload-dialog-content">
            <div className="audio-upload-file-card">
              <span aria-hidden="true" className="audio-upload-file-icon">
                <FileAudio size={20} />
              </span>
              <span className="audio-upload-file-copy">
                <strong title={draft?.path}>{draft?.name ?? ""}</strong>
                <small>{t("지원 형식 및 제한: {details}", { details: capabilityLabel })}</small>
              </span>
              <Badge label="STT" variant="neutral" />
            </div>

            <div className="audio-upload-date-field">
              <label className="audio-upload-date-label" htmlFor={dateInputId}>
                {t("회의 날짜")}
              </label>
              <p className="audio-upload-date-description" id={dateDescriptionId}>
                {t("회의에서 언급된 상대 날짜를 해석할 기준일입니다.")}
              </p>
              <input
                aria-describedby={`${dateDescriptionId}${
                  hasDateError ? ` ${dateErrorId}` : ""
                }`}
                aria-errormessage={hasDateError ? dateErrorId : undefined}
                aria-invalid={hasDateError || undefined}
                className="audio-upload-date-input"
                disabled={isSubmitting}
                id={dateInputId}
                name="meeting-date"
                onChange={(event) => onDateChange(event.currentTarget.value)}
                type="date"
                value={draft?.date ?? ""}
              />
              {hasDateError ? (
                <p className="audio-upload-date-error" id={dateErrorId} role="alert">
                  {t("올바른 회의 날짜를 선택해 주세요")}
                </p>
              ) : null}
            </div>

            <div className="audio-upload-contract-note">
              <span aria-hidden="true">
                <Sparkles size={16} />
              </span>
              <div>
                <strong>{t("전사 후 자동 분석")}</strong>
                <p>
                  {t(
                    "서버가 음성을 전사한 뒤 결정·액션·이슈·리스크를 추출합니다. 처리에는 몇 분이 걸릴 수 있습니다.",
                  )}
                </p>
              </div>
            </div>

            {!isServerOnline ? (
              <div className="audio-upload-offline-note" role="status">
                <AlertTriangle aria-hidden="true" size={15} />
                <span>{t("서버에 다시 연결한 뒤 전사를 시작할 수 있습니다")}</span>
              </div>
            ) : null}

            <div className="audio-upload-safety-note">
              <AudioLines aria-hidden="true" size={15} />
              <span>
                {t(
                  "CLOVA 회의 음성 계약에서 지원하는 형식만 선택할 수 있습니다.",
                )}
              </span>
              <CalendarDays aria-hidden="true" size={15} />
            </div>
          </LayoutContent>
        }
        footer={
          <LayoutFooter hasDivider>
            <div className="audio-upload-dialog-actions">
              <Button
                isDisabled={isSubmitting}
                label={t("취소")}
                onClick={onCancel}
                variant="ghost"
              />
              <Button
                icon={<AudioLines size={15} />}
                isDisabled={
                  !isServerOnline ||
                  !draft ||
                  (Boolean(draft.date) && !isISODate(draft.date))
                }
                isLoading={isSubmitting}
                label={t(isSubmitting ? "업로드 중" : "전사 시작")}
                onClick={onConfirm}
                tooltip={
                  !isServerOnline
                    ? t("서버에 다시 연결한 뒤 전사를 시작할 수 있습니다")
                    : undefined
                }
                variant="primary"
              />
            </div>
          </LayoutFooter>
        }
      />
    </Dialog>
  );
}
