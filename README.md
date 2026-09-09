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
pip install gtm-telemetry-wizard
```

Or install from source:

```bash
git clone https://github.com/bizkite-co/gtm-telemetry-wizard.git
cd gtm-telemetry-wizard
pip install -e .
```

---

## Quick Start

### 1. Guided Setup Wizard
Run the 5-phase setup wizard for any website and container ID:

```bash
telemetry-wizard wizard --domain example.com --container-id GTM-XXXXXXX --ga4-id G-YYYYYYYY
```

### 2. Using `telemetry.toml` Configuration File
Create a `telemetry.toml` in your project directory:

```toml
[site]
domain = "example.com"
container_id = "GTM-53F6J2WX"
ga4_measurement_id = "G-HJJ9TK2TKY"

[deployment]
mode = "browser"
headful = true
```

Then run:

```bash
telemetry-wizard wizard --config telemetry.toml
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

- `telemetry-wizard wizard` - Guided 5-phase telemetry setup wizard.
- `telemetry-wizard sync` - Compile GTM container IaC spec.
- `telemetry-wizard verify` - Run Playwright E2E live URL verification.
- `telemetry-wizard ping` - Deliver initial GA4 warm-up measurement hit.

---

## License

MIT License © 2026 Bizkite Co.
