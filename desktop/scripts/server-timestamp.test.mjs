import assert from "node:assert/strict";
import test from "node:test";

import { parsePaimTimestamp } from "../src/format.ts";

test("legacy zone-less ISO date-time is interpreted as UTC", () => {
  assert.equal(
    parsePaimTimestamp("2026-07-29T08:15:30.123456"),
    Date.parse("2026-07-29T08:15:30.123456Z"),
  );
});

test("legacy MySQL date-time with a space is interpreted as UTC", () => {
  assert.equal(
    parsePaimTimestamp("2026-07-29 08:15:30"),
    Date.UTC(2026, 6, 29, 8, 15, 30),
  );
});

test("explicit RFC 3339 offsets remain authoritative", () => {
  const timestamp = "2026-07-29T17:15:30+09:00";
  assert.equal(parsePaimTimestamp(timestamp), Date.parse(timestamp));
});

test("missing and invalid values return NaN", () => {
  assert.equal(Number.isNaN(parsePaimTimestamp(undefined)), true);
  assert.equal(Number.isNaN(parsePaimTimestamp("not-a-date")), true);
});
