import { test, expect } from "@playwright/test";
test("named read-only web container completes explicitly offline repair and exports evidence", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByText(/Offline preview · fixed model/)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Diagnose experiment" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Diagnose experiment" }).click();
  await expect(
    page.getByRole("heading", { name: "Repair independently verified" }),
  ).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Original and final/ }),
  ).toBeVisible();
  await page.getByRole("tab", { name: "Checks" }).click();
  await expect(
    page.getByRole("cell", { name: "Pass", exact: true }),
  ).toHaveCount(26);
  await page.getByRole("tab", { name: "Evidence" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download evidence ZIP" }).click();
  expect((await download).suggestedFilename()).toMatch(
    /^experiment-.+-evidence.zip$/,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});
