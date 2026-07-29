import assert from "node:assert/strict";
import test from "node:test";

import {
  INITIAL_WORKSPACE_ROUTE,
  reduceWorkspaceRoute,
} from "../src/workspaceRoute.ts";

test("project detail navigation can reset the active tab atomically", () => {
  const current = {
    ...INITIAL_WORKSPACE_ROUTE,
    mainView: "project-management",
    projectDetailTab: "activity",
  };

  assert.deepEqual(
    reduceWorkspaceRoute(current, {
      type: "open-project-detail",
      tab: "overview",
    }),
    {
      ...current,
      mainView: "project-detail",
      projectDetailTab: "overview",
    },
  );
});

test("returning to project detail preserves its previous tab by default", () => {
  const current = {
    ...INITIAL_WORKSPACE_ROUTE,
    mainView: "project-management",
    projectDetailTab: "files",
  };

  assert.deepEqual(
    reduceWorkspaceRoute(current, { type: "open-project-detail" }),
    {
      ...current,
      mainView: "project-detail",
    },
  );
});

test("management navigation and section selection share one route state", () => {
  const opened = reduceWorkspaceRoute(INITIAL_WORKSPACE_ROUTE, {
    type: "open-project-management",
    section: "members",
  });

  assert.equal(opened.mainView, "project-management");
  assert.equal(opened.projectManagementSection, "members");
  assert.equal(
    reduceWorkspaceRoute(opened, {
      type: "set-project-management-section",
      section: "github",
    }).projectManagementSection,
    "github",
  );
});

test("member management remembers whether it was opened from detail or management", () => {
  const route = reduceWorkspaceRoute(INITIAL_WORKSPACE_ROUTE, {
    type: "open-members",
    returnView: "project-management",
  });

  assert.equal(route.mainView, "members");
  assert.equal(route.membersReturnView, "project-management");
});
