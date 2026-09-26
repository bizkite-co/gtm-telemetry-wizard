# gtm-telemetry-wizard

> Declarative GTM Container IaC Compiler, Playwright E2E Live Verifier, and GA4 Telemetry Ingestion Setup Wizard.

`gtm-telemetry-wizard` is a standalone CLI tool and Python library for automating Google Tag Manager (GTM) container setups, compiling declarative IaC specs, verifying live webpage telemetry with Playwright, and warming up GA4 measurement streams to achieve **Container Quality: Excellent**.

---

## Features

- **5-Phase Setup Wizard**: Diagnostic check, container spec compilation, live Playwright verification, GA4 ingest warm-up, and container quality reporting.
- **GA4 Ingest Warm-Up**: Delivers initial telemetry pings directly to GA4 (`/g/collect`), automatically clearing 48-hour missing traffic quality alerts.
- **Playwright E2E Verification**: Headless/Headful browser verification inspecting `gtm.js` snippet loading, `dataLayer` events, and UTM parameters.
- **Dual Deployment Options**: Automated browser import (via Playwright CDP persistent Chrome profile) or GTM REST API v2 deployment.
- **Borderless Terminal UI**: Clean Rich-powered terminal interface.

---

## Installation

```bash
uv tool install gtm-telemetry-wizard
```

Or install from source:

```bash
git clone https://github.com/bizkite-co/gtm-telemetry-wizard.git
cd gtm-telemetry-wizard
uv sync
```

`uv sync` installs this checkout as an editable development package. The
repository's `mise.toml` adds `.venv/bin` to `PATH` only while working in this
directory, so `gtw` uses the local checkout here and the PyPI installation
everywhere else.

Use `mise run check` to verify the CLI, `mise run build` to build distributions,
and `mise run release` to create and push the next patch release with `verkit`.

---

## Campaign Configuration and Provisioning

Every campaign command requires an explicit domain, GTM container ID, and GA4
measurement ID. `gtw` never substitutes IDs from another campaign. Store those
values in the consuming repository's `telemetry.toml` and pass its location
with `--config`:

```bash
gtw wizard --config path/to/telemetry.toml
```

To create a new GA4 property/web stream and GTM web container, provide the
parent account IDs and the configuration path. This writes the returned
`G-...` and `GTM-...` IDs to that file atomically, ready to review and commit:

```bash
gtw provision \
  --domain example.com \
  --analytics-account-id ANALYTICS_ACCOUNT_ID \
  --gtm-account-id GTM_ACCOUNT_ID \
  --config path/to/telemetry.toml
```

Provisioning uses Application Default Credentials. Before running it, enable
the Google Analytics Admin API and Google Tag Manager API, then authenticate
with `analytics.edit` and `tagmanager.edit.containers` scopes.

Deploy a generated container through the Tag Manager API:

```bash
gtw deploy --config path/to/telemetry.toml
```

Use `--no-publish` to create a reviewable GTM container version without
publishing it.

---

## Quick Start

### 1. Guided Setup Wizard
Run the 5-phase setup wizard for any website and container ID:

```bash
gtw wizard --domain example.com --container-id GTM-XXXXXXX --ga4-id G-YYYYYYYY
```

### 2. Using `telemetry.toml` Configuration File
Create a `telemetry.toml` in your project directory:

```toml
[site]
domain = "example.com"
container_id = "GTM-XXXXXXX"
gtm_container_api_id = "123456789"
ga4_measurement_id = "G-YYYYYYYY"

[deployment]
mode = "browser"
headful = true
```

Then run:

```bash
gtw wizard --config telemetry.toml
```

---

## Python API Usage

```python
from gtm_telemetry_wizard import TelemetryConfig, TelemetryProvider

# Initialize provider
config = TelemetryConfig(domain="example.com", container_id="GTM-XXXXXXX")
provider = TelemetryProvider(config)

# Run live telemetry verification
results = provider.verify_live_telemetry()
print("GTM Loaded:", results["gtm_script_loaded"])

# Send initial GA4 warm-up ping
ping_res = provider.ping_ga4_measurement_id("G-YYYYYYYY")
print("Ping Status:", ping_res["status"])
```

---

## CLI Reference

- `gtw wizard` - Guided 5-phase telemetry setup wizard.
- `gtw sync` - Compile GTM container IaC spec.
- `gtw verify` - Run Playwright E2E live URL verification.
- `gtw ping` - Deliver initial GA4 warm-up measurement hit.
- `gtw provision` - Provision GA4 web stream and GTM container via Google APIs.
- `gtw deploy` - Import and publish compiled container manifest via GTM API.
- `gtw query` - Query real-time and historical traffic via GA4 Data API.

---

## License

MIT License © 2026 Bizkite Co.
