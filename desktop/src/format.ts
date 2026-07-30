const PAIM_NAIVE_DATE_TIME =
  /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/;

/**
 * MySQL DATETIME values in older PaiM API responses are UTC but omit a zone.
 * Preserve explicit RFC 3339 offsets and interpret only zone-less date-times
 * as UTC. Date-only business fields such as due_date must not use this parser.
 */
export function parsePaimTimestamp(value: string | null | undefined) {
  const normalized = value?.trim();
  if (!normalized) return NaN;

  const timestamp = Date.parse(
    PAIM_NAIVE_DATE_TIME.test(normalized)
      ? `${normalized.replace(" ", "T")}Z`
      : normalized,
  );
  return Number.isFinite(timestamp) ? timestamp : NaN;
}

// 현재 시각 기준으로 채팅/이벤트 목록에 보여줄 짧은 상대 시간을 만든다.
export function formatRelativeAge(createdAt: number, language: "en" | "ko" = "ko") {
  const diffMs = Math.max(0, Date.now() - createdAt);
  const minuteMs = 60 * 1000;
  const hourMs = 60 * minuteMs;
  const dayMs = 24 * hourMs;
  const weekMs = 7 * dayMs;

  if (diffMs < minuteMs) {
    return language === "en" ? "now" : "방금";
  }

  if (diffMs < hourMs) {
    return language === "en" ? `${Math.floor(diffMs / minuteMs)}m` : `${Math.floor(diffMs / minuteMs)}분`;
  }

  if (diffMs < dayMs) {
    return language === "en" ? `${Math.floor(diffMs / hourMs)}h` : `${Math.floor(diffMs / hourMs)}시간`;
  }

  if (diffMs < weekMs) {
    return language === "en" ? `${Math.floor(diffMs / dayMs)}d` : `${Math.floor(diffMs / dayMs)}일`;
  }

  return language === "en" ? `${Math.floor(diffMs / weekMs)}w` : `${Math.floor(diffMs / weekMs)}주`;
}
