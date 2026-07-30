import assert from "node:assert/strict";
import test from "node:test";

import { normalizeApiProjectSetup } from "../src/projectSetup.ts";
import { isProjectSetupComplete } from "../src/types.ts";

function projectWithSetup(setup) {
  return {
    id: "project-test",
    name: "Test Project",
    createdAt: 0,
    sessions: [],
    ...setup,
  };
}

test("legacy project without setup fields opens project detail", () => {
  const createdAt = "2026-07-01T12:00:00.000";
  const setup = normalizeApiProjectSetup({ created_at: createdAt });

  assert.equal(setup.setupCompletedAt, Date.parse(`${createdAt}Z`));
  assert.equal(setup.setupMode, "existing");
  assert.equal(isProjectSetupComplete(projectWithSetup(setup)), true);
});

test("explicit draft remains in project setup", () => {
  const setup = normalizeApiProjectSetup(
    { setup_status: "draft" },
    {
      setupCompletedAt: Date.parse("2026-07-01T12:00:00.000Z"),
      setupMode: "chat_only",
    },
  );

  assert.equal(setup.setupCompletedAt, undefined);
  assert.equal(setup.setupMode, undefined);
  assert.equal(isProjectSetupComplete(projectWithSetup(setup)), false);
});

test("explicit ready opens project detail", () => {
  const completedAt = "2026-07-02T09:30:00.000Z";
  const setup = normalizeApiProjectSetup({
    setup_status: "ready",
    setup_mode: "analyzed",
    setup_completed_at: completedAt,
  });

  assert.equal(setup.setupCompletedAt, Date.parse(completedAt));
  assert.equal(setup.setupMode, "analyzed");
  assert.equal(isProjectSetupComplete(projectWithSetup(setup)), true);
});

test("legacy reconciliation preserves local completion after setup endpoint 404", () => {
  const localSetup = {
    setupCompletedAt: Date.parse("2026-07-03T04:20:00.000Z"),
    setupMode: "chat_only",
  };
  const setup = normalizeApiProjectSetup(
    { created_at: "2026-06-30T00:00:00.000Z" },
    localSetup,
  );

  assert.deepEqual(setup, localSetup);
  assert.equal(isProjectSetupComplete(projectWithSetup(setup)), true);
});
