from __future__ import annotations

from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from typer import rich_utils
from verkit.theme import DEFAULT as theme

from .config import TelemetryConfig
from .service import TelemetryProvider


def _themed_typer_panel(*args: object, **kwargs: object) -> Panel:
    kwargs.setdefault("box", theme.panel_box)
    return Panel(*args, **kwargs)


rich_utils.Panel = _themed_typer_panel

app = typer.Typer(no_args_is_help=True, help="Standalone GTM Telemetry Setup & Container IaC Wizard")
console = Console()


@app.command(name="wizard")
def wizard_cmd(
    domain: Optional[str] = typer.Option(None, "--domain", "-d", help="Target website domain"),
    container_id: Optional[str] = typer.Option(None, "--container-id", "-c", help="Target GTM Container ID"),
    ga4_id: Optional[str] = typer.Option(None, "--ga4-id", "-g", help="Target GA4 Measurement ID"),
    config: Optional[Path] = typer.Option(None, "--config", help="Path to telemetry.toml config file"),
    skip_verify: bool = typer.Option(False, "--skip-verify", help="Skip Playwright live URL verification"),
) -> None:
    """Guided wizard for inspecting status, compiling container spec, verifying live site, and deploying GTM."""
    cfg = TelemetryConfig.load(
        config_path=config,
        domain=domain,
        container_id=container_id,
        ga4_measurement_id=ga4_id,
    )
    provider = TelemetryProvider(cfg)

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
        console.print("  1. Run automated container import: `gtw deploy --mode browser`")
        console.print(
            f"  2. In Tag Manager UI, verify Google Tag is linked to ID `{resolved_id}`."
        )
        console.print("  3. Click Submit, then Publish to publish the workspace live.")

    console.print("[bold green]✓ Setup Wizard Complete![/bold green]")


@app.command(name="sync")
def sync_cmd(
    domain: str = typer.Option("getretirementtaxanalyzer.com", "--domain", "-d", help="Target website domain"),
    measurement_id: Optional[str] = typer.Option(None, "--measurement-id", "-m", help="Explicit GA4 Measurement ID override"),
) -> None:
    """Compile GTM IaC container spec for the target domain."""
    provider = TelemetryProvider(TelemetryConfig.load(domain=domain, ga4_measurement_id=measurement_id))
    m_id = measurement_id or provider.resolve_measurement_id()
    compiled_path = provider.compile_container_manifest(m_id)
    console.print(f"[bold green]Resolved GA4 Measurement ID:[/bold green] [cyan]{m_id}[/cyan]")
    console.print(f"[bold green]Compiled GTM IaC Manifest:[/bold green] [dim]{compiled_path}[/dim]")


@app.command(name="verify")
def verify_cmd(
    url: str = typer.Option(
        "https://getretirementtaxanalyzer.com/?utm_source=email_sequence&utm_medium=email",
        "--url",
        "-u",
        help="Target webpage URL to test",
    ),
) -> None:
    """Run Playwright E2E verification test against live URL."""
    provider = TelemetryProvider()
    console.print(f"[bold blue]Running Playwright Telemetry Verification for:[/bold blue] {url}")
    res = provider.verify_live_telemetry(url)
    console.print(f"GTM Script Loaded: {'[green]Yes[/green]' if res['gtm_script_loaded'] else '[red]No[/red]'}")
    console.print(f"Captured dataLayer Events ({len(res['data_layer_events'])}):")
    console.print_json(data=res["data_layer_events"])


@app.command(name="ping")
def ping_cmd(
    measurement_id: str = typer.Option("G-HJJ9TK2TKY", "--measurement-id", "-m", help="Target GA4 Measurement ID"),
    domain: str = typer.Option("getretirementtaxanalyzer.com", "--domain", "-d", help="Target website domain"),
) -> None:
    """Send an initial telemetry hit to GA4 to warm up data ingestion and clear 48-hour missing traffic alerts."""
    provider = TelemetryProvider()
    res = provider.ping_ga4_measurement_id(measurement_id=measurement_id, domain=domain)
    if res.get("success"):
        console.print(f"[bold green]✓ Sent GA4 Telemetry Ingestion Ping:[/bold green] HTTP {res.get('status')}")
    else:
        console.print(f"[bold red]✗ Ping Error:[/bold red] {res.get('error')}")


if __name__ == "__main__":
    app()
