# SPDX-FileCopyrightText: 2026 Hemalatha Madeswaran <hemalathamadeswaran@gmail.com>
# SPDX-FileCopyrightText: 2026 Aryan Iyappan <aryaniyappan2006@gmail.com>
# SPDX-FileCopyrightText: 2026 Harishankar <harishankar0301@gmail.com>
# SPDX-FileCopyrightText: 2026 Hari Srinivasan <harisrini21@gmail.com>
# SPDX-FileCopyrightText: 2026 Kaushik Kumar <kaushikrjpm10@gmail.com>
# SPDX-FileCopyrightText: 2026 Lokesh Selvam <lokeshselvam7025@gmail.com>
# SPDX-FileCopyrightText: 2026 Santhosh Raja <santhoshpkraja2004@gmail.com>
# SPDX-FileCopyrightText: 2026 Shaan Narendran <shaannaren06@gmail.com>
# SPDX-FileCopyrightText: 2026 Shreem Seth <shreemseth26@gmail.com>
# SPDX-FileCopyrightText: 2026 Swathi Saravanan <ss4522@cornell.edu>
# SPDX-FileCopyrightText: 2026 Vishnu Muthiah <vishnu.muthiah04@gmail.com>
# SPDX-FileCopyrightText: 2026 Riya Rani <rr1182764@gmail.com>
# SPDX-License-Identifier: Apache-2.0

"""Auth & config CLI commands."""

from __future__ import annotations

import json as _json
import os
import re
import shutil
from contextlib import nullcontext
from pathlib import Path
from typing import Annotated, NoReturn

import httpx
import typer
from loguru import logger as optic
from rich import print as rprint

from observal_cli import client, config
from observal_cli.branding import welcome_banner
from observal_cli.errors import CliError, ErrorCategory, fail
from observal_cli.prompts import password_input, quick_choice, text_input
from observal_cli.render import OutputMode, console, esc, kv_panel, output_json, spinner, status_badge
from observal_shared.namespace_rules import NAMESPACE_RULE_TEXT, is_valid_namespace
from observal_shared.secrets import resolve_secret

# ── Auth subgroup ───────────────────────────────────────────

auth_app = typer.Typer(
    name="auth",
    help=(
        "Authentication and account commands\n\n"
        "Examples:\n"
        "  observal auth login\n"
        "  observal auth whoami\n"
        "  observal auth logout"
    ),
    no_args_is_help=True,
)

config_app = typer.Typer(
    help=(
        "CLI configuration\n\n"
        "Examples:\n"
        "  observal config show\n"
        "  observal config set output json\n"
        "  observal config path"
    )
)


# ── Auth commands (registered on auth_app) ──────────────────


_PASSWORD_REQUIREMENTS = [
    ("At least 12 characters", lambda p: len(p) >= 12),
    ("One uppercase letter", lambda p: bool(re.search(r"[A-Z]", p))),
    ("One number", lambda p: bool(re.search(r"[0-9]", p))),
    ("One special character", lambda p: bool(re.search(r"[^A-Za-z0-9]", p))),
]


def _validate_password(password: str) -> list[str]:
    """Return list of unmet requirement descriptions, empty if valid."""
    return [label for label, check in _PASSWORD_REQUIREMENTS if not check(password)]


def _prompt_password(prompt_text: str = "New password") -> str:
    """Prompt for a password, show requirements, retry until valid."""
    optic.trace("prompt_text={}", prompt_text)
    rprint("\n[dim]Password requirements:[/dim]")
    for label, _ in _PASSWORD_REQUIREMENTS:
        rprint(f"  [dim]· {label}[/dim]")

    while True:
        pw = password_input(prompt_text)
        failed = _validate_password(pw)
        if not failed:
            return pw
        rprint("\n[yellow]Password does not meet requirements:[/yellow]")
        for f in failed:
            rprint(f"  [red]✗[/red] {f}")


def _is_json(output: OutputMode | str) -> bool:
    return output == OutputMode.json or output == "json"


def _json_line(data: dict) -> None:
    print(_json.dumps(data, ensure_ascii=False))


def _secret(name: str, *, operation: str) -> str | None:
    try:
        return resolve_secret(name)
    except ValueError as exc:
        fail(
            ErrorCategory.VALIDATION,
            f"{name} is configured incorrectly.",
            operation=operation,
            resource=name,
            remediation=f"Set only {name} or {name}_FILE, then retry.",
            detail=repr(exc),
        )


def _fail_transport(error: httpx.TransportError, *, operation: str, resource: str) -> NoReturn:
    if isinstance(error, httpx.TimeoutException):
        client._handle_timeout(operation=operation, resource=resource, detail=repr(error))
    client._handle_connect(operation=operation, resource=resource, detail=repr(error))
    raise AssertionError("transport handlers must terminate")


def _raise_for_status(response: httpx.Response, *, path: str, operation: str, resource: str) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as error:
        client._handle_error(error, path, operation=operation, resource=resource)


def _save_login(server_url: str, data: dict) -> dict:
    try:
        user = data["user"]
        cfg_data = {
            "server_url": server_url,
            "access_token": data["access_token"],
            "refresh_token": data["refresh_token"],
            "user_id": user.get("id", ""),
            "user_name": user.get("name", ""),
            "username": user.get("username", ""),
        }
    except (KeyError, TypeError, AttributeError) as exc:
        fail(
            ErrorCategory.UNEXPECTED,
            "The server returned an invalid authentication response.",
            operation="Save authenticated session",
            resource=f"server {server_url}",
            remediation="Check server health and version compatibility, then retry.",
            detail=repr(exc),
        )

    endpoints = _fetch_endpoints(server_url)
    if endpoints:
        cfg_data["web_url"] = endpoints.get("web", "")
    config.save(cfg_data)
    return user


def _login_result(server_url: str, user: dict, *, method: str, bootstrapped: bool) -> dict:
    return {
        "authenticated": True,
        "server_url": server_url,
        "method": method,
        "bootstrapped": bootstrapped,
        "user": {
            "id": user.get("id", ""),
            "name": user.get("name", ""),
            "email": user.get("email", ""),
            "role": user.get("role", ""),
            "username": user.get("username", ""),
        },
    }


def _finish_login(
    server_url: str,
    data: dict,
    *,
    output: OutputMode | str,
    method: str,
    bootstrapped: bool = False,
    run_setup: bool = True,
    stream: bool = False,
) -> None:
    user = _save_login(server_url, data)
    result = _login_result(server_url, user, method=method, bootstrapped=bootstrapped)
    if _is_json(output):
        if stream:
            _json_line({"event": "authenticated", **result})
        else:
            output_json(result)
        return

    rprint(f"[green]Logged in as {esc(user.get('name', 'unknown'))}[/green] ({esc(user.get('email', ''))})")
    rprint(f"[dim]Config saved to {config.CONFIG_FILE}[/dim]")
    if run_setup:
        _post_login_setup()


def _ensure_cli_matches_server(server_url: str) -> None:
    """Block login when the CLI does not exactly match the server version.

    The server is the source of truth. CLI pings the server to get its
    version, then requires an exact match. Shows the correct upgrade or
    downgrade command so the user knows exactly what to run.
    """
    from packaging.version import InvalidVersion, Version

    from observal_cli.version_check import get_current_version

    cli_ver_str = get_current_version()
    if cli_ver_str == "0.0.0":
        return

    try:
        r = httpx.get(f"{server_url}/api/v1/config/version", timeout=10)
        r.raise_for_status()
        server_ver = r.json().get("server_version")
    except Exception:
        return

    if not server_ver or server_ver == "dev":
        return

    try:
        cli_version = Version(cli_ver_str)
        server_version = Version(server_ver)
    except InvalidVersion:
        return

    if cli_version == server_version:
        return

    from observal_cli.install_detector import upgrade_command

    if cli_version > server_version:
        install_command = f"observal self downgrade --version {server_ver}"
    else:
        install_command = upgrade_command(server_ver)
    fail(
        ErrorCategory.VERSION,
        f"CLI version {cli_ver_str} does not match server version {server_ver}.",
        operation="Authenticate with Observal",
        resource=f"server {server_url}",
        remediation=f"Run {install_command} and retry login.",
    )


@auth_app.command()
def login(
    server: str = typer.Option(None, "--server", "-s", help="Server URL"),
    email: str = typer.Option(None, "--email", "-e", help="Email or username"),
    password: str = typer.Option(None, "--password", "-p", help="Password"),
    name: str = typer.Option(None, "--name", "-n", help="Your name (used for admin setup)"),
    sso: bool = typer.Option(False, "--sso", help="Authenticate via browser SSO"),
    saml: bool = typer.Option(False, "--saml", help="Authenticate via browser SAML SSO"),
    output: Annotated[
        OutputMode, typer.Option("--output", "-o", help="Output format: table or json")
    ] = OutputMode.table,
    no_setup: Annotated[bool, typer.Option("--no-setup", help="Skip post-login skill installation and doctor")] = False,
):
    """Connect to Observal.

    On a fresh server, creates the first admin account. On an initialized
    server, authenticates with credentials or browser SSO. Set
    OBSERVAL_PASSWORD or OBSERVAL_PASSWORD_FILE to avoid exposing a password
    in shell history. JSON credential login requires complete inputs and never
    prompts. JSON SSO emits JSON Lines authorization and completion events.

    Examples:
        observal auth login
        observal auth login --server https://observal.example.com --email alice --output json --no-setup
        observal auth login --sso --output json
    """
    json_mode = _is_json(output)
    if not json_mode:
        welcome_banner()

    from observal_cli.lockfile import migrate_lockfile_v1

    stored = config.load()
    previous_server = stored.get("server_url")
    if previous_server:
        migrate_lockfile_v1(str(previous_server))

    if server:
        server_url = server
    elif stored.get("server_url"):
        server_url = str(stored["server_url"])
    elif json_mode:
        server_url = "http://localhost:80"
    else:
        server_url = text_input("Server URL", default="") or "http://localhost:80"
    server_url = server_url.rstrip("/")
    resource = f"server {server_url}"

    try:
        with nullcontext() if json_mode else spinner("Connecting..."):
            response = httpx.get(f"{server_url}/health", timeout=10)
        _raise_for_status(
            response,
            path="/health",
            operation="Check server before login",
            resource=resource,
        )
        health_data = response.json()
    except CliError:
        raise
    except httpx.TransportError as error:
        _fail_transport(error, operation="Check server before login", resource=resource)
    except (ValueError, TypeError, AttributeError) as error:
        fail(
            ErrorCategory.UNEXPECTED,
            "The server returned an invalid health response.",
            operation="Check server before login",
            resource=resource,
            remediation="Check server health and version compatibility, then retry.",
            detail=repr(error),
        )
    except Exception as error:
        fail(
            ErrorCategory.UNEXPECTED,
            "The server health check failed unexpectedly.",
            operation="Check server before login",
            resource=resource,
            remediation="Retry with debug output and inspect server health if the failure persists.",
            detail=repr(error),
        )

    _ensure_cli_matches_server(server_url)
    initialized = health_data.get("initialized", True)
    run_setup = not no_setup and not json_mode
    supplied_password = password or _secret("OBSERVAL_PASSWORD", operation="Authenticate with Observal")

    if not initialized:
        if json_mode:
            if not email or not name or not supplied_password:
                fail(
                    ErrorCategory.VALIDATION,
                    "Fresh-server JSON login requires email, name, and a password.",
                    operation="Initialize Observal administrator",
                    resource=resource,
                    remediation=(
                        "Provide email and name, and set OBSERVAL_PASSWORD or OBSERVAL_PASSWORD_FILE, then retry."
                    ),
                )
            admin_email, admin_name, admin_password = email, name, supplied_password
        else:
            rprint("[green]Connected.[/green] No users yet; setting up the administrator account.")
            admin_email = email or text_input("Admin email")
            admin_name = name or text_input("Admin name", default="admin")
            admin_password = supplied_password or _prompt_password("Admin password")
            if supplied_password is None:
                confirm = password_input("Confirm password")
                if admin_password != confirm:
                    fail(
                        ErrorCategory.VALIDATION,
                        "Passwords do not match.",
                        operation="Initialize Observal administrator",
                        resource="administrator password",
                        remediation="Enter matching passwords and retry.",
                    )

        failed = _validate_password(admin_password)
        if failed:
            fail(
                ErrorCategory.VALIDATION,
                "The administrator password does not meet security requirements.",
                operation="Initialize Observal administrator",
                resource="administrator password",
                remediation="Use at least 12 characters with uppercase, number, and special characters.",
            )

        try:
            with nullcontext() if json_mode else spinner("Creating admin account..."):
                response = httpx.post(
                    f"{server_url}/api/v1/auth/init",
                    json={"email": admin_email, "name": admin_name, "password": admin_password},
                    timeout=30,
                )
            if response.status_code == 400 and "already initialized" in response.text.lower():
                fail(
                    ErrorCategory.CONFLICT,
                    "The server was initialized by another user before this request completed.",
                    operation="Initialize Observal administrator",
                    resource=resource,
                    remediation="Retry login with an existing account.",
                    http_status=400,
                )
            _raise_for_status(
                response,
                path="/api/v1/auth/init",
                operation="Initialize Observal administrator",
                resource=resource,
            )
            data = response.json()
        except CliError:
            raise
        except httpx.TransportError as error:
            _fail_transport(error, operation="Initialize Observal administrator", resource=resource)
        except (ValueError, TypeError) as error:
            fail(
                ErrorCategory.UNEXPECTED,
                "The server returned an invalid initialization response.",
                operation="Initialize Observal administrator",
                resource=resource,
                remediation="Check server health and version compatibility, then retry.",
                detail=repr(error),
            )
        _finish_login(
            server_url,
            data,
            output=output,
            method="bootstrap",
            bootstrapped=True,
            run_setup=run_setup,
        )
        return

    if not json_mode:
        rprint("[green]Connected.[/green]")

    sso_mode = bool(sso or saml)
    direct_sso = sso_mode
    sso_provider: str | None = "saml" if saml else None
    sso_only = False
    sso_available = False
    oidc_available = False
    saml_available = False
    try:
        public_response = httpx.get(f"{server_url}/api/v1/config/public", timeout=5)
        if public_response.status_code == 200:
            public = public_response.json()
            sso_only = bool(public.get("sso_only"))
            oidc_available = bool(public.get("sso_enabled"))
            saml_available = bool(public.get("saml_enabled"))
            sso_available = oidc_available or saml_available
            if saml and not saml_available:
                fail(
                    ErrorCategory.VALIDATION,
                    "SAML SSO is not configured on this server.",
                    operation="Authenticate with SAML SSO",
                    resource=resource,
                    remediation="Use an enabled authentication method or ask an administrator to configure SAML.",
                )
            if sso_only:
                sso_mode = True
                direct_sso = True
    except CliError:
        raise
    except (httpx.HTTPError, ValueError, TypeError):
        pass

    if json_mode and not (sso or saml) and not (email and supplied_password):
        fail(
            ErrorCategory.VALIDATION,
            "JSON login requires complete credentials or an explicit SSO option.",
            operation="Authenticate with Observal",
            resource=resource,
            remediation=("Provide email and OBSERVAL_PASSWORD, or select SSO or SAML, then retry."),
        )

    if not json_mode and not sso_mode and not (email or supplied_password):
        if sso_only:
            if oidc_available and saml_available:
                rprint("  [1] OIDC SSO")
                rprint("  [2] SAML SSO")
                choice = quick_choice("Login method", ["1", "2"])
                sso_provider = "saml" if choice == "2" else "oidc"
            else:
                rprint(f"  [1] {'SAML SSO' if saml_available else 'SSO'}")
                quick_choice("Login method", ["1"])
                sso_provider = "saml" if saml_available else None
            sso_mode = True
            direct_sso = True
        else:
            rprint("  [1] CLI email/username + password")
            rprint("  [2] Web sign-in")
            valid = ["1", "2"]
            if oidc_available:
                rprint("  [3] OIDC SSO")
                valid.append("3")
            elif saml_available:
                rprint("  [3] SAML SSO")
                valid.append("3")
            if oidc_available and saml_available:
                rprint("  [4] SAML SSO")
                valid.append("4")
            choice = quick_choice("Login method", valid)
            if choice == "2":
                sso_mode = True
            elif choice == "3" and sso_available:
                sso_mode = True
                direct_sso = True
                sso_provider = "oidc" if oidc_available else "saml"
            elif choice == "4" and saml_available:
                sso_mode = True
                direct_sso = True
                sso_provider = "saml"

    if sso_mode:
        if not json_mode and run_setup:
            _do_device_flow_login(server_url, direct_sso=direct_sso, provider=sso_provider)
        else:
            _do_device_flow_login(
                server_url,
                direct_sso=direct_sso,
                provider=sso_provider,
                output=output,
                run_setup=run_setup,
            )
        return

    login_email = email or text_input("Email or username")
    login_password = supplied_password or password_input("Password")
    if not json_mode and run_setup:
        _do_password_login(server_url, login_email, login_password)
    else:
        _do_password_login(
            server_url,
            login_email,
            login_password,
            output=output,
            run_setup=run_setup,
        )


@auth_app.command()
def logout(
    output: Annotated[
        OutputMode, typer.Option("--output", "-o", help="Output format: table or json")
    ] = OutputMode.table,
):
    """Clear saved credentials.

    Revokes the remote session when possible, then removes local access and
    refresh tokens. Remote revocation failure never blocks local cleanup.

    Examples:
        observal auth logout
        observal auth logout --output json
    """
    existed = config.CONFIG_FILE.exists()
    attempted = False
    revoked: bool | None = None
    if existed:
        try:
            raw_cfg = _json.loads(config.CONFIG_FILE.read_text())
        except (OSError, _json.JSONDecodeError) as error:
            fail(
                ErrorCategory.VALIDATION,
                "The local authentication configuration cannot be read.",
                operation="Log out of Observal",
                resource=str(config.CONFIG_FILE),
                remediation="Repair or remove the configuration file, then retry.",
                detail=repr(error),
            )

        access_token = raw_cfg.get("access_token")
        refresh_token = raw_cfg.get("refresh_token")
        server_url = raw_cfg.get("server_url", "").rstrip("/")
        if access_token and server_url:
            attempted = True
            try:
                response = httpx.post(
                    f"{server_url}/api/v1/auth/logout",
                    json={"refresh_token": refresh_token or None},
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=5,
                )
                revoked = response.is_success
            except httpx.HTTPError:
                revoked = False
        config.remove("access_token", "refresh_token", "api_key")

    result = {
        "logged_out": True,
        "config_existed": existed,
        "local_tokens_cleared": True,
        "remote_revocation_attempted": attempted,
        "remote_revoked": revoked,
    }
    if _is_json(output):
        output_json(result)
        return

    rprint("[green]Logged out.[/green]" if existed else "[dim]No config to clear.[/dim]")
    if revoked is False:
        rprint("[yellow]The remote session could not be revoked, but local credentials were removed.[/yellow]")
    if existed:
        rprint(
            "[dim]Harness hooks will stop sending telemetry. "
            "Run [bold]observal doctor cleanup[/bold] to remove managed hooks.[/dim]"
        )


@auth_app.command()
def whoami(
    output: OutputMode = typer.Option("table", "--output", "-o", help="Output format: table or json"),
):
    """Show current authenticated user.

    Queries the server for the user associated with the stored access token.

    Examples:
        observal auth whoami
        observal auth whoami --output json
    """
    with nullcontext() if _is_json(output) else spinner("Checking..."):
        user = client.get("/api/v1/auth/whoami")
    if _is_json(output):
        output_json(user)
        return
    console.print(
        kv_panel(
            esc(user["name"]),
            [
                ("Username", f"@{esc(user['username'])}" if user.get("username") else "[dim]not set[/dim]"),
                ("Email", esc(user["email"])),
                ("Role", status_badge(esc(user.get("role", "user")))),
                ("ID", f"[dim]{esc(user['id'])}[/dim]"),
            ],
        )
    )


@auth_app.command()
def status(
    output: Annotated[
        OutputMode, typer.Option("--output", "-o", help="Output format: table or json")
    ] = OutputMode.table,
):
    """Check authenticated server connectivity and local outbox health.

    Returns authentication code 3 when credentials are absent and unavailable
    code 9 when the configured server cannot be reached.

    Examples:
        observal auth status
        observal auth status --output json
    """
    cfg = config.load()
    url = str(cfg.get("server_url") or "").rstrip("/")
    if not url or not cfg.get("access_token"):
        fail(
            ErrorCategory.AUTH,
            "Observal authentication is not configured.",
            operation="Check authentication status",
            resource=str(config.CONFIG_FILE),
            remediation="Run observal auth login or configure an access token, then retry.",
        )

    ok, latency = client.health()
    if not ok:
        fail(
            ErrorCategory.UNAVAILABLE,
            "The configured Observal server is unreachable.",
            operation="Check authentication status",
            resource=f"server {url}",
            remediation="Check the server URL and service health, then retry.",
        )

    outbox: dict[str, object]
    try:
        from observal_cli.telemetry_buffer import stats as buffer_stats

        buf = buffer_stats()
        outbox = {
            "available": True,
            "total": buf.get("total", 0),
            "pending": buf.get("pending", 0),
            "bytes": buf.get("bytes", 0),
            "oldest_pending": buf.get("oldest_pending"),
        }
    except Exception as error:
        outbox = {"available": False, "error": type(error).__name__}

    result = {
        "server_url": url,
        "authenticated": True,
        "health": {"reachable": True, "latency_ms": round(latency, 3)},
        "outbox": outbox,
    }
    if _is_json(output):
        output_json(result)
        return

    rprint(f"  Server:  {esc(url)}")
    rprint("  Auth:    [green]configured[/green]")
    color = "green" if latency < 200 else "yellow" if latency < 1000 else "red"
    rprint(f"  Health:  [{color}]ok[/{color}] ({latency:.0f}ms)")
    if outbox["available"] and outbox["total"]:
        pending = int(outbox["pending"])
        label = f"[yellow]{pending} pending[/yellow]" if pending else "[green]0 pending[/green]"
        rprint()
        rprint(f"  Outbox:  {label} batches, {int(outbox['bytes']) / 1024:.1f} KiB")
        if outbox["oldest_pending"]:
            rprint(f"  Oldest:  {esc(outbox['oldest_pending'])} UTC")
    elif not outbox["available"]:
        rprint("  Outbox:  [yellow]status unavailable[/yellow]")


@auth_app.command(name="change-password")
def change_password(
    output: Annotated[
        OutputMode, typer.Option("--output", "-o", help="Output format: table or json")
    ] = OutputMode.table,
):
    """Change your password.

    Human mode prompts for passwords. JSON mode reads
    OBSERVAL_CURRENT_PASSWORD and OBSERVAL_NEW_PASSWORD, including their FILE
    forms, and never prompts.

    Examples:
        observal auth change-password
        observal auth change-password --output json
    """
    cfg = config.load()
    if not cfg.get("server_url") or not cfg.get("access_token"):
        fail(
            ErrorCategory.AUTH,
            "An authenticated session is required to change the password.",
            operation="Change password",
            resource=str(config.CONFIG_FILE),
            remediation="Run observal auth login and retry.",
        )

    json_mode = _is_json(output)
    current = _secret("OBSERVAL_CURRENT_PASSWORD", operation="Change password")
    new_password = _secret("OBSERVAL_NEW_PASSWORD", operation="Change password")
    if json_mode and (not current or not new_password):
        fail(
            ErrorCategory.VALIDATION,
            "JSON password change requires current and new password secrets.",
            operation="Change password",
            resource="password input",
            remediation=("Set OBSERVAL_CURRENT_PASSWORD and OBSERVAL_NEW_PASSWORD, or their FILE forms, then retry."),
        )

    current = current or password_input("Current password")
    if new_password is None:
        new_password = _prompt_password("New password")
        confirmation = password_input("Confirm password")
        if new_password != confirmation:
            fail(
                ErrorCategory.VALIDATION,
                "Passwords do not match.",
                operation="Change password",
                resource="new password",
                remediation="Enter matching passwords and retry.",
            )

    if _validate_password(new_password):
        fail(
            ErrorCategory.VALIDATION,
            "The new password does not meet security requirements.",
            operation="Change password",
            resource="new password",
            remediation="Use at least 12 characters with uppercase, number, and special characters.",
        )

    with nullcontext() if json_mode else spinner("Changing password..."):
        result = client.put(
            "/api/v1/auth/profile/password",
            {"current_password": current, "new_password": new_password},
        )
    payload = result or {"changed": True}
    if _is_json(output):
        output_json(payload)
    else:
        rprint("[green]Password changed successfully.[/green]")


@auth_app.command(name="set-username")
def set_username(
    username: str = typer.Argument(..., help="Username (3-32 chars, lowercase alphanumeric, hyphens and dots)"),
    output: Annotated[
        OutputMode, typer.Option("--output", "-o", help="Output format: table or json")
    ] = OutputMode.table,
):
    """Set or update your username.

    Examples:
        observal auth set-username alice
        observal auth set-username my-dev-handle --output json
        observal auth set-username my.dev.handle
    """
    optic.trace("username={}", username)
    if username != username.strip().lower() or not is_valid_namespace(username):
        fail(
            ErrorCategory.VALIDATION,
            NAMESPACE_RULE_TEXT,
            operation="Update username",
            resource="username",
            remediation="Choose a valid registry namespace and retry.",
        )

    with nullcontext() if _is_json(output) else spinner("Updating username..."):
        result = client.put("/api/v1/auth/profile/username", {"username": username})
    config.save({"username": result.get("username", username)})
    if _is_json(output):
        output_json(result)
    else:
        rprint(f"[green]Username set to @{esc(result.get('username', username))}[/green]")


def version_callback():
    """Show CLI version."""
    from importlib.metadata import version as pkg_version

    try:
        v = pkg_version("observal-cli")
    except Exception:
        v = "dev"
    rprint(f"observal [bold]{v}[/bold]")


# ── Helper functions ────────────────────────────────────────


def _fetch_endpoints(server_url: str) -> dict:
    """Fetch service endpoint URLs from the discovery endpoint.

    Returns a dict with api, web URLs.
    Falls back to sensible defaults if the endpoint is unavailable.
    """
    optic.trace("server_url={}", server_url)
    try:
        r = httpx.get(f"{server_url.rstrip('/')}/api/v1/config/endpoints", timeout=5)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {}


def _do_password_login(
    server_url: str,
    email: str,
    password: str,
    *,
    output: OutputMode | str = OutputMode.table,
    run_setup: bool = True,
) -> None:
    """Authenticate with email or username and password."""
    optic.trace("server_url={}, email={}", server_url, email)
    json_mode = _is_json(output)
    resource = f"server {server_url}"
    try:
        with nullcontext() if json_mode else spinner("Authenticating..."):
            response = httpx.post(
                f"{server_url}/api/v1/auth/login",
                json={"email": email, "password": password},
                timeout=30,
            )
        _raise_for_status(
            response,
            path="/api/v1/auth/login",
            operation="Authenticate with password",
            resource=resource,
        )
        data = response.json()
    except CliError:
        raise
    except httpx.TransportError as error:
        _fail_transport(error, operation="Authenticate with password", resource=resource)
    except (ValueError, TypeError) as error:
        fail(
            ErrorCategory.UNEXPECTED,
            "The server returned an invalid login response.",
            operation="Authenticate with password",
            resource=resource,
            remediation="Check server health and version compatibility, then retry.",
            detail=repr(error),
        )

    if data.get("must_change_password"):
        if not json_mode:
            rprint("[yellow]Your administrator requires a password change.[/yellow]")
        new_password = _secret("OBSERVAL_NEW_PASSWORD", operation="Complete required password change")
        if new_password is None:
            if json_mode:
                fail(
                    ErrorCategory.VALIDATION,
                    "JSON login requires a new password for the mandatory password change.",
                    operation="Complete required password change",
                    resource="new password",
                    remediation="Set OBSERVAL_NEW_PASSWORD or OBSERVAL_NEW_PASSWORD_FILE, then retry.",
                )
            new_password = _prompt_password("New password")
            confirmation = password_input("Confirm new password")
            if new_password != confirmation:
                fail(
                    ErrorCategory.VALIDATION,
                    "Passwords do not match.",
                    operation="Complete required password change",
                    resource="new password",
                    remediation="Enter matching passwords and retry.",
                )
        if _validate_password(new_password):
            fail(
                ErrorCategory.VALIDATION,
                "The new password does not meet security requirements.",
                operation="Complete required password change",
                resource="new password",
                remediation="Use at least 12 characters with uppercase, number, and special characters.",
            )
        try:
            with nullcontext() if json_mode else spinner("Changing password..."):
                changed = httpx.put(
                    f"{server_url}/api/v1/auth/profile/password",
                    json={"current_password": password, "new_password": new_password},
                    headers={"Authorization": f"Bearer {data['access_token']}"},
                    timeout=30,
                )
            _raise_for_status(
                changed,
                path="/api/v1/auth/profile/password",
                operation="Complete required password change",
                resource="user account",
            )
        except CliError:
            raise
        except httpx.TransportError as error:
            _fail_transport(error, operation="Complete required password change", resource=resource)
        if not json_mode:
            rprint("[green]Password changed.[/green]")

    _finish_login(
        server_url,
        data,
        output=output,
        method="password",
        run_setup=run_setup,
    )


def _do_device_flow_login(
    server_url: str,
    direct_sso: bool = False,
    provider: str | None = None,
    *,
    output: OutputMode | str = OutputMode.table,
    run_setup: bool = True,
) -> None:
    """Authenticate via browser using the device authorization flow."""
    optic.trace("server_url={}", server_url)
    import time
    import webbrowser
    from urllib.parse import urlparse

    json_mode = _is_json(output)
    resource = f"server {server_url}"
    try:
        with nullcontext() if json_mode else spinner("Requesting device authorization..."):
            response = httpx.post(
                f"{server_url}/api/v1/auth/device/authorize",
                json={"sso": direct_sso, "provider": provider},
                timeout=10,
            )
        _raise_for_status(
            response,
            path="/api/v1/auth/device/authorize",
            operation="Request device authorization",
            resource=resource,
        )
        data = response.json()
        device_code = data["device_code"]
        user_code = data["user_code"]
        verification_uri = data["verification_uri"]
        verification_uri_complete = data["verification_uri_complete"]
        expires_in = data["expires_in"]
        interval = data.get("interval", 5)
    except CliError:
        raise
    except httpx.TransportError as error:
        _fail_transport(error, operation="Request device authorization", resource=resource)
    except (KeyError, ValueError, TypeError) as error:
        fail(
            ErrorCategory.UNEXPECTED,
            "The server returned an invalid device authorization response.",
            operation="Request device authorization",
            resource=resource,
            remediation="Check server health and version compatibility, then retry.",
            detail=repr(error),
        )

    parsed_verification = urlparse(verification_uri)
    parsed_server = urlparse(server_url)
    if parsed_verification.hostname in ("localhost", "127.0.0.1", "::1") and parsed_server.hostname not in (
        "localhost",
        "127.0.0.1",
        "::1",
        None,
    ):
        base = f"{parsed_server.scheme}://{parsed_server.netloc}"
        path = parsed_verification.path or "/device"
        verification_uri = f"{base}{path}"
        original_query = urlparse(data.get("verification_uri_complete", "")).query
        verification_uri_complete = f"{base}{path}?{original_query}" if original_query else f"{base}{path}"
        optic.debug("rewrote localhost verification_uri to {}", verification_uri)

    if json_mode:
        _json_line(
            {
                "event": "authorization_required",
                "verification_uri": verification_uri,
                "verification_uri_complete": verification_uri_complete,
                "user_code": user_code,
                "expires_in": expires_in,
                "interval": interval,
            }
        )
    else:
        rprint()
        rprint("[bold]To sign in, open this URL in your browser:[/bold]")
        rprint()
        rprint(f"  [link={verification_uri_complete}]{verification_uri}[/link]")
        rprint()
        rprint(f"  Then enter code: [bold cyan]{user_code}[/bold cyan]")
        rprint()

    try:
        import platform
        import subprocess as _sp

        opened = False
        system = platform.system()
        if system == "Darwin":
            _sp.Popen(["open", verification_uri_complete], stderr=_sp.DEVNULL, stdout=_sp.DEVNULL)
            opened = True
        elif system == "Linux":
            wsl = _sp.run(["wslpath", "-w", "/"], capture_output=True)
            if wsl.returncode == 0:
                _sp.Popen(
                    ["powershell.exe", "-NoProfile", "-c", f"Start-Process '{verification_uri_complete}'"],
                    stderr=_sp.DEVNULL,
                    stdout=_sp.DEVNULL,
                )
            else:
                _sp.Popen(["xdg-open", verification_uri_complete], stderr=_sp.DEVNULL, stdout=_sp.DEVNULL)
            opened = True
        else:
            webbrowser.open(verification_uri_complete)
            opened = True
        if opened and not json_mode:
            rprint("[dim]Browser opened automatically.[/dim]")
    except Exception:
        if not json_mode:
            rprint("[dim]Could not open browser automatically. Please open the URL manually.[/dim]")

    if not json_mode:
        rprint()
        rprint("[dim]Waiting for authorization...[/dim]", end="")

    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            response = httpx.post(
                f"{server_url}/api/v1/auth/device/token",
                json={
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                timeout=10,
            )
        except httpx.RequestError:
            if not json_mode:
                rprint(".", end="", flush=True)
            continue

        if response.status_code == 200:
            try:
                token_data = response.json()
            except ValueError as error:
                fail(
                    ErrorCategory.UNEXPECTED,
                    "The server returned an invalid device token response.",
                    operation="Complete device authorization",
                    resource=resource,
                    remediation="Check server health and version compatibility, then retry.",
                    detail=repr(error),
                )
            if not json_mode:
                rprint(" [green]authorized![/green]")
            _finish_login(
                server_url,
                token_data,
                output=output,
                method=provider or "sso",
                run_setup=run_setup,
                stream=json_mode,
            )
            return

        if response.status_code == 428:
            if not json_mode:
                rprint(".", end="", flush=True)
            continue

        try:
            error = response.json().get("error", "unknown_error")
        except ValueError:
            error = "unknown_error"
        if error == "expired_token":
            fail(
                ErrorCategory.AUTH,
                "The device authorization code expired.",
                operation="Complete device authorization",
                resource="device authorization",
                remediation="Start login again to request a new code.",
                http_status=response.status_code,
            )
        if error == "access_denied":
            fail(
                ErrorCategory.PERMISSION,
                "Device authorization was denied.",
                operation="Complete device authorization",
                resource="device authorization",
                remediation="Approve the browser authorization request and retry.",
                http_status=response.status_code,
            )
        _raise_for_status(
            response,
            path="/api/v1/auth/device/token",
            operation="Complete device authorization",
            resource=resource,
        )

    fail(
        ErrorCategory.UNAVAILABLE,
        "Device authorization timed out.",
        operation="Complete device authorization",
        resource="device authorization",
        remediation="Start login again and complete browser authorization before the code expires.",
    )


def register_config(app: typer.Typer):
    """Register config subcommands."""

    @config_app.command(name="show")
    def config_show():
        """Show current CLI configuration.

        Prints all config values as JSON. Access and refresh tokens are
        masked for safety. The config file lives at ~/.observal/config.json.

        Examples:
            observal config show
        """
        cfg = config.load()
        safe = dict(cfg)
        if safe.get("access_token"):
            t = safe["access_token"]
            safe["access_token"] = t[:8] + "..." + t[-4:] if len(t) > 12 else "***"
        if safe.get("refresh_token"):
            t = safe["refresh_token"]
            safe["refresh_token"] = t[:8] + "..." + t[-4:] if len(t) > 12 else "***"
        # Clean up legacy key if present
        safe.pop("api_key", None)
        console.print_json(_json.dumps(safe, indent=2))

    @config_app.command(name="set")
    def config_set(
        key: str = typer.Argument(..., help="Config key (output, color, server_url)"),
        value: str = typer.Argument(..., help="Config value"),
    ):
        """Set a CLI config value.

        Persists the given key/value pair to ~/.observal/config.json.
        Common keys: output (table/json), color (true/false),
        server_url.

        Examples:
            observal config set output json
            observal config set color false
            observal config set server_url http://observal.internal:80
        """
        optic.trace("key={}, value={}", key, value)
        if key == "output" and value not in ("table", "json"):
            raise typer.BadParameter("output must be 'table' or 'json'", param_hint="value")
        if key == "server_url":
            from observal_cli.lockfile import migrate_lockfile_v1

            previous_server = config.load().get("server_url")
            if previous_server:
                migrate_lockfile_v1(str(previous_server))
        if key == "color":
            config.save({key: value.lower() in ("true", "1", "yes")})
        else:
            config.save({key: value})
        rprint(f"[green]Set {key}[/green]")

    @config_app.command(name="path")
    def config_path():
        """Show config file path.

        Prints the absolute path to the CLI config file. Useful for
        scripting or manual edits.

        Examples:
            observal config path
            cat $(observal config path)
        """
        rprint(str(config.CONFIG_FILE))

    @config_app.command(name="alias")
    def config_alias(
        name: str = typer.Argument(..., help="Alias name (used as @name)"),
        target: str = typer.Argument(None, help="Target ID (omit to remove)"),
    ):
        """Set or remove an alias for an MCP/agent ID.

        Aliases let you reference agents or components by short names
        instead of UUIDs. Use @name in any command that accepts an ID.
        Omit the target argument to remove an existing alias.

        Examples:
            observal config alias myagent 550e8400-e29b-41d4-a716-446655440000
            observal config alias myagent
        """
        optic.trace("name={}, target={}", name, target)
        aliases = config.load_aliases()
        if target:
            aliases[name] = target
            config.save_aliases(aliases)
            rprint(f"[green]@{name} -> {target}[/green]")
        else:
            removed = aliases.pop(name, None)
            config.save_aliases(aliases)
            if removed:
                rprint(f"[green]Removed @{name}[/green]")
            else:
                rprint(f"[yellow]Alias @{name} not found.[/yellow]")

    @config_app.command(name="aliases")
    def config_aliases():
        """List all aliases.

        Shows all configured @name to ID mappings. Aliases are stored
        in ~/.observal/aliases.json.

        Examples:
            observal config aliases
        """
        aliases = config.load_aliases()
        if not aliases:
            rprint("[dim]No aliases set. Use: observal config alias <name> <id>[/dim]")
            return
        for name, target in sorted(aliases.items()):
            rprint(f"  @{name} -> [dim]{target}[/dim]")

    app.add_typer(config_app, name="config")


def _post_login_setup():
    """Post-login setup: install skills unconditionally, then run doctor."""
    _install_observal_skill()
    _generate_initial_layer_snapshot()
    rprint()
    try:
        from unittest.mock import MagicMock

        from observal_cli.cmd_doctor import doctor

        # Call doctor inline so stdin prompts work naturally.
        # Pass a fake ctx with invoked_subcommand=None so it runs the check logic.
        ctx = MagicMock()
        ctx.invoked_subcommand = None
        doctor(ctx=ctx, yes=False)
    except (SystemExit, typer.Exit, typer.Abort):
        pass  # Normal exit from doctor
    except Exception as e:
        rprint(f"[yellow]Could not run doctor: {e}[/yellow]")
        rprint("  Run [bold]observal doctor[/bold] manually to configure your harnesses.")


def _post_auth_onboarding():
    """Detect local harness configs and show what was found."""
    try:
        _ide_dirs = {
            "Claude Code": (Path.home() / ".claude", "claude-code"),
            "Kiro CLI": (Path.home() / ".kiro", "kiro"),
            "Cursor": (Path.home() / ".cursor", "cursor"),
            "Codex": (Path.home() / ".codex", "codex"),
            "Copilot": (Path.home() / ".vscode", "copilot"),
            "OpenCode": (Path.home() / ".config" / "opencode", "opencode"),
            "Pi": (Path.home() / ".pi" / "agent", "pi"),
        }

        found: list[tuple[str, str, int, int]] = []  # (label, ide_key, agents, mcps)
        for label, (dir_path, ide_key) in _ide_dirs.items():
            if not dir_path.is_dir():
                continue
            agents = mcps = 0
            try:
                from observal_cli.harness import NotSupportedError, ensure_loaded, get_adapter

                ensure_loaded()
                adapter = get_adapter(ide_key)
                result = adapter.scan_home(dir_path.parent)
                agents = len(result.agents)
                mcps = len(result.mcps)
            except (KeyError, NotSupportedError):
                pass
            if agents > 0 or mcps > 0:
                found.append((label, ide_key, agents, mcps))

        if not found:
            return

        rprint()
        rprint("[bold]\N{ELECTRIC LIGHT BULB} Detected local harness configs.[/bold]")
        rprint()
        for label, _key, agents, mcps in found:
            parts = []
            if agents:
                parts.append(f"{agents} agent{'s' if agents != 1 else ''}")
            if mcps:
                parts.append(f"{mcps} MCP{'s' if mcps != 1 else ''}")
            rprint(f"  [bold]{label}[/bold] - {', '.join(parts)} found")
        rprint()
        rprint("[dim]Run `observal doctor patch --all-harnesses` to instrument telemetry.[/dim]")

    except Exception:
        pass


def _generate_initial_layer_snapshot():
    """Generate ~/.observal/layer_snapshot.json scanning all detected harnesses.

    Runs once after login to establish the initial baseline of the user's
    harness configuration state. Silent on failure.
    """
    try:
        from observal_cli.layer import ensure_local_snapshot

        ensure_local_snapshot()
    except Exception:
        pass  # Never block login on snapshot failure


def _install_observal_skill():
    """Install the bundled Observal skills to all detected harness skill directories."""
    from observal_cli.skill_installer import install_observal_skill

    install_observal_skill()


def _run_doctor_patch(ide_name: str):
    """Run 'observal doctor patch --harness <name>' as a subprocess."""
    optic.trace("ide_name={}", ide_name)
    import subprocess
    import sys

    try:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, "-m", "observal_cli.main", "doctor", "patch", "--harness", ide_name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            env=env,
        )
        if result.stdout:
            rprint(result.stdout.rstrip())
        if result.returncode != 0 and result.stderr:
            rprint(f"[yellow]{result.stderr.rstrip()}[/yellow]")
    except Exception as e:
        rprint(f"[yellow]Could not run doctor patch: {e}[/yellow]")
        rprint(f"Run [bold]observal doctor patch --harness {ide_name}[/bold] manually.")


def _configure_cursor(server_url: str):
    """Check for Cursor (harness or CLI) and offer to configure its telemetry hooks."""
    optic.trace("server_url={}", server_url)
    cursor_dir = Path.home() / ".cursor"

    try:
        cursor_exists = cursor_dir.is_dir() or shutil.which("cursor")
        if not cursor_exists:
            return

        if not typer.confirm(
            "\nDetected Cursor. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        _run_doctor_patch("cursor")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Cursor automatically: {e}[/yellow]")
        rprint("Run [bold]observal doctor patch --harness cursor[/bold] to set up manually.")


def _configure_kiro(server_url: str):
    """Check for Kiro CLI and offer to configure its telemetry hooks."""
    optic.trace("server_url={}", server_url)
    kiro_dir = Path.home() / ".kiro"

    try:
        kiro_exists = kiro_dir.is_dir() or shutil.which("kiro-cli") or shutil.which("kiro")
        if not kiro_exists:
            return

        if not typer.confirm(
            "\nDetected Kiro CLI. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        _run_doctor_patch("kiro")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Kiro automatically: {e}[/yellow]")
        rprint("Run [bold]observal doctor patch --harness kiro[/bold] to set up manually.")


def _configure_codex(server_url: str):
    """Check for Codex CLI and configure telemetry via doctor patch."""
    optic.trace("server_url={}", server_url)
    codex_dir = Path.home() / ".codex"

    try:
        codex_exists = codex_dir.is_dir() or shutil.which("codex")
        if not codex_exists:
            return

        if not typer.confirm(
            "\nDetected Codex CLI. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        _run_doctor_patch("codex")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Codex automatically: {e}[/yellow]")
        rprint("Run [bold]observal doctor patch --harness codex[/bold] manually.")


def _configure_copilot(server_url: str):
    """Check for GitHub Copilot (VS Code) and configure telemetry via doctor patch."""
    optic.trace("server_url={}", server_url)
    try:
        vscode_dir = Path.home() / ".vscode"
        if not vscode_dir.is_dir():
            return

        # Check for an actual Copilot extension rather than just VS Code existing.
        extensions_dir = vscode_dir / "extensions"
        has_copilot = extensions_dir.is_dir() and any(
            p.name.startswith("github.copilot") for p in extensions_dir.iterdir()
        )
        if not has_copilot:
            return

        if not typer.confirm(
            "\nDetected GitHub Copilot. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        _run_doctor_patch("copilot")

    except Exception:
        pass


def _configure_copilot_cli(server_url: str):
    """Check for Copilot CLI and configure telemetry via doctor patch."""
    optic.trace("server_url={}", server_url)
    try:
        # The copilot binary is the definitive signal.
        # ~/.copilot/config.json can be created by a previous observal doctor patch,
        # so its presence alone doesn't mean Copilot CLI is actually installed.
        if not shutil.which("copilot"):
            return

        if not typer.confirm(
            "\nDetected Copilot CLI. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        _run_doctor_patch("copilot-cli")

    except Exception:
        pass


def _configure_opencode(server_url: str):
    """Check for OpenCode and configure telemetry via doctor patch."""
    optic.trace("server_url={}", server_url)
    try:
        # The opencode binary is the strongest signal. The official installer
        # commonly places it at ~/.opencode/bin/opencode without adding it to PATH.
        # ~/.config/opencode/opencode.json can be created by a previous Observal
        # doctor patch, so accept config only when a binary is present.
        opencode_bin = Path.home() / ".opencode" / "bin" / "opencode"
        if not shutil.which("opencode") and not opencode_bin.exists():
            return

        if not typer.confirm(
            "\nDetected OpenCode. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        _run_doctor_patch("opencode")

    except Exception:
        pass


def _configure_claude_code(server_url: str, access_token: str):
    """Check for Claude Code and configure telemetry via doctor patch.

    Fetches a long-lived hooks token first (needed by the patch command),
    then delegates to 'observal doctor patch --harness claude-code'.
    """
    optic.trace("server_url={}", server_url)
    claude_dir = Path.home() / ".claude"

    try:
        claude_exists = claude_dir.is_dir() or shutil.which("claude")
        if not claude_exists:
            return

        if not typer.confirm(
            "\nDetected Claude Code. Configure telemetry -> Observal?",
            default=True,
        ):
            return

        # Fetch a long-lived hooks token and save to config before patching
        hooks_token = _fetch_hooks_token(server_url, access_token)
        if hooks_token:
            cfg = config.load()
            cfg["api_key"] = hooks_token
            config.save(cfg)

        _run_doctor_patch("claude-code")

    except Exception as e:
        rprint(f"\n[yellow]Could not configure Claude Code automatically: {e}[/yellow]")
        rprint("Run [bold]observal doctor patch --harness claude-code[/bold] manually.")


def _fetch_hooks_token(server_url: str, access_token: str) -> str:
    """Call /auth/hooks-token to get a long-lived token for telemetry hooks.

    Falls back to the session access_token if the endpoint fails.
    """
    optic.trace("server_url={}", server_url)
    try:
        r = httpx.post(
            f"{server_url.rstrip('/')}/api/v1/auth/hooks-token",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("access_token", access_token)
    except Exception:
        pass
    return access_token
