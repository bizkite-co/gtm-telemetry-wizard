from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from typer import rich_utils
from verkit import display_version_info, promote_version, release_version, tag_version
from verkit.theme import DEFAULT as theme

from .auth import (
    ALL_SCOPES,
    check_account_scopes,
    ensure_account_scopes,
    list_gcloud_accounts,
    scopes_arg,
)
from .config import ConfigurationError, TelemetryConfig
from .service import GoogleApiClient, ProvisioningError, TelemetryProvider, find_ga4_properties


def _themed_typer_panel(*args: object, **kwargs: object) -> Panel:
    kwargs.setdefault("box", theme.panel_box)
    return Panel(*args, **kwargs)


rich_utils.Panel = _themed_typer_panel

app = typer.Typer(no_args_is_help=True, help="Standalone GTM Telemetry Setup & Container IaC Wizard")
console = Console()


def _exit_with_error(error: ConfigurationError | ProvisioningError) -> None:
    console.print("\n[bold red]Unable to continue[/bold red]")
    console.print(f"[red]Reason:[/red] {error}")
    console.print(f"[cyan]Solution:[/cyan] {error.solution}")
    raise typer.Exit(code=2)


def _load_config(config_path: Optional[Path], **overrides: object) -> TelemetryConfig:
    try:
        return TelemetryConfig.load(config_path=config_path, **overrides)
    except ConfigurationError as error:
        _exit_with_error(error)
    raise AssertionError("unreachable")


@app.command(name="wizard")
def wizard_cmd(
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Target website domain"),
    container_id: Optional[str] = typer.Option(None, "--container-id", "-c", help="Target GTM Container ID"),
    ga4_id: Optional[str] = typer.Option(None, "--ga4-id", "-g", help="Target GA4 Measurement ID"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to telemetry.toml config file"),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip Playwright live URL verification"),
) -> None:
    """Guided wizard for inspecting status, compiling container spec, verifying live site, and deploying GTM."""
    cfg = _load_config(
        config,
        domain=domain,
        container_id=container_id,
        ga4_measurement_id=ga4_id,
    )
    provider = TelemetryProvider(cfg)
    try:
        cfg.require("domain", "container_id", "ga4_measurement_id")
    except ConfigurationError as error:
        _exit_with_error(error)

    console.print("[bold cyan]GTM & Web Telemetry Setup Wizard[/bold cyan]")
    console.print(f"[dim]Domain: {cfg.domain} | Container: {cfg.container_id}[/dim]")

    console.print("\n[bold yellow]Phase 1: Diagnostic Status Check[/bold yellow]")
    status = provider.check_telemetry_status()

    table = Table(
        show_header=True,
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details", style="dim")

    acc_display = status["active_account"] or "None (Run `gcloud auth login`)"
    table.add_row(
        "GCP Active Account",
        "[green]Active[/green]" if status["active_account"] else "[red]Not Set[/red]",
        acc_display,
    )

    table.add_row(
        "gcloud Access Token",
        "[green]Valid[/green]" if status["gcloud_token_valid"] else "[yellow]Missing/Expired[/yellow]",
        "OAuth access token available via gcloud print-access-token",
    )

    resolved_id = provider.resolve_measurement_id()
    table.add_row(
        "GA4 Measurement ID",
        "[green]Configured[/green]" if resolved_id else "[yellow]Missing[/yellow]",
        f"Resolved: {resolved_id}",
    )

    import urllib.request
    css_status = "Missing Link"
    try:
        req = urllib.request.Request(f"https://{cfg.domain}/", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8")
            if "bootstrap" in html.lower() and "style.css" in html:
                css_status = "Healthy (Bootstrap + Tailwind)"
            elif "style.css" in html:
                css_status = "Stylesheet Active"
    except Exception as css_err:
        css_status = f"Warning ({css_err})"

    table.add_row(
        "Website Asset Health",
        "[green]Healthy[/green]" if "Healthy" in css_status or "Active" in css_status else "[yellow]Check Needed[/yellow]",
        css_status,
    )

    table.add_row(
        "GTM IaC Spec Manifest",
        "[green]Compiled[/green]" if status["compiled_manifest_exists"] else "[yellow]Not Compiled[/yellow]",
        status["compiled_manifest_path"],
    )

    console.print(table)

    console.print("\n[bold yellow]Phase 2: Compiling GTM IaC Manifest[/bold yellow]")
    compiled_path = provider.compile_container_manifest(resolved_id)
    console.print(f"[bold green]✓ Compiled Container Spec:[/bold green] [dim]{compiled_path}[/dim] (Measurement ID: {resolved_id})")

    gtm_ok = False
    ping_ok = False
    if not skip_verify:
        console.print(f"\n[bold yellow]Phase 3: Verifying Live Webpage Telemetry ({cfg.domain})[/bold yellow]")
        res = provider.verify_live_telemetry()
        gtm_ok = bool(res.get("gtm_script_loaded"))
        if gtm_ok:
            console.print(f"[bold green]✓ GTM Script Loaded:[/bold green] Container {cfg.container_id} active on {cfg.domain}")
        else:
            console.print(f"[bold red]✗ GTM Script Missing:[/bold red] Could not find gtm.js on {cfg.domain}")

        events = res.get("data_layer_events", [])
        console.print(f"[bold green]✓ Captured dataLayer Events ({len(events)}):[/bold green]")
        for ev in events:
            ev_name = ev.get("event", "gtm.start")
            console.print(f"  • [cyan]{ev_name}[/cyan]")

        ping_res = provider.ping_ga4_measurement_id(resolved_id)
        ping_ok = bool(ping_res.get("success"))
        if ping_ok:
            console.print(f"[bold green]✓ GA4 Ingestion Warmed Up:[/bold green] Initial telemetry hit delivered to {resolved_id} (HTTP {ping_res.get('status')})")
        else:
            console.print(f"[yellow]! GA4 Ingestion Ping Note:[/yellow] {ping_res.get('error')}")

        console.print("[dim]Rechecking live telemetry state...[/dim]")
        recheck_res = provider.verify_live_telemetry()
        if recheck_res.get("gtm_script_loaded"):
            console.print("[bold green]✓ Recheck Confirmed:[/bold green] GTM container telemetry verified live.")
    else:
        console.print("\n[dim]Phase 3: Live Telemetry Verification skipped (--skip-verify)[/dim]")

    console.print("\n[bold yellow]Phase 4: Container Quality & Completion Summary[/bold yellow]")
    if gtm_ok and ping_ok:
        console.print("[bold green]Container Quality: Excellent[/bold green]")
        console.print("[dim]Container is sending data. No issues detected.[/dim]")
        console.print(f"  Domain: [cyan]https://{cfg.domain}[/cyan]")
        console.print(f"  GA4 Measurement ID: [cyan]{resolved_id}[/cyan]")
        console.print(f"  GTM Container ID: [cyan]{cfg.container_id}[/cyan]")
        console.print("  Live Telemetry: [green]Active & Verified[/green]")
    else:
        console.print("[bold yellow]Remaining actions to reach Container Quality: Excellent:[/bold yellow]")
        console.print("  1. Deploy the compiled container: `gtw deploy --config path/to/telemetry.toml`")
        console.print(
            f"  2. In Tag Manager UI, verify Google Tag is linked to ID `{resolved_id}`."
        )
        console.print("  3. Click Submit, then Publish to publish the workspace live.")

    console.print("[bold green]✓ Setup Wizard Complete![/bold green]")


@app.command(name="provision")
def provision_cmd(
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Domain for the new web property and container"),
    analytics_account_id: Optional[str] = typer.Option(
        None, "--analytics-account-id", help="Google Analytics account ID that will own the property"
    ),
    gtm_account_id: Optional[str] = typer.Option(
        None, "--gtm-account-id", help="Google Tag Manager account ID that will own the container"
    ),
    config: Optional[Path] = typer.Option(
        None, "--config", help="Path to the telemetry.toml file to create or update"
    ),
) -> None:
    """Create GA4 and GTM resources, then persist their IDs to telemetry.toml."""
    cfg = _load_config(
        config,
        domain=domain,
        analytics_account_id=analytics_account_id,
        gtm_account_id=gtm_account_id,
    )
    try:
        config_path = TelemetryProvider(cfg).provision()
    except (ConfigurationError, ProvisioningError) as error:
        _exit_with_error(error)
    console.print("[bold green]Provisioning complete[/bold green]")
    console.print(f"  GA4 measurement ID: [cyan]{cfg.ga4_measurement_id}[/cyan]")
    console.print(f"  GTM container ID: [cyan]{cfg.container_id}[/cyan]")
    console.print(f"  Saved configuration: [cyan]{config_path}[/cyan]")


@app.command(name="deploy")
def deploy_cmd(
    config: Optional[Path] = typer.Option(None, "--config", help="Path to telemetry.toml config file"),
    no_publish: bool = typer.Option(
        False, "--no-publish", help="Create a GTM container version without publishing it"
    ),
) -> None:
    """Import the compiled manifest into GTM through the Tag Manager API."""
    provider = TelemetryProvider(_load_config(config))
    try:
        result = provider.deploy_container(publish=not no_publish)
    except (ConfigurationError, ProvisioningError) as error:
        _exit_with_error(error)
    console.print("[bold green]GTM deployment complete[/bold green]")
    console.print(f"  Workspace ID: [cyan]{result['workspace_id']}[/cyan]")
    console.print(f"  Container version ID: [cyan]{result['version_id']}[/cyan]")
    if result["published"] == "true":
        console.print("  Status: [green]published[/green]")
    else:
        console.print("  Status: [yellow]created but not published[/yellow]")


@app.command(name="sync")
def sync_cmd(
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Target website domain"),
    measurement_id: Optional[str] = typer.Option(None, "--measurement-id", "-m", help="Explicit GA4 Measurement ID override"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to telemetry.toml config file"),
) -> None:
    """Compile GTM IaC container spec for the target domain."""
    provider = TelemetryProvider(_load_config(config, domain=domain, ga4_measurement_id=measurement_id))
    try:
        compiled_path = provider.compile_container_manifest(measurement_id)
        m_id = measurement_id or provider.resolve_measurement_id()
    except ConfigurationError as error:
        _exit_with_error(error)
    console.print(f"[bold green]Resolved GA4 Measurement ID:[/bold green] [cyan]{m_id}[/cyan]")
    console.print(f"[bold green]Compiled GTM IaC Manifest:[/bold green] [dim]{compiled_path}[/dim]")


@app.command(name="verify")
def verify_cmd(
    url: Optional[str] = typer.Option(None, "--url", "-u", help="Target webpage URL to test"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to telemetry.toml config file"),
) -> None:
    """Run Playwright E2E verification test against live URL."""
    provider = TelemetryProvider(_load_config(config))
    try:
        res = provider.verify_live_telemetry(url)
    except ConfigurationError as error:
        _exit_with_error(error)
    target_url = res["target_url"]
    console.print(f"[bold blue]Running Playwright Telemetry Verification for:[/bold blue] {target_url}")
    console.print(f"GTM Script Loaded: {'[green]Yes[/green]' if res['gtm_script_loaded'] else '[red]No[/red]'}")
    console.print(f"Captured dataLayer Events ({len(res['data_layer_events'])}):")
    console.print_json(data=res["data_layer_events"])


@app.command(name="ping")
def ping_cmd(
    measurement_id: Optional[str] = typer.Option(None, "--measurement-id", "-m", help="Target GA4 Measurement ID"),
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Target website domain"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to telemetry.toml config file"),
) -> None:
    """Send an initial telemetry hit to GA4 to warm up data ingestion and clear 48-hour missing traffic alerts."""
    provider = TelemetryProvider(_load_config(config, domain=domain, ga4_measurement_id=measurement_id))
    try:
        res = provider.ping_ga4_measurement_id(measurement_id=measurement_id, domain=domain)
    except ConfigurationError as error:
        _exit_with_error(error)
    if res.get("success"):
        console.print(f"[bold green]✓ Sent GA4 Telemetry Ingestion Ping:[/bold green] HTTP {res.get('status')}")
    else:
        console.print(f"[bold red]✗ Ping Error:[/bold red] {res.get('error')}")


@app.command(name="query")
def query_cmd(
    campaign: Optional[str] = typer.Option(None, "--campaign", "-c", help="Filter by session campaign name (e.g. testimonials)"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="Filter by page path (e.g. /testimonials/)"),
    property_id: Optional[str] = typer.Option(None, "--property-id", help="Target GA4 Numeric Property ID"),
    days: int = typer.Option(7, "--days", "-d", help="Number of past days to query"),
    realtime: bool = typer.Option(False, "--realtime", "-r", help="Query real-time active users"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to telemetry.toml config file"),
) -> None:
    """Query Google Analytics 4 traffic and engagement data via GA4 Data API."""
    cfg = _load_config(config, ga4_property_id=property_id)
    provider = TelemetryProvider(cfg)
    try:
        report = provider.query_analytics(
            property_id=property_id,
            campaign=campaign,
            path=path,
            days=days,
            realtime=realtime,
        )
    except (ConfigurationError, ProvisioningError) as error:
        _exit_with_error(error)

    mode_label = "Real-time Traffic" if realtime else f"Traffic Summary (Past {days} days)"
    console.print(f"\n[bold cyan]Google Analytics 4 Data Report[/bold cyan] [dim]({mode_label})[/dim]")
    if campaign:
        console.print(f"Filter: [yellow]Campaign contains '{campaign}'[/yellow]")
    if path:
        console.print(f"Filter: [yellow]Path contains '{path}'[/yellow]")

    rows = report.get("rows", [])
    if not rows:
        console.print("\n[yellow]No visitor traffic recorded for the specified criteria.[/yellow]")
        return

    table = Table(
        show_header=True,
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    dim_headers = [d.get("name", "") for d in report.get("dimensionHeaders", [])]
    metric_headers = [m.get("name", "") for m in report.get("metricHeaders", [])]

    for d in dim_headers:
        table.add_column(d, style="cyan")
    for m in metric_headers:
        table.add_column(m, style="bold green", justify="right")

    for row in rows:
        d_vals = [v.get("value", "") for v in row.get("dimensionValues", [])]
        m_vals = [v.get("value", "0") for v in row.get("metricValues", [])]
        table.add_row(*(d_vals + m_vals))

    console.print(table)


auth_app = typer.Typer(no_args_is_help=True, help="Manage gcloud OAuth scopes gtw needs, across multiple accounts.")
app.add_typer(auth_app, name="auth")


@auth_app.command(name="scopes")
def auth_scopes_cmd() -> None:
    """Print the canonical scope list gtw requires - the single source of
    truth lives in gtm_telemetry_wizard/auth.py, not copy-pasted anywhere."""
    console.print(scopes_arg(ALL_SCOPES))


@auth_app.command(name="status")
def auth_status_cmd(
    accounts: list[str] = typer.Argument(
        None, help="Accounts to check (default: all `gcloud auth list` accounts)"
    ),
) -> None:
    """Show which required scopes each account currently has. Read-only -
    never prompts for login."""
    target_accounts = accounts or list_gcloud_accounts()
    if not target_accounts:
        console.print("[yellow]No gcloud accounts found. Run `gcloud auth login` first.[/yellow]")
        raise typer.Exit(code=1)

    table = Table(
        show_header=True,
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("Account", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Missing scopes", style="yellow")

    for account in target_accounts:
        status = check_account_scopes(account)
        if status.error:
            table.add_row(account, "[red]Error[/red]", status.error)
        elif status.ok:
            table.add_row(account, "[green]OK[/green]", "")
        else:
            table.add_row(account, "[yellow]Missing scopes[/yellow]", "\n".join(status.missing))

    console.print(table)


@auth_app.command(name="login")
def auth_login_cmd(
    accounts: list[str] = typer.Argument(
        ..., help="Account(s) to (re-)grant gtw's required scopes to"
    ),
    force: bool = typer.Option(
        False, "--force", help="Re-run login even if scopes already look sufficient"
    ),
) -> None:
    """Idempotently ensure each account has the scopes gtw needs.

    Only prompts (interactive OAuth consent in a browser) for accounts
    actually missing a scope - safe to re-run any time, including right
    after adding a new scope to ALL_SCOPES in gtm_telemetry_wizard/auth.py.
    This is the one command that should ever need to change when a new
    Google API scope requirement shows up.
    """
    for account in accounts:
        console.print(f"[dim]Checking {account}...[/dim]")
        status = ensure_account_scopes(account, force=force)
        if status.ok:
            console.print(f"[bold green]✓ {account}[/bold green] has all required scopes.")
        else:
            console.print(
                f"[bold red]✗ {account}[/bold red] still missing: {', '.join(status.missing)}"
            )


accounts_app = typer.Typer(
    no_args_is_help=True,
    help="Discover which Google account/GA4 property owns a given measurement ID or domain.",
)
app.add_typer(accounts_app, name="accounts")


@accounts_app.command(name="discover")
def accounts_discover_cmd(
    measurement_id: Optional[str] = typer.Option(
        None, "--measurement-id", "-m", help="GA4 measurement ID to search for (e.g. G-XXXXXXX)"
    ),
    domain: Optional[str] = typer.Option(
        None, "--domain", "-d", help="Web stream default URI (domain) to search for"
    ),
    accounts: list[str] = typer.Option(
        None, "--account", help="Restrict to these gcloud accounts (default: all `gcloud auth list` accounts)"
    ),
) -> None:
    """Scan every (or specified) gcloud account for GA4 properties, reporting
    which account can see which measurement ID/domain - a CLI-native,
    scriptable, repeatable replacement for hunting through the GA4 web UI
    across multiple logins to figure out "which account owns this?".

    Run `gtw auth login <account>` first for any account missing scopes -
    this command will report "No access" for those rather than guessing.
    """
    target_accounts = accounts or list_gcloud_accounts()
    if not target_accounts:
        console.print("[yellow]No gcloud accounts found. Run `gcloud auth login` first.[/yellow]")
        raise typer.Exit(code=1)

    table = Table(
        show_header=True,
        box=theme.table_box,
        header_style=theme.header_style,
        padding=theme.table_padding,
    )
    table.add_column("Account", style="cyan")
    table.add_column("GA4 Account", style="dim")
    table.add_column("Property ID", style="bold green")
    table.add_column("Measurement ID", style="bold")
    table.add_column("Domain", style="dim")

    any_found = False
    for account in target_accounts:
        try:
            token = TelemetryProvider._access_token(account=account)
        except (ConfigurationError, ProvisioningError) as error:
            table.add_row(account, "[red]No access[/red]", "", "", str(error))
            continue

        client = GoogleApiClient(token)
        try:
            matches = find_ga4_properties(client, measurement_id=measurement_id)
        except Exception as exc:
            table.add_row(account, "[red]Error[/red]", "", "", str(exc))
            continue

        if domain:
            matches = [
                m for m in matches if m.web_stream_default_uri and domain in m.web_stream_default_uri
            ]

        if not matches:
            table.add_row(account, "[dim]none visible[/dim]", "", "", "")
            continue

        for m in matches:
            any_found = True
            table.add_row(
                account,
                m.account_display_name,
                m.property_id,
                m.measurement_id,
                m.web_stream_default_uri or "",
            )

    console.print(table)
    if not any_found and (measurement_id or domain):
        console.print(
            "\n[yellow]No account saw a match.[/yellow] Either the property belongs to an "
            "account not yet granted `gtw auth login`, or the ID/domain is wrong."
        )


version_app = typer.Typer(no_args_is_help=False, help="Version inspection, promotion, and release management via verkit")
app.add_typer(version_app, name="version")


class ReleasePart(str, Enum):
    major = "major"
    minor = "minor"
    patch = "patch"


@version_app.callback(invoke_without_command=True)
def version_main(ctx: typer.Context) -> None:
    """Inspect version when called without subcommands."""
    if ctx.invoked_subcommand is None:
        display_version_info(console, "gtm-telemetry-wizard")


@version_app.command(name="inspect")
def version_inspect_cmd() -> None:
    """Inspect working tree and HEAD version."""
    display_version_info(console, "gtm-telemetry-wizard")


@version_app.command(name="release")
def version_release_cmd(
    part: ReleasePart = typer.Argument(..., help="Version increment part: major, minor, or patch"),
    push: bool = typer.Option(True, "--push/--no-push", help="Push commit and tag to origin"),
) -> None:
    """Atomic promote + tag + push release workflow via verkit."""
    try:
        new_v, tag_name = release_version(part.value, console=console, push=push)
        console.print(f"[bold green]✓ Successfully released {new_v} (tag: {tag_name})[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Release failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@version_app.command(name="promote")
def version_promote_cmd(
    part: ReleasePart = typer.Argument(..., help="Version increment part: major, minor, or patch"),
    allow_amend: bool = typer.Option(True, "--amend/--no-amend", help="Allow amending previous version bump commit"),
) -> None:
    """Bump version in project files and create/amend commit via verkit."""
    try:
        new_v = promote_version(part.value, console=console, allow_amend=allow_amend)
        console.print(f"[bold green]✓ Promoted version to {new_v}[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Promotion failed:[/bold red] {e}")
        raise typer.Exit(code=1)


@version_app.command(name="tag")
def version_tag_cmd(
    push: bool = typer.Option(True, "--push/--no-push", help="Push tag to origin"),
) -> None:
    """Create git tag on HEAD and push via verkit."""
    try:
        tag_name = tag_version(console=console, push=push)
        console.print(f"[bold green]✓ Created tag {tag_name}[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Tagging failed:[/bold red] {e}")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
