// SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
// SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
// SPDX-License-Identifier: Apache-2.0

import { expect, Page, test } from "@playwright/test";
import { API_BASE } from "./helpers";

const PASSWORD = "E2e-Team-Invite!42";
const suffix = Date.now().toString(36);

type Principal = { id: string; email: string; role: string; token: string };
type Team = { id: string; handle: string };

let adminToken: string;
let owner: Principal;
let outsider: Principal;
let teamReviewer: Principal;
let globalReviewer: Principal;
let privateTeam: Team;
let publicTeam: Team;
let inviteToken: string;

async function adminLogin(): Promise<string> {
  const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer e2e-shareable-admin-${suffix}-${crypto.randomUUID()}`,
    },
    body: JSON.stringify({
      email: process.env.DEMO_ADMIN_EMAIL ?? "admin@demo.example",
      password: process.env.DEMO_ADMIN_PASSWORD ?? "admin-changeme",
    }),
  });
  const body = await response.json();
  if (!response.ok || !body.access_token) {
    throw new Error(`Admin login failed: ${response.status} ${JSON.stringify(body)}`);
  }
  return body.access_token;
}

async function api(path: string, token: string, method = "GET", body?: unknown) {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(`${method} ${path} failed: ${response.status} ${await response.text()}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

async function createUser(label: string, role = "user"): Promise<Principal> {
  const email = `e2e.${label}.${suffix}@example.test`;
  const created = await api("/api/v1/admin/users", adminToken, "POST", {
    email,
    name: `E2E ${label}`,
    username: `e2e-${label}-${suffix}`.slice(0, 32),
    role,
    password: PASSWORD,
  });
  const login = await api("/api/v1/auth/login", `e2e-${label}-${suffix}`, "POST", {
    email,
    password: PASSWORD,
  });
  return { id: created.id, email, role, token: login.access_token };
}

async function loginAs(page: Page, principal: Principal) {
  await page.goto("/");
  await page.evaluate(
    ([token, role]) => {
      sessionStorage.setItem("observal_access_token", token);
      localStorage.setItem("observal_user_role", role);
    },
    [principal.token, principal.role],
  );
  await page.reload();
}

async function pendingRequest(teamId: string, userId: string) {
  const requests = await api(`/api/v1/teams/${teamId}/join-requests?status=pending`, owner.token);
  const request = requests.find((row: { user_id: string }) => row.user_id === userId);
  if (!request) throw new Error(`No pending request for ${userId}`);
  return request;
}

test.describe("shareable teamspace links", () => {
  test.describe.configure({ mode: "serial" });

  test.beforeAll(async () => {
    adminToken = await adminLogin();
    owner = await createUser("owner");
    outsider = await createUser("outsider");
    teamReviewer = await createUser("team-reviewer");
    globalReviewer = await createUser("global-reviewer", "reviewer");

    privateTeam = await api("/api/v1/teams", owner.token, "POST", {
      name: "E2E Private Team",
      handle: `e2e-private-${suffix}`.slice(0, 32),
      visibility: "private",
    });
    publicTeam = await api("/api/v1/teams", owner.token, "POST", {
      name: "E2E Public Team",
      handle: `e2e-public-${suffix}`.slice(0, 32),
      visibility: "public",
    });
    await api(`/api/v1/teams/${privateTeam.id}/members`, owner.token, "POST", {
      user_id: teamReviewer.id,
      role: "reviewer",
    });
    const invite = await api(`/api/v1/teams/${privateTeam.id}/invites`, owner.token, "POST", {
      name: "E2E browser invite",
      expires_in_days: 1,
      max_uses: 5,
    });
    inviteToken = invite.token;
  });

  test.afterAll(async () => {
    if (privateTeam?.id) await api(`/api/v1/teams/${privateTeam.id}`, owner.token, "DELETE");
    if (publicTeam?.id) await api(`/api/v1/teams/${publicTeam.id}`, owner.token, "DELETE");
    adminToken = await adminLogin();
    for (const principal of [owner, outsider, teamReviewer, globalReviewer]) {
      if (principal?.id) await api(`/api/v1/admin/users/${principal.id}`, adminToken, "DELETE");
    }
  });

  test("private invite preserves login destination and durable request state", async ({ page }) => {
    await page.route("**/api/v1/auth/login", async (route) => {
      await route.continue({
        headers: { ...route.request().headers(), Authorization: `Bearer e2e-browser-${suffix}` },
      });
    });
    await page.goto(`/team-invites/${inviteToken}`);
    await expect(page).toHaveURL(new RegExp(`/login\\?next=%2Fteam-invites%2F${inviteToken}`));
    await page.getByLabel("Email").fill(outsider.email);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: /sign in/i }).click();
    await expect(page).toHaveURL(new RegExp(`/team-invites/${inviteToken}$`));

    await page.getByRole("button", { name: "Request access", exact: true }).click();
    await expect(page.getByText(/access requested/i)).toBeVisible();
    await page.reload();
    await expect(page.getByText(/access requested/i)).toBeVisible();

    await page.getByRole("button", { name: /withdraw request/i }).click();
    await expect(page.getByText(/withdrew this access request/i)).toBeVisible();
    await page.reload();
    await expect(page.getByText(/withdrew this access request/i)).toBeVisible();
  });

  test("private invite approval survives refresh and opens the teamspace", async ({ page }) => {
    await loginAs(page, outsider);
    await page.goto(`/team-invites/${inviteToken}`);
    await page.getByRole("button", { name: /request access again/i }).click();
    await expect(page.getByText(/access requested/i)).toBeVisible();

    const request = await pendingRequest(privateTeam.id, outsider.id);
    await api(`/api/v1/teams/${privateTeam.id}/join-requests/${request.id}/approve`, owner.token, "POST");
    await page.reload();
    await expect(page.getByText(/access approved/i)).toBeVisible();
    await page.getByRole("link", { name: /open teamspace/i }).click();
    await expect(page).toHaveURL(new RegExp(`/teamspaces/${privateTeam.handle}$`));
    await expect(page.getByRole("tab", { name: /members/i })).toBeVisible();
  });

  test("public join request becomes membership after owner approval", async ({ page }) => {
    await loginAs(page, outsider);
    await page.goto(`/teamspaces/${publicTeam.handle}`);
    await page.getByRole("button", { name: /request to join/i }).click();
    await page.getByRole("button", { name: /send request/i }).click();
    await expect(page.getByText(/request pending/i)).toBeVisible();

    const request = await pendingRequest(publicTeam.id, outsider.id);
    await api(`/api/v1/teams/${publicTeam.id}/join-requests/${request.id}/approve`, owner.token, "POST");
    await page.reload();
    await expect(page.getByRole("tab", { name: /members/i })).toBeVisible();
    await expect(page.getByText(/request pending/i)).toHaveCount(0);
  });

  test("only owners and admins control private visibility", async ({ page }) => {
    await loginAs(page, teamReviewer);
    await page.goto(`/teamspaces/${privateTeam.handle}`);
    await expect(page.getByRole("button", { name: /make public/i })).toHaveCount(0);

    const reviewerChange = await fetch(`${API_BASE}/api/v1/teams/${privateTeam.id}/visibility`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${teamReviewer.token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ visibility: "public" }),
    });
    expect(reviewerChange.status).toBe(403);

    const reviewerTeams = await api("/api/v1/teams/all", globalReviewer.token);
    expect(reviewerTeams.some((team: { id: string }) => team.id === privateTeam.id)).toBe(false);
    await loginAs(page, globalReviewer);
    await page.goto(`/teamspaces/${privateTeam.handle}`);
    await expect(page.getByText(/no teamspace named/i)).toBeVisible();
  });

  test("canonical component type route resolves the correct collection", async ({ page }) => {
    let resolveUrl = "";
    await page.route("**/api/v1/registry/resolve?*", async (route) => {
      resolveUrl = route.request().url();
      await route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ detail: "Not found" }) });
    });
    await loginAs(page, owner);
    await page.goto("/components/skills/example-team/example-skill");
    await expect(page).toHaveURL(/\/components\/skills\/example-team\/example-skill$/);
    await expect(page.getByText("Component not found")).toBeVisible();
    const query = new URL(resolveUrl).searchParams;
    expect(query.get("type")).toBe("skill");
    expect(query.get("identifier")).toBe("example-team/example-skill");
  });
});
