# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""CLI commands for managing co-authors on agents and components."""

from __future__ import annotations

import typer
from rich import print as rprint
from rich.table import Table

from observal_cli import client


def _list_co_authors(entity_type: str, entity_id: str) -> None:
    """List co-authors for an entity."""
    resp = client.get(f"/{entity_type}/{entity_id}/co-authors")
    if not resp:
        rprint("[dim]No co-authors.[/dim]")
        return

    table = Table(title="Co-Authors")
    table.add_column("Email", style="cyan")
    table.add_column("Username", style="green")
    table.add_column("Active", style="dim")

    for author in resp:
        table.add_row(
            author.get("email", ""),
            author.get("username") or "",
            "yes" if author.get("is_active", True) else "no",
        )

    rprint(table)


def _add_co_author(entity_type: str, entity_id: str, user: str) -> None:
    """Add a co-author to an entity."""
    body = {"email": user.lower()} if "@" in user and not user.startswith("@") else {"username": user.lstrip("@")}
    resp = client.post(f"/{entity_type}/{entity_id}/co-authors", json_data=body)
    rprint(f"[green]Added co-author:[/green] {resp.get('email', user)} ({resp.get('username', '')})")


def _remove_co_author(entity_type: str, entity_id: str, user_id: str) -> None:
    """Remove a co-author from an entity."""
    client.delete(f"/{entity_type}/{entity_id}/co-authors/{user_id}")
    rprint("[green]Co-author removed.[/green]")


def make_co_authors_typer(entity_type: str) -> typer.Typer:
    """Create a co-authors sub-typer for a given entity type (agents, mcps, skills, etc.)."""
    command = {
        "agents": "agent",
        "mcps": "registry mcp",
        "skills": "registry skill",
        "hooks": "registry hook",
        "prompts": "registry prompt",
        "sandboxes": "registry sandbox",
    }[entity_type]
    prefix = f"observal {command} co-authors"
    co_app = typer.Typer(help=f"Manage co-authors for {entity_type}\n\nExamples:\n  {prefix} list alice/my-component")

    def list_cmd(
        entity_id: str = typer.Argument(help="Entity UUID or name"),
    ):
        _list_co_authors(entity_type, entity_id)

    list_cmd.__doc__ = f"""List co-authors.

    Examples:
      {prefix} list alice/my-component
    """
    co_app.command(name="list")(list_cmd)

    def add_cmd(
        entity_id: str = typer.Argument(help="Entity UUID or name"),
        user: str = typer.Argument(help="Email or username of the user to add"),
    ):
        _add_co_author(entity_type, entity_id, user)

    add_cmd.__doc__ = f"""Add a co-author.

    Examples:
      {prefix} add alice/my-component alice@example.com
    """
    co_app.command(name="add")(add_cmd)

    def remove_cmd(
        entity_id: str = typer.Argument(help="Entity UUID or name"),
        user_id: str = typer.Argument(help="UUID of the co-author to remove"),
    ):
        _remove_co_author(entity_type, entity_id, user_id)

    remove_cmd.__doc__ = f"""Remove a co-author.

    Examples:
      {prefix} remove alice/my-component 550e8400-e29b-41d4-a716-446655440000
    """
    co_app.command(name="remove")(remove_cmd)

    return co_app
