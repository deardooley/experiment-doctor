import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";
const id = "11111111-1111-4111-8111-111111111111";
const fileId = "22222222-2222-4222-8222-222222222222";
const csv = "t,x\n0,1\n1,0.367879\n5,0.006738\n";
const artifact = {
  id: fileId,
  name: "trajectory.csv",
  label: "Original · Primary · trajectory.csv",
  size: Buffer.byteLength(csv),
  sha256: createHash("sha256").update(csv).digest("hex"),
};
async function setup(
  page: import("@playwright/test").Page,
  status = "VERIFIED_REPAIR",
) {
  let accepted = false;
  let cancelled = false;
  let reads = 0;
  const execution = {
    job_id: id,
    status: "SUCCEEDED",
    exit_code: 0,
    reason: "SUCCESS",
    cleanup: "removed",
  };
  const attempt = (revision: number) => ({
    revision,
    parameters: { dt: revision ? 0.01 : 2.5, k: 1, x0: 1, t_end: 5 },
    source: 'print("<script>window.injected=true</script>")',
    jobs: [{ job_id: id, role: "primary", execution, artifacts: [artifact] }],
    verification: {
      verdict: revision ? "PASS" : "FAIL",
      checks: [
        {
          key: "primary.analytic_error",
          passed: !!revision,
          measured: revision ? 0.0018 : 2.24,
          tolerance: 0.01,
        },
      ],
      evidence: [],
      limitations: [],
      spec_hash: "a".repeat(64),
      verifier_hash: "b".repeat(64),
      spec_version: "decay-v1",
    },
  });
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body: unknown;
    if (path.endsWith("/session"))
      body = { csrf_token: "test-csrf", expires_at: Date.now() / 1000 + 86400 };
    else if (path.endsWith("/apps"))
      body = ["decay-coarse-step", "decay-wrong-sign", "decay-healthy"].map(
        (id) => ({
          id,
          version: "1",
          verifier_version: "decay-v1",
          input_schema: {},
        }),
      );
    else if (
      path === "/api/v1/experiments" &&
      route.request().method() === "POST"
    ) {
      expect(route.request().headers()["x-csrf-token"]).toBe("test-csrf");
      accepted = true;
      body = { experiment_id: id };
    } else if (path === "/api/v1/experiments") body = [];
    else if (path.endsWith("/cancel")) {
      cancelled = true;
      body = { cancel_requested: true };
    } else if (path.endsWith("/view")) {
      reads++;
      const state = cancelled
        ? "CANCELLED"
        : status === "RUNNING"
          ? "RUNNING"
          : reads < 2
            ? "RUNNING"
            : status;
      body = {
        experiment_id: id,
        fixture_id: "decay-coarse-step",
        kind: "diagnosis",
        status: state,
        created_at: 1700000000,
        cancel_requested: cancelled,
        artifacts: state === "RUNNING" ? [] : [artifact],
        report:
          state === "RUNNING"
            ? null
            : {
                outcome: state,
                hypothesis:
                  'Reduce the time step. <img src=x onerror="window.injected=true">',
                patch: "--- original\n+++ candidate\n-dt = 2.5\n+dt = 0.01",
                attempts: ["INCOMPLETE", "CANCELLED"].includes(state)
                  ? []
                  : [attempt(0), attempt(1)],
                provenance: {
                  mode: "offline-e2e fixture",
                  model_id: "deterministic test fixture",
                },
                limitations: [
                  "Deterministic browser fixture; no live model or sandbox execution.",
                ],
              },
      };
    } else if (path.endsWith("/events"))
      body =
        url.searchParams.get("after") === "0"
          ? [
              {
                cursor: 1,
                at: 1700000000,
                kind: "ATTEMPT_STARTED",
                data: { revision: 0 },
              },
              { cursor: 2, at: 1700000001, kind: "MODEL_REQUESTED", data: {} },
            ]
          : [];
    else if (path.includes("/artifacts/"))
      return route.fulfill({
        body: csv,
        contentType: "application/octet-stream",
      });
    else if (path.endsWith("/evidence"))
      return route.fulfill({
        body: Buffer.from("ZIP fixture"),
        contentType: "application/zip",
      });
    else return route.fulfill({ status: 404, body: "not found" });
    await route.fulfill({ json: body });
  });
  await page.route("**/health/ready", (r) =>
    r.fulfill({ json: { status: "ready" } }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Diagnose experiment" }),
  ).toBeEnabled();
  return () => accepted;
}
test("visitor selects fixture, follows timeline, inspects patch plots checks and exports", async ({
  page,
}) => {
  const accepted = await setup(page);
  await page.getByRole("button", { name: "Diagnose experiment" }).click();
  await expect(
    page.getByRole("heading", { name: "Repair independently verified" }),
  ).toBeVisible();
  expect(accepted()).toBe(true);
  await expect(
    page.getByText("Original experiment", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("offline-e2e fixture", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Original and final/ }),
  ).toBeVisible();
  await page.getByRole("slider", { name: "Inspect time" }).fill("1");
  await expect(page.getByText("Inspect time: 1.00 s")).toBeVisible();
  await page.getByRole("tab", { name: "Patch", exact: true }).click();
  await expect(page.getByLabel("Unified patch")).toContainText("+dt = 0.01");
  await page.getByRole("tab", { name: "Patch" }).press("ArrowRight");
  await expect(page.getByRole("tab", { name: "Checks" })).toBeFocused();
  await expect(
    page.getByRole("cell", { name: "2.24", exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Provenance" }).click();
  await expect(
    page.getByText("deterministic test fixture", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Evidence" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download evidence ZIP" }).click();
  expect((await download).suggestedFilename()).toBe(
    `experiment-${id}-evidence.zip`,
  );
  expect(
    await page.evaluate(() => Reflect.get(window, "injected")),
  ).toBeUndefined();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
test("incomplete report never implies verified evidence", async ({ page }) => {
  await setup(page, "INCOMPLETE");
  await page.getByRole("button", { name: "Diagnose experiment" }).click();
  await expect(
    page.getByRole("heading", { name: "Experiment incomplete" }),
  ).toBeVisible();
  await expect(
    page.getByText("Numeric evidence is unavailable.", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Checks" }).click();
  await expect(
    page.getByText("No independent checks are available."),
  ).toBeVisible();
});
test("cancellation remains an explicit incomplete scientific result", async ({
  page,
}) => {
  await setup(page, "RUNNING");
  await page.getByRole("button", { name: "Diagnose experiment" }).click();
  await page
    .getByRole("button", { name: "Cancel experiment", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Experiment cancelled" }),
  ).toBeVisible();
});
test("lost session exposes reconnect without automatically resubmitting", async ({
  page,
}) => {
  await setup(page);
  await page.route("**/api/v1/experiments", (r) =>
    r.fulfill({ status: 401, json: { detail: "expired" } }),
  );
  await page.getByRole("button", { name: "Diagnose experiment" }).click();
  await expect(page.getByRole("alert")).toContainText("session expired");
  await expect(page.getByRole("button", { name: "Reconnect" })).toBeVisible();
});

test("failed repair remains visibly unverified", async ({ page }) => {
  await setup(page, "NOT_REPAIRED");
  await page.getByRole("button", { name: "Diagnose experiment" }).click();
  await expect(
    page.getByRole("heading", { name: "No verified repair" }),
  ).toBeVisible();
  await expect(page.locator(".verdict.verified")).toHaveCount(0);
});
test("corrupt trajectory never becomes a plotted curve", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/artifacts/*", (r) =>
    r.fulfill({
      body: '<svg onload="window.injected=true"/>',
      contentType: "application/octet-stream",
    }),
  );
  await page.getByRole("button", { name: "Diagnose experiment" }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Evidence integrity check failed",
  );
  await expect(
    page.getByRole("img", { name: /Original and final/ }),
  ).toHaveCount(0);
  expect(
    await page.evaluate(() => Reflect.get(window, "injected")),
  ).toBeUndefined();
});
