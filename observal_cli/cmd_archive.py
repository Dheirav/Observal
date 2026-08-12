# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""CLI commands for archiving registry components."""

from __future__ import annotations

import typer
from rich import print as rprint

from observal_cli import client

_ENTITY_LABELS = {
    "mcps": "MCP server",
    "skills": "skill",
    "hooks": "hook",
    "prompts": "prompt",
    "sandboxes": "sandbox",
}
_COMMAND_NAMES = {
    "mcps": "mcp",
    "skills": "skill",
    "hooks": "hook",
    "prompts": "prompt",
    "sandboxes": "sandbox",
}


def _archive_component(entity_type: str, entity_id: str, yes: bool) -> None:
    resolved = client.resolve_registry_reference(entity_type, entity_id)
    label = _ENTITY_LABELS.get(entity_type, entity_type)
    if not yes:
        item = client.get(f"/api/v1/{entity_type}/{resolved}")
        if not typer.confirm(f"Archive {label} [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    client.patch(f"/api/v1/{entity_type}/{resolved}/archive")
    rprint(f"[green]✓ {label.title()} archived[/green]")


def _unarchive_component(entity_type: str, entity_id: str, yes: bool) -> None:
    resolved = client.resolve_registry_reference(entity_type, entity_id)
    label = _ENTITY_LABELS.get(entity_type, entity_type)
    if not yes:
        item = client.get(f"/api/v1/{entity_type}/{resolved}")
        if not typer.confirm(f"Restore {label} [bold]{item['name']}[/bold] ({resolved})?"):
            raise typer.Abort()
    client.patch(f"/api/v1/{entity_type}/{resolved}/unarchive")
    rprint(f"[green]✓ {label.title()} restored[/green]")


def add_archive_commands(app: typer.Typer, entity_type: str) -> None:
    command = _COMMAND_NAMES[entity_type]

    def archive(
        entity_id: str = typer.Argument(help="Entity UUID or name"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        _archive_component(entity_type, entity_id, yes)

    archive.__doc__ = f"""Archive this component.

    Examples:
      observal registry {command} archive alice/my-component
    """
    app.command(name="archive")(archive)

    def unarchive(
        entity_id: str = typer.Argument(help="Entity UUID or name"),
        yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
    ):
        _unarchive_component(entity_type, entity_id, yes)

    unarchive.__doc__ = f"""Restore an archived component.

    Examples:
      observal registry {command} unarchive alice/my-component
    """
    app.command(name="unarchive")(unarchive)
