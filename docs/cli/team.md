<!-- SPDX-FileCopyrightText: 2026 Observal Contributors -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# `observal team`

Create and govern teamspaces, members, join requests, and private-team invitation links.

Every leaf command supports `--output table|json`. JSON success output contains no Rich text or prompt. JSON failures leave stdout empty and write one categorized error object to stderr.

## Commands

| Command | Purpose |
| --- | --- |
| `list` | List the signed-in user's teamspaces |
| `show` | Show a teamspace and its members |
| `create` | Create a teamspace |
| `visibility` | Change public or private visibility |
| `delete` | Permanently delete a teamspace |
| `leave` | Leave a teamspace |
| `request-join` | Request membership |
| `requests` | List join requests and decisions |
| `approve` | Approve a pending request |
| `reject` | Reject a pending request |
| `members list` | List members |
| `members add` | Add a member or update a role |
| `members remove` | Remove a member |
| `invite create` | Create a private-team invitation link |
| `invite list` | List invitation links |
| `invite revoke` | Revoke an invitation link |

Team references may be UUIDs, handles, or `@handle`. Unknown teamspaces use not-found exit code 5.

## List and show

```bash
observal team list --output json
observal team list --all --output json
observal team show platform-tools --output json
```

`list` returns a direct array. The default includes teamspaces where the user is a member. `--all` requests all teamspaces visible to the caller. An empty array is successful.

`show` returns a stable combined result:

```json
{
  "team": {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "Platform Tools",
    "handle": "platform-tools",
    "role": "owner"
  },
  "members": []
}
```

## Create and visibility

```bash
observal team create 'Platform Tools' \
  --handle platform-tools \
  --description 'Internal tooling' \
  --visibility private \
  --output json

observal team visibility platform-tools public --output json
```

Visibility is `public` or `private`. New public teamspaces may enter the server's visibility review workflow before becoming public. The creator becomes the initial owner.

Create and visibility JSON return the direct Team object.

## Delete and leave

```bash
observal team delete platform-tools --yes --output json
observal team leave platform-tools --yes --output json
```

Delete is permanent. Leave removes only the caller's membership; the last owner cannot leave. Human mode prompts unless `--yes` is supplied. JSON mode never prompts and requires `--yes`.

Both endpoints currently return an empty JSON object on success.

## Join requests

Request access:

```bash
observal team request-join platform-tools --message 'I maintain deployments' --output json
```

The message is optional and limited to 500 characters. JSON returns the created join request.

Owners and deployment admins can list and decide requests:

```bash
observal team requests platform-tools --status pending --output json
observal team approve platform-tools @alice --output json
observal team reject platform-tools bob@example.com --reason 'Use the SRE teamspace' --output json
```

Valid status filters are `pending`, `approved`, `rejected`, and `cancelled`. Requests are selected by exact email or case-insensitive username. A missing pending request uses not-found exit code 5.

List returns a direct array. Request, approve, and reject return the direct join-request object.

## Members

```bash
observal team members list platform-tools --output json
observal team members add platform-tools alice@example.com --role reviewer --output json
observal team members add platform-tools @bob --role owner --output json
observal team members remove platform-tools @bob --yes --output json
```

Roles are `member`, `reviewer`, and `owner`. Adding an existing member updates the role. The last owner cannot be removed.

Member list returns a direct array. Add returns the saved member. Remove currently returns an empty object.

Human remove prompts unless `--yes` is supplied. JSON remove requires `--yes`.

## Private-team invitations

Create a link:

```bash
observal team invite create platform-tools \
  --name onboarding \
  --expires-days 30 \
  --max-uses 20 \
  --output json
```

`--expires-days` accepts 1 through 365. `--max-uses` accepts 1 through 10,000 or may be omitted for no use limit. Invite names accept 1 through 100 characters.

Create JSON returns the direct invitation object, including the one-time token and URL. Treat both as secrets. Do not log, store in public artifacts, or share outside the intended recipients.

List links and their current state:

```bash
observal team invite list platform-tools --output json
```

List returns a direct array. States include active, expired, exhausted, and revoked.

Revoke a link permanently:

```bash
observal team invite revoke \
  platform-tools \
  550e8400-e29b-41d4-a716-446655440000 \
  --yes \
  --output json
```

The invite ID must be a UUID. Human mode prompts unless `--yes` is supplied. JSON mode requires `--yes`. JSON returns the revoked invitation object.

## Exit codes

| Code | Meaning |
| --- | --- |
| 3 | Authentication required or failed |
| 4 | Membership or owner permission denied |
| 5 | Teamspace, member, or pending request not found |
| 6 | Handle, membership, owner, visibility, or invite state conflict |
| 7 | Invalid visibility, role, request status, invite ID, text length, or missing JSON confirmation |
| 8 | Rate limit reached |
| 9 | Server unavailable |
| 10 | CLI and server version mismatch |

## Related

* [`observal inbox`](inbox.md): view join-request decisions
* [`observal agent`](agent.md): publish Agents to a teamspace
* [`observal registry`](registry.md): publish components to a teamspace
