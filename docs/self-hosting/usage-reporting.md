<!-- SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Usage reporting

Observal can send aggregate usage reports to the Observal-operated collector at `https://telemetry.observal.io/api/v1/usage-pings`. Reporting is disabled by default. The collector and reporting dashboard are maintained separately in [Observal Usage](https://github.com/Observal/observal_usage).

## Enable reporting

A super administrator must configure **Deployment Public URL** and then open **Admin > Settings > Usage Reporting**. Enter the company name, choose a reporting frequency, enable reporting, and save consent. The available frequencies are every six hours, daily, and weekly. Weekly is the default. The same panel previews the exact payload and can send a test report.

Only a super administrator can change the company identity, frequency, or consent setting.

Disabling the switch stops scheduled delivery immediately. It does not remove reports already received by Observal. Contact the Observal maintainers with the installation ID shown in the panel to request deletion.

## Data included

- Stable, randomly generated installation ID
- Company name and deployment hostname supplied by the administrator
- Observal version and deployment type
- Aggregate counts for users, teams, registry components, agent installations, and sessions
- Aggregate session totals by harness
- Boolean adoption signals for selected server features
- Report schema version and timestamp

## Data never included

Usage reports do not include names or email addresses of users, prompts, responses, trace events, source code, repository names, tokens, API keys, credentials, or arbitrary configuration values. Only the selected feature flags listed above are included.

## Delivery behavior

The selected schedule uses fixed UTC boundaries:

- Every six hours: 00:30, 06:30, 12:30, and 18:30 UTC
- Daily: 06:30 UTC each day
- Weekly: Monday at 06:30 UTC

The worker evaluates due reports every six hours. If a scheduled report was missed or failed, a later worker pass retries it until the current schedule window has a successful delivery. Each pass makes up to three total delivery attempts with short backoff. A failure never blocks normal Observal operation. The last successful send, latest error, selected frequency, and next delivery time are visible in the Usage Reporting settings panel.

The collector URL is fixed in production releases. `USAGE_PING_URL` exists only to direct development and isolated test deployments to a local collector.
