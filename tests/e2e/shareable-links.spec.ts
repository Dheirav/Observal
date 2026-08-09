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
let superAdminToken: string;
let owner: Principal;
let outsider: Principal;
let teamReviewer: Principal;
let globalReviewer: Principal;
let privateTeam: Team;
let publicTeam: Team;
let personalTeam: Team;
let inviteToken: string;

async function demoLogin(role: "admin" | "super_admin"): Promise<string> {
  const superAdmin = role === "super_admin";
  const email = superAdmin
    ? (process.env.DEMO_SUPER_ADMIN_EMAIL ?? "super@demo.example")
    : (process.env.DEMO_ADMIN_EMAIL ?? "admin@demo.example");
  const password = superAdmin
    ? (process.env.DEMO_SUPER_ADMIN_PASSWORD ?? "super-changeme")
    : (process.env.DEMO_ADMIN_PASSWORD ?? "admin-changeme");
  const response = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer e2e-shareable-${role}-${suffix}-${crypto.randomUUID()}`,
    },
    body: JSON.stringify({ email, password }),
  });
  const body = await response.json();
  if (!response.ok || !body.access_token) {
    throw new Error(`${role} login failed: ${response.status} ${JSON.stringify(body)}`);
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
    adminToken = await demoLogin("admin");
    superAdminToken = await demoLogin("super_admin");
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
    personalTeam = await api("/api/v1/teams/claim-personal", outsider.token, "POST");
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
    if (personalTeam?.id) await api(`/api/v1/teams/${personalTeam.id}`, outsider.token, "DELETE");
    adminToken = await demoLogin("admin");
    for (const principal of [owner, outsider, teamReviewer, globalReviewer]) {
      if (principal?.id) await api(`/api/v1/admin/users/${principal.id}`, adminToken, "DELETE");
    }
  });

  test("claiming a personal teamspace keeps public teamspaces visible", async ({ page }) => {
    await loginAs(page, outsider);
    await page.goto("/teamspaces");

    await expect(page.getByText(personalTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(publicTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(privateTeam.handle, { exact: true })).toHaveCount(0);
  });

  test("personal teamspaces can be deleted but never joined or left", async ({ page }) => {
    await loginAs(page, outsider);
    await page.goto(`/teamspaces/${personalTeam.handle}`);

    await expect(page.getByRole("button", { name: /delete/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /request to join/i })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /leave/i })).toHaveCount(0);
  });

  for (const role of ["admin", "super_admin"] as const) {
    test(`${role} visibility does not masquerade as team membership`, async ({ page }) => {
      const token = role === "admin" ? adminToken : superAdminToken;
      await loginAs(page, { id: role, email: "", role, token });
      await page.goto("/teamspaces");
      await expect(page.getByText(publicTeam.handle, { exact: true })).toBeVisible();
      await expect(page.getByText(privateTeam.handle, { exact: true })).toBeVisible();
      await expect(page.getByText(personalTeam.handle, { exact: true })).toBeVisible();

      await page.goto(`/teamspaces/${privateTeam.handle}`);
      await expect(page.getByText("admin access", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: /leave/i })).toHaveCount(0);
      await page.getByRole("button", { name: /request to join/i }).click();
      await page.getByRole("button", { name: /send request/i }).click();
      await expect(page.getByText(/request pending/i)).toBeVisible();
      await page.getByRole("button", { name: /withdraw/i }).click();
      await expect(page.getByRole("button", { name: /request to join/i })).toBeVisible();

      await page.goto(`/teamspaces/${personalTeam.handle}`);
      await expect(page.getByText("admin access", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: /request to join/i })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /leave/i })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /delete/i })).toBeVisible();
    });
  }

  test("direct private members opening an invite are recognized", async ({ page }) => {
    await loginAs(page, teamReviewer);
    await page.goto(`/team-invites/${inviteToken}`);

    await expect(page.getByText(/already a member/i)).toBeVisible();
    await expect(page.getByRole("link", { name: /open teamspace/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /request to join/i })).toHaveCount(0);
  });

  test("invalid private invite tokens reveal no team metadata", async ({ page }) => {
    await loginAs(page, outsider);
    await page.goto(`/team-invites/not-a-real-${suffix}`);

    await expect(page.getByText(/invite unavailable/i)).toBeVisible();
    await expect(page.getByText(privateTeam.handle, { exact: true })).toHaveCount(0);
  });

  test("a sole owner cannot leave while members remain", async ({ page }) => {
    await loginAs(page, owner);
    await page.goto(`/teamspaces/${privateTeam.handle}`);
    await page.getByRole("button", { name: /leave/i }).click();

    await expect(page.getByText(/must have at least one owner|transfer ownership/i)).toBeVisible();
    await expect(page).toHaveURL(new RegExp(`/teamspaces/${privateTeam.handle}$`));
    await expect(page.getByRole("button", { name: /leave/i })).toBeVisible();
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

    await page.getByRole("button", { name: "Request to join", exact: true }).click();
    await expect(page.getByText(/join requested/i)).toBeVisible();
    await page.reload();
    await expect(page.getByText(/join requested/i)).toBeVisible();

    await page.getByRole("button", { name: /withdraw request/i }).click();
    await expect(page.getByText(/withdrew this join request/i)).toBeVisible();
    await page.reload();
    await expect(page.getByText(/withdrew this join request/i)).toBeVisible();
  });

  test("private invite approval survives refresh and opens the teamspace", async ({ page }) => {
    await loginAs(page, outsider);
    await page.goto(`/team-invites/${inviteToken}`);
    await page.getByRole("button", { name: /request to join again/i }).click();
    await expect(page.getByText(/join requested/i)).toBeVisible();

    const request = await pendingRequest(privateTeam.id, outsider.id);
    await api(`/api/v1/teams/${privateTeam.id}/join-requests/${request.id}/approve`, owner.token, "POST");
    await page.reload();
    await expect(page.getByText(/join request approved/i)).toBeVisible();
    await page.getByRole("link", { name: /open teamspace/i }).click();
    await expect(page).toHaveURL(new RegExp(`/teamspaces/${privateTeam.handle}$`));
    await expect(page.getByRole("tab", { name: /members/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /leave/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /request to join/i })).toHaveCount(0);

    await page.goto("/teamspaces");
    await expect(page.getByText(personalTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(privateTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(publicTeam.handle, { exact: true })).toBeVisible();
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
    await expect(page.getByRole("button", { name: /leave/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /request to join/i })).toHaveCount(0);

    await page.goto("/teamspaces");
    await expect(page.getByText(personalTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(privateTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(publicTeam.handle, { exact: true })).toBeVisible();
  });

  test("reviewers see public teams and need an invite for private teams", async ({ page }) => {
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
    expect(reviewerTeams.some((team: { id: string }) => team.id === publicTeam.id)).toBe(true);
    expect(reviewerTeams.some((team: { id: string }) => team.id === privateTeam.id)).toBe(false);
    expect(reviewerTeams.some((team: { id: string }) => team.id === personalTeam.id)).toBe(false);

    await loginAs(page, globalReviewer);
    await page.goto("/teamspaces");
    await expect(page.getByText(publicTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(privateTeam.handle, { exact: true })).toHaveCount(0);
    await expect(page.getByText(personalTeam.handle, { exact: true })).toHaveCount(0);

    await page.goto(`/teamspaces/${privateTeam.handle}`);
    await expect(page.getByText(/no teamspace named/i)).toBeVisible();

    await page.goto(`/team-invites/${inviteToken}`);
    await page.getByRole("button", { name: "Request to join", exact: true }).click();
    await expect(page.getByText(/join requested/i)).toBeVisible();
    await page.getByRole("button", { name: /withdraw request/i }).click();
    await expect(page.getByText(/withdrew this join request/i)).toBeVisible();

    await page.goto(`/teamspaces/${publicTeam.handle}`);
    await page.getByRole("button", { name: /request to join/i }).click();
    await page.getByRole("button", { name: /send request/i }).click();
    await expect(page.getByText(/request pending/i)).toBeVisible();
    await page.getByRole("button", { name: /withdraw/i }).click();
    await expect(page.getByRole("button", { name: /request to join/i })).toBeVisible();
  });

  test("leaving a private team keeps public discovery and allows rejoining", async ({ page }) => {
    await loginAs(page, outsider);
    await page.goto(`/teamspaces/${privateTeam.handle}`);
    await page.getByRole("button", { name: /leave/i }).click();

    await expect(page).toHaveURL(/\/teamspaces$/);
    await expect(page.getByText(personalTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(publicTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(privateTeam.handle, { exact: true })).toHaveCount(0);

    await page.goto(`/team-invites/${inviteToken}`);
    await page.getByRole("button", { name: /request to join again/i }).click();
    await expect(page.getByText(/join requested/i)).toBeVisible();
    await page.getByRole("button", { name: /withdraw request/i }).click();
  });

  test("leaving a public team keeps it discoverable and joinable", async ({ page }) => {
    await loginAs(page, outsider);
    await page.goto(`/teamspaces/${publicTeam.handle}`);
    await page.getByRole("button", { name: /leave/i }).click();

    await expect(page).toHaveURL(/\/teamspaces$/);
    await expect(page.getByText(personalTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(publicTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(privateTeam.handle, { exact: true })).toHaveCount(0);

    await page.getByText(publicTeam.handle, { exact: true }).click();
    await expect(page.getByRole("button", { name: /request to join/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /leave/i })).toHaveCount(0);
  });

  test("team reviewers lose private visibility after leaving", async ({ page }) => {
    await loginAs(page, teamReviewer);
    await page.goto(`/teamspaces/${privateTeam.handle}`);
    await page.getByRole("button", { name: /leave/i }).click();

    await expect(page).toHaveURL(/\/teamspaces$/);
    await expect(page.getByText(publicTeam.handle, { exact: true })).toBeVisible();
    await expect(page.getByText(privateTeam.handle, { exact: true })).toHaveCount(0);
    await page.goto(`/teamspaces/${privateTeam.handle}`);
    await expect(page.getByText(/no teamspace named/i)).toBeVisible();
  });

  test("a public pending request closes when the team becomes private", async ({ page }) => {
    const team: Team = await api("/api/v1/teams", owner.token, "POST", {
      name: "E2E Public To Private",
      handle: `e2e-pub-private-${suffix}`.slice(0, 32),
      visibility: "public",
    });
    try {
      await loginAs(page, outsider);
      await page.goto(`/teamspaces/${team.handle}`);
      await page.getByRole("button", { name: /request to join/i }).click();
      await page.getByRole("button", { name: /send request/i }).click();
      await expect(page.getByText(/request pending/i)).toBeVisible();
      const request = await pendingRequest(team.id, outsider.id);

      await api(`/api/v1/teams/${team.id}/visibility`, owner.token, "PATCH", { visibility: "private" });
      await page.reload();
      await expect(page.getByText(/no teamspace named/i)).toBeVisible();

      const requests = await api(`/api/v1/teams/${team.id}/join-requests`, owner.token);
      const closed = requests.find((row: { id: string }) => row.id === request.id);
      expect(closed.status).toBe("rejected");
      expect(closed.decision_reason).toBe("Teamspace became private");
    } finally {
      await api(`/api/v1/teams/${team.id}`, owner.token, "DELETE");
    }
  });

  test("a private pending request survives a transition to public", async ({ page }) => {
    const team: Team = await api("/api/v1/teams", owner.token, "POST", {
      name: "E2E Private To Public",
      handle: `e2e-private-pub-${suffix}`.slice(0, 32),
      visibility: "private",
    });
    try {
      const invite = await api(`/api/v1/teams/${team.id}/invites`, owner.token, "POST", {
        name: "Visibility transition invite",
        expires_in_days: 1,
        max_uses: 1,
      });
      await loginAs(page, outsider);
      await page.goto(`/team-invites/${invite.token}`);
      await page.getByRole("button", { name: /request to join/i }).click();
      await expect(page.getByText(/join requested/i)).toBeVisible();
      const request = await pendingRequest(team.id, outsider.id);

      await api(`/api/v1/teams/${team.id}/visibility`, owner.token, "PATCH", { visibility: "public" });
      await page.goto(`/teamspaces/${team.handle}`);
      await expect(page.getByText(/request pending/i)).toBeVisible();

      await api(`/api/v1/teams/${team.id}/join-requests/${request.id}/approve`, owner.token, "POST");
      await page.reload();
      await expect(page.getByRole("button", { name: /leave/i })).toBeVisible();
      await expect(page.getByRole("button", { name: /request to join/i })).toHaveCount(0);
    } finally {
      await api(`/api/v1/teams/${team.id}`, owner.token, "DELETE");
    }
  });

  test("deleting a team cascades pending requests without residue", async ({ page }) => {
    const team: Team = await api("/api/v1/teams", owner.token, "POST", {
      name: "E2E Delete Pending",
      handle: `e2e-delete-pending-${suffix}`.slice(0, 32),
      visibility: "public",
    });
    await loginAs(page, outsider);
    await page.goto(`/teamspaces/${team.handle}`);
    await page.getByRole("button", { name: /request to join/i }).click();
    await page.getByRole("button", { name: /send request/i }).click();
    await expect(page.getByText(/request pending/i)).toBeVisible();
    const request = await pendingRequest(team.id, outsider.id);

    const deletion = await fetch(`${API_BASE}/api/v1/teams/${team.id}`, {
      method: "DELETE",
      headers: { Authorization: `Bearer ${owner.token}` },
    });
    if (deletion.status !== 204) {
      await fetch(`${API_BASE}/api/v1/teams/${team.id}/join-requests/${request.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${outsider.token}` },
      });
      await fetch(`${API_BASE}/api/v1/teams/${team.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${owner.token}` },
      });
    }
    expect(deletion.status).toBe(204);

    await page.goto("/teamspaces");
    await expect(page.getByText(team.handle, { exact: true })).toHaveCount(0);
    await page.goto(`/teamspaces/${team.handle}`);
    await expect(page.getByText(/no teamspace named/i)).toBeVisible();
  });

  test("approval and removal refresh across users and tabs", async ({ page, context }) => {
    const team: Team = await api("/api/v1/teams", owner.token, "POST", {
      name: "E2E Cross Tab Access",
      handle: `e2e-cross-tab-${suffix}`.slice(0, 32),
      visibility: "private",
    });
    const invite = await api(`/api/v1/teams/${team.id}/invites`, owner.token, "POST", {
      name: "Cross-tab invite",
      expires_in_days: 1,
      max_uses: 1,
    });
    const ownerPage = await context.newPage();
    const secondMemberPage = await context.newPage();
    try {
      await loginAs(page, outsider);
      await page.goto(`/team-invites/${invite.token}`);
      await page.getByRole("button", { name: /request to join/i }).click();
      await expect(page.getByText(/join requested/i)).toBeVisible();
      const request = await pendingRequest(team.id, outsider.id);

      await loginAs(ownerPage, owner);
      await ownerPage.bringToFront();
      await api(`/api/v1/teams/${team.id}/join-requests/${request.id}/approve`, owner.token, "POST");
      await page.bringToFront();
      await expect(page.getByText(/join request approved/i)).toBeVisible({ timeout: 15_000 });
      await page.getByRole("link", { name: /open teamspace/i }).click();
      await expect(page.getByRole("button", { name: /leave/i })).toBeVisible();

      await loginAs(secondMemberPage, outsider);
      await secondMemberPage.goto(`/teamspaces/${team.handle}`);
      await expect(secondMemberPage.getByRole("button", { name: /leave/i })).toBeVisible();

      await ownerPage.bringToFront();
      await api(`/api/v1/teams/${team.id}/members/${outsider.id}`, owner.token, "DELETE");
      await page.bringToFront();
      await expect(page.getByText(/no teamspace named/i)).toBeVisible({ timeout: 15_000 });
      await secondMemberPage.bringToFront();
      await expect(secondMemberPage.getByText(/no teamspace named/i)).toBeVisible({ timeout: 15_000 });
    } finally {
      await ownerPage.close();
      await secondMemberPage.close();
      await api(`/api/v1/teams/${team.id}`, owner.token, "DELETE");
    }
  });

  test("only one concurrent request consumes the final invite use", async () => {
    const team: Team = await api("/api/v1/teams", owner.token, "POST", {
      name: "E2E Final Invite Use",
      handle: `e2e-final-invite-${suffix}`.slice(0, 32),
      visibility: "private",
    });
    try {
      const invite = await api(`/api/v1/teams/${team.id}/invites`, owner.token, "POST", {
        name: "One use invite",
        expires_in_days: 1,
        max_uses: 1,
      });
      const request = (token: string) =>
        fetch(`${API_BASE}/api/v1/teams/${team.id}/join-requests`, {
          method: "POST",
          headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
          body: JSON.stringify({ invite_token: invite.token }),
        });
      const responses = await Promise.all([request(outsider.token), request(globalReviewer.token)]);
      expect(responses.map((response) => response.status).sort()).toEqual([201, 201]);
      const requests = await Promise.all(responses.map((response) => response.json()));
      const approve = (requestId: string) =>
        fetch(`${API_BASE}/api/v1/teams/${team.id}/join-requests/${requestId}/approve`, {
          method: "POST",
          headers: { Authorization: `Bearer ${owner.token}` },
        });
      const approvals = await Promise.all(requests.map((row) => approve(row.id)));
      expect(approvals.map((response) => response.status).sort()).toEqual([200, 409]);

      const pending = await api(`/api/v1/teams/${team.id}/join-requests?status=pending`, owner.token);
      expect(pending).toHaveLength(1);
      const members = await api(`/api/v1/teams/${team.id}/members`, owner.token);
      expect(members).toHaveLength(2);
      const invites = await api(`/api/v1/teams/${team.id}/invites`, owner.token);
      expect(invites.find((row: { id: string }) => row.id === invite.id)?.use_count).toBe(1);
    } finally {
      await api(`/api/v1/teams/${team.id}`, owner.token, "DELETE");
    }
  });

  test("a deleted personal teamspace can be claimed again", async () => {
    const first: Team = await api("/api/v1/teams/claim-personal", globalReviewer.token, "POST");
    await api(`/api/v1/teams/${first.id}`, globalReviewer.token, "DELETE");
    const replacement: Team = await api("/api/v1/teams/claim-personal", globalReviewer.token, "POST");
    try {
      expect(replacement.id).not.toBe(first.id);
      expect(replacement.handle).toBe(first.handle);
      const teams = await api("/api/v1/teams", globalReviewer.token);
      expect(teams.filter((team: { is_personal: boolean }) => team.is_personal)).toHaveLength(1);
    } finally {
      await api(`/api/v1/teams/${replacement.id}`, globalReviewer.token, "DELETE");
    }
  });

  test("an unjoined admin receives private-team publishing actions", async ({ page }) => {
    const team: Team = await api("/api/v1/teams", owner.token, "POST", {
      name: "E2E Admin Publish",
      handle: `e2e-admin-publish-${suffix}`.slice(0, 32),
      visibility: "private",
    });
    try {
      await loginAs(page, { id: "admin", email: "", role: "admin", token: adminToken });
      await page.goto(`/teamspaces/${team.handle}`);
      await expect(page.getByRole("link", { name: /build agent/i })).toBeVisible();
      await page.getByRole("tab", { name: /components/i }).click();
      await expect(page.getByRole("button", { name: /create component/i })).toBeVisible();
    } finally {
      await api(`/api/v1/teams/${team.id}`, owner.token, "DELETE");
    }
  });

  test("making a private team public revokes old invites and restores discovery", async ({ page }) => {
    await loginAs(page, owner);
    await page.goto(`/teamspaces/${privateTeam.handle}`);
    await page.getByRole("button", { name: /make public/i }).click();
    await expect(page.getByText(/teamspace is now public/i)).toBeVisible();

    await loginAs(page, teamReviewer);
    await page.goto("/teamspaces");
    await expect(page.getByText(privateTeam.handle, { exact: true })).toBeVisible();

    await page.goto(`/team-invites/${inviteToken}`);
    await expect(page.getByText(/invite unavailable/i)).toBeVisible();
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
