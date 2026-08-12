<!-- SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com> -->
<!-- SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com> -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# observal registry models

Display registry-backed harness model data.

## Synopsis

```bash
observal registry models [--harness <name>] [--output table|json]
observal registry models list [--harness <name>] [--output table|json]
```

## Options

| Option | Description |
| --- | --- |
| `--harness <name>` | Filter to one harness, such as `claude-code`, `cursor`, or `pi`. |
| `--output, -o <format>` | Output format: `table` (default) or `json`. |

## Data source

The command reads the harness model JSON files packaged with Observal under `observal_shared/harness_models/`.

## Examples

```bash
observal registry models
observal registry models --harness pi --output json
observal registry models list --harness claude-code --output json
```
