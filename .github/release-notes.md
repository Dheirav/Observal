<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

This release includes 25 change groups through `fde9c88`.

## Features

- add Goose as a first-class harness ([#1667](https://github.com/Observal/Observal/pull/1667))
- continuous fuzzing via OSS-Fuzz (Scorecard Fuzzing 0/10 → 10/10) ([#1668](https://github.com/Observal/Observal/pull/1668))
- add the cross-product actionable inbox ([#1669](https://github.com/Observal/Observal/pull/1669))
- meet OpenSSF security criteria ([#1674](https://github.com/Observal/Observal/pull/1674))
- add shareable registry and team links ([#1673](https://github.com/Observal/Observal/pull/1673))

## Fixes

- attestation verify identity and resume-safe publish jobs ([#1655](https://github.com/Observal/Observal/pull/1655))
- make pypi, npm, and helm jobs resume-safe ([#1656](https://github.com/Observal/Observal/pull/1656))
- remove duplicate title and contributors section from release notes ([#1658](https://github.com/Observal/Observal/pull/1658))
- only stamp alembic HEAD on a genuinely fresh database ([#1662](https://github.com/Observal/Observal/pull/1662))
- pre-create ~/.observal before Docker makes it root-owned ([#1664](https://github.com/Observal/Observal/pull/1664))
- red parallel test run, dropped log records, and stale AGENTS.md ([#1666](https://github.com/Observal/Observal/pull/1666))
- preserve intentional downgrades ([#1672](https://github.com/Observal/Observal/pull/1672))
- correct agent trace attribution ([#1671](https://github.com/Observal/Observal/pull/1671))
- support headless setup ([#1676](https://github.com/Observal/Observal/pull/1676))
- preserve debug symbols ([#1679](https://github.com/Observal/Observal/pull/1679))
- require explicit session identity ([#1675](https://github.com/Observal/Observal/pull/1675))

## Documentation

- remove repetition between How It Works and feature sections ([#1657](https://github.com/Observal/Observal/pull/1657))

## Maintenance

- add E2E tests for CLI doctor commands ([#1018](https://github.com/Observal/Observal/pull/1018))
- traces pipeline end-to-end tests (#946) ([#1174](https://github.com/Observal/Observal/pull/1174))
- agents e2e tests (#936, #937, #938, #939, #941) ([#1169](https://github.com/Observal/Observal/pull/1169))
- add Playwright tests for SSO and device auth (#929) ([#1177](https://github.com/Observal/Observal/pull/1177))
- add unit tests for observal_cli/cmd_scan.py ([#1369](https://github.com/Observal/Observal/pull/1369))
- cover cmd auth helpers ([#1647](https://github.com/Observal/Observal/pull/1647))
- raise Python coverage with focused suites ([#1677](https://github.com/Observal/Observal/pull/1677))
- target canonical Codecov project ([#1678](https://github.com/Observal/Observal/pull/1678))

## Verify this release

Verify checksums, artifact provenance, and the signed release tag using the [release verification guide](https://github.com/Observal/Observal/blob/main/docs/security/release-verification.md).

## Full comparison

[v1.11.0...v1.12.0](https://github.com/Observal/Observal/compare/v1.11.0...v1.12.0)
