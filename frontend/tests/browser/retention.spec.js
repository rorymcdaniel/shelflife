import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const scripts = Object.fromEntries(
  ["common", "seerr", "jellyfin"].map((name) => [
    name,
    readFileSync(
      new URL(`../../../backend/shelflife/web/${name}.js`, import.meta.url),
      "utf8",
    ),
  ]),
);

async function bridge(page, name, hash = "") {
  await page.route("**/fixture", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: '<!doctype html><html><head></head><body><button id="request">Request</button><div class="detailPage"><div class="detailButtons"></div></div></body></html>',
    }),
  );
  await page.goto("/fixture" + hash);
  await page.addScriptTag({ content: scripts.common });
  await page.addScriptTag({ content: scripts[name] });
}

test("Seerr fetch shows default 60 days and sends the choice with original request fields", async ({
  page,
}) => {
  let submitted;
  await page.route("**/api/v1/request", (route) => {
    submitted = route.request();
    return route.fulfill({ json: { id: 42 } });
  });
  await bridge(page, "seerr");
  await page.evaluate(() => {
    document.querySelector("#request").onclick = () => {
      window.result = fetch("/api/v1/request", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mediaType: "movie", mediaId: 603 }),
      });
    };
  });
  await page.getByRole("button", { name: "Request", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "60 days after they become available",
  );
  expect(submitted).toBeUndefined();
  await expect(page.getByLabel("Retention period")).toHaveValue("60");
  await page.getByRole("button", { name: "Request with this choice" }).click();
  await expect
    .poll(() => submitted?.postDataJSON())
    .toEqual({ mediaType: "movie", mediaId: 603, shelflifeDays: 60 });
  expect(submitted.headers()["x-shelflife-intent"]).toBe("keep");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("Seerr XHR supports forever and cancellation sends nothing", async ({
  page,
}) => {
  const requests = [];
  await page.route("**/api/v1/request", (route) => {
    requests.push(route.request().postDataJSON());
    return route.fulfill({ json: { id: 42 } });
  });
  await bridge(page, "seerr");
  const start = () =>
    page.evaluate(() => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/v1/request");
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.send(JSON.stringify({ mediaType: "tv", mediaId: 100, seasons: [2] }));
    });
  await start();
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  expect(requests).toHaveLength(0);
  await start();
  await page.getByLabel("Retention period").selectOption("forever");
  await page.getByRole("button", { name: "Request with this choice" }).click();
  await expect
    .poll(() => requests)
    .toEqual([
      { mediaType: "tv", mediaId: 100, seasons: [2], shelflifeDays: null },
    ]);
});

test("Jellyfin Keep confirms success and reports failures without pretending a keep saved", async ({
  page,
}) => {
  const id = "a".repeat(32);
  let failing = true;
  await page.route("**/shelflife/jellyfin/**", (route) =>
    route.request().method() === "GET"
      ? route.fulfill({
          json: {
            title: "The Matrix",
            permanent: false,
            expires_at: "2027-01-16T00:00:00Z",
          },
        })
      : failing
        ? route.fulfill({
            status: 503,
            json: { detail: "Connection unavailable; please retry." },
          })
        : route.fulfill({
            json: { title: "The Matrix", permanent: true, expires_at: null },
          }),
  );
  await page.addInitScript(() => {
    window.ApiClient = { accessToken: () => "user-access-token" };
  });
  await bridge(page, "jellyfin", "#/details?id=" + id);
  await page.getByRole("button", { name: "Keep…", exact: true }).click();
  await page.getByLabel("Retention period").selectOption("forever");
  await page.getByRole("button", { name: "Keep", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Connection unavailable");
  failing = false;
  await page.getByRole("button", { name: "Keep…", exact: true }).click();
  await page.getByLabel("Retention period").selectOption("forever");
  await page.getByRole("button", { name: "Keep", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Kept permanently", exact: true }),
  ).toBeDisabled();
  await page.evaluate(() => {
    location.hash = "#/home";
  });
  await expect(page.locator("[data-shelflife]")).toHaveCount(0);
});

test("mobile shared library lets an ordinary user keep a title and hides admin controls", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  let permanent = false;
  await page.route("**/api/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/setup/status")
      return route.fulfill({ json: { needs_setup: false } });
    if (path === "/api/account/me")
      return route.fulfill({
        json: {
          id: 2,
          username: "friend",
          role: "user",
          allowed_pages: null,
          permissions: [],
          date_format: "yyyy-MM-dd",
        },
      });
    if (path === "/api/retention/1/keep") {
      permanent = true;
      return route.fulfill({ json: { permanent: true } });
    }
    if (path === "/api/retention")
      return route.fulfill({
        json: {
          total: 1,
          settings: {
            enabled_at: "2026-11-17T00:00:00Z",
            preview: true,
            paused: false,
            timezone: "UTC",
          },
          items: [
            {
              id: 1,
              title: "The Matrix",
              kind: "movie",
              season_number: -1,
              permanent,
              expires_at: permanent ? null : "2027-01-16T00:00:00Z",
              available_at: "2026-11-17T00:00:00Z",
              deleted_at: null,
              last_error: null,
            },
          ],
        },
      });
    return route.fulfill({ json: {} });
  });
  await page.goto("/#/retention");
  await expect(
    page.getByRole("heading", { name: "Make room. Keep what matters." }),
  ).toBeVisible();
  await expect(page.getByText("Manage library retention")).toHaveCount(0);
  await page.getByRole("button", { name: "Keep…", exact: true }).click();
  await page.getByLabel("Keep for at least").selectOption("forever");
  await page.getByRole("button", { name: "Keep", exact: true }).click();
  await expect(page.getByText("This title has a home here.")).toBeVisible();
  if (process.env.SHELFLIFE_SCREENSHOT)
    await page.screenshot({
      path: process.env.SHELFLIFE_SCREENSHOT,
      fullPage: true,
    });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
