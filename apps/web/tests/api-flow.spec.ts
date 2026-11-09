import { test, expect } from "@playwright/test";
// Real FastAPI cookies/CSRF, Doctor orchestration, trusted checker and owned ZIP.
// Execution/model are explicitly offline numeric fixtures. No candidate runs on this host.
test("real API repairs a fixture, verifies healthy control, restores reports and denies foreign sessions", async ({
  page,
  context,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Diagnose experiment" }),
  ).toBeEnabled();
  for (const fixture of ["An unstable time step", "A healthy control"]) {
    await page
      .getByRole("button", {
        name: new RegExp(`^(REPAIR CHALLENGE|CONTROL).*${fixture}`),
      })
      .click();
    await page.getByRole("button", { name: "Diagnose experiment" }).click();
    await expect(
      page.getByRole("heading", {
        name:
          fixture === "A healthy control"
            ? "Healthy experiment verified"
            : "Repair independently verified",
      }),
    ).toBeVisible();
    await expect(
      page.getByText("offline-e2e fixture", { exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: /Original and final/ }),
    ).toBeVisible();
    await page.getByRole("tab", { name: "Checks" }).click();
    await expect(
      page.getByRole("cell", { name: "Pass", exact: true }),
    ).toHaveCount(fixture === "A healthy control" ? 22 : 26);
    const experiment = new URL(page.url()).searchParams.get("experiment");
    const response = await page.request.get(
      `/api/v1/experiments/${experiment}/evidence`,
    );
    expect(response.status()).toBe(200);
    expect((await response.body()).subarray(0, 2).toString()).toBe("PK");
  }
  const cookies = await context.cookies();
  expect(cookies.find((c) => c.name === "ed_session")?.httpOnly).toBe(true);
  const experiment = new URL(page.url()).searchParams.get("experiment");
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Healthy experiment verified" }),
  ).toBeVisible();
  const other = await context.browser()!.newContext();
  const foreign = await other.newPage();
  await foreign.goto("/");
  await expect(
    foreign.getByRole("button", { name: "Diagnose experiment" }),
  ).toBeEnabled();
  expect(
    (
      await foreign.request.get(`/api/v1/experiments/${experiment}/view`)
    ).status(),
  ).toBe(404);
  expect(
    (
      await foreign.request.get(`/api/v1/experiments/${experiment}/evidence`)
    ).status(),
  ).toBe(404);
  await other.close();
});
