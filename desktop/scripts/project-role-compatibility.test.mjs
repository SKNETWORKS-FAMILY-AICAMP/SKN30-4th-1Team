import assert from "node:assert/strict";
import test from "node:test";

import { fillMissingProjectRoles } from "../src/projectRoleCompatibility.ts";

const currentUser = { id: 7 };

test("server-provided roles remain authoritative without member requests", async () => {
  const projects = [
    { id: 1, current_user_role: "owner", name: "Owned" },
    { id: 2, current_user_role: "member", name: "Shared" },
    { id: 3, current_user_role: null, name: "Explicitly unavailable" },
  ];
  let fetchCount = 0;

  const result = await fillMissingProjectRoles(
    projects,
    currentUser,
    async () => {
      fetchCount += 1;
      return [{ user_id: 7, role: "viewer" }];
    },
  );

  assert.equal(fetchCount, 0);
  assert.deepEqual(result, projects);
  assert.equal(result[0], projects[0]);
  assert.equal(result[1], projects[1]);
  assert.equal(result[2], projects[2]);
});

test("only omitted roles are resolved from the current user's member row", async () => {
  const requestedProjectIds = [];
  const projects = [
    { id: 11, name: "Legacy owner" },
    { id: 12, current_user_role: "member", name: "Modern member" },
    { id: 13, name: "Legacy member" },
  ];

  const result = await fillMissingProjectRoles(
    projects,
    currentUser,
    async (projectId) => {
      requestedProjectIds.push(projectId);
      return projectId === 11
        ? [
            { user_id: 7, role: "owner" },
            { user_id: 8, role: "member" },
          ]
        : [
            { user_id: 8, role: "owner" },
            { user_id: 7, role: "member" },
          ];
    },
  );

  assert.deepEqual(requestedProjectIds.sort((a, b) => a - b), [11, 13]);
  assert.equal(result[0].current_user_role, "owner");
  assert.equal(result[1].current_user_role, "member");
  assert.equal(result[1], projects[1]);
  assert.equal(result[2].current_user_role, "member");
});

test("a missing current-user member row resolves to explicit null", async () => {
  const result = await fillMissingProjectRoles(
    [{ id: 21, name: "Inconsistent legacy project" }],
    currentUser,
    async () => [{ user_id: 8, role: "owner" }],
  );

  assert.equal(result[0].current_user_role, null);
});

test("signed-out compatibility leaves omitted roles untouched", async () => {
  let fetchCount = 0;
  const projects = [{ id: 31, name: "Legacy project" }];

  const result = await fillMissingProjectRoles(
    projects,
    null,
    async () => {
      fetchCount += 1;
      return [];
    },
  );

  assert.equal(fetchCount, 0);
  assert.equal(result[0], projects[0]);
  assert.equal(result[0].current_user_role, undefined);
});
