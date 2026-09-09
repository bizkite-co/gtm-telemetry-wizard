from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from .config import TelemetryConfig

logger = logging.getLogger(__name__)

DEFAULT_CONTAINER_SPEC_JSON = """{
  "exportFormatVersion": 2,
  "exportTime": "2026-09-09 10:25:00",
  "containerVersion": {
    "path": "accounts/1/containers/1/versions/0",
    "container": {
      "path": "accounts/1/containers/1",
      "accountId": "1",
      "containerId": "1",
      "name": "getretirementtaxanalyzer.com",
      "publicId": "GTM-53F6J2WX",
      "usageContext": [
        "WEB"
      ]
    },
    "tag": [
      {
        "accountId": "1",
        "containerId": "1",
        "tagId": "1",
        "name": "GA4 - Google Tag (All Pages)",
        "type": "gaawc",
        "parameter": [
          {
            "type": "TEMPLATE",
            "key": "measurementId",
            "value": "{{GA4 Measurement ID}}"
          }
        ],
        "firingTriggerId": [
          "2147479553"
        ],
        "monitoringMetadata": {
          "type": "MAP"
        }
      },
      {
        "accountId": "1",
        "containerId": "1",
        "tagId": "2",
        "name": "GA4 Event - CTA Click",
        "type": "gaawe",
        "parameter": [
          {
            "type": "TEMPLATE",
            "key": "measurementIdOverride",
            "value": "{{GA4 Measurement ID}}"
          },
          {
            "type": "TEMPLATE",
            "key": "eventName",
            "value": "cta_click"
          },
          {
            "type": "LIST",
            "key": "eventParameters",
            "list": [
              {
                "type": "MAP",
                "map": [
                  {
                    "type": "TEMPLATE",
                    "key": "name",
                    "value": "button_label"
                  },
                  {
                    "type": "TEMPLATE",
                    "key": "value",
                    "value": "{{dlv - cta_label}}"
                  }
                ]
              },
              {
                "type": "MAP",
                "map": [
                  {
                    "type": "TEMPLATE",
                    "key": "name",
                    "value": "utm_source"
                  },
                  {
                    "type": "TEMPLATE",
                    "key": "value",
                    "value": "{{dlv - utm_source}}"
                  }
                ]
              },
              {
                "type": "MAP",
                "map": [
                  {
                    "type": "TEMPLATE",
                    "key": "name",
                    "value": "utm_campaign"
                  },
                  {
                    "type": "TEMPLATE",
                    "key": "value",
                    "value": "{{dlv - utm_campaign}}"
                  }
                ]
              }
            ]
          }
        ],
        "firingTriggerId": [
          "2"
        ]
      }
    ],
    "trigger": [
      {
        "accountId": "1",
        "containerId": "1",
        "triggerId": "2",
        "name": "Event - cta_click",
        "type": "CUSTOM_EVENT",
        "customEventFilter": [
          {
            "type": "EQUALS",
            "parameter": [
              {
                "type": "TEMPLATE",
                "key": "arg0",
                "value": "{{_event}}"
              },
              {
                "type": "TEMPLATE",
                "key": "arg1",
                "value": "cta_click"
              }
            ]
          }
        ]
      }
    ],
    "variable": [
      {
        "accountId": "1",
        "containerId": "1",
        "variableId": "1",
        "name": "GA4 Measurement ID",
        "type": "c",
        "parameter": [
          {
            "type": "TEMPLATE",
            "key": "value",
            "value": "G-MEASUREMENT-ID-HERE"
          }
        ]
      },
      {
        "accountId": "1",
        "containerId": "1",
        "variableId": "2",
        "name": "dlv - utm_source",
        "type": "v",
        "parameter": [
          {
            "type": "TEMPLATE",
            "key": "name",
            "value": "utm.utm_source"
          },
          {
            "type": "INTEGER",
            "key": "dataLayerVersion",
            "value": "2"
          }
        ]
      },
      {
        "accountId": "1",
        "containerId": "1",
        "variableId": "3",
        "name": "dlv - utm_campaign",
        "type": "v",
        "parameter": [
          {
            "type": "TEMPLATE",
            "key": "name",
            "value": "utm.utm_campaign"
          },
          {
            "type": "INTEGER",
            "key": "dataLayerVersion",
            "value": "2"
          }
        ]
      },
      {
        "accountId": "1",
        "containerId": "1",
        "variableId": "4",
        "name": "dlv - cta_label",
        "type": "v",
        "parameter": [
          {
            "type": "TEMPLATE",
            "key": "name",
            "value": "cta_label"
          },
          {
            "type": "INTEGER",
            "key": "dataLayerVersion",
            "value": "2"
          }
        ]
      }
    ],
    "builtInVariable": [
      {
        "accountId": "1",
        "containerId": "1",
        "type": "PAGE_URL",
        "name": "Page URL"
      },
      {
        "accountId": "1",
        "containerId": "1",
        "type": "EVENT",
        "name": "Event"
      }
    ]
  }
}"""


class TelemetryProvider:
    """Standalone TelemetryProvider for GTM container IaC, site verification, and GA4 telemetry warm-up."""

    def __init__(self, config: Optional[TelemetryConfig] = None) -> None:
        self.config = config or TelemetryConfig.load()

    def resolve_measurement_id(self, domain: Optional[str] = None) -> str:
        d = domain or self.config.domain
        if self.config.ga4_measurement_id:
            return self.config.ga4_measurement_id
        return "G-HJJ9TK2TKY"

    def compile_container_manifest(
        self, measurement_id: Optional[str] = None, output_dir: Optional[Path] = None
    ) -> Path:
        m_id = measurement_id or self.resolve_measurement_id()
        updated_content = DEFAULT_CONTAINER_SPEC_JSON.replace("G-MEASUREMENT-ID-HERE", m_id)

        target_dir = output_dir or Path.home() / ".local" / "share" / "gtm_telemetry_wizard"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "gtm-container-compiled.json"
        target_path.write_text(updated_content, encoding="utf-8")
        logger.info("Compiled GTM IaC manifest for GA4 ID %s at %s", m_id, target_path)
        return target_path

    def verify_live_telemetry(self, target_url: Optional[str] = None) -> dict[str, Any]:
        url = target_url or f"https://{self.config.domain}/?utm_source=email_sequence&utm_medium=email"
        results: dict[str, Any] = {
            "target_url": url,
            "data_layer_events": [],
            "network_requests": [],
            "gtm_script_loaded": False,
        }

        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()

                net_reqs: list[str] = []
                page.on("request", lambda req: net_reqs.append(req.url))

                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                except Exception as err:
                    logger.warning("Telemetry verification page load timeout/error: %s", err)

                data_layer = page.evaluate("() => window.dataLayer || []")
                results["data_layer_events"] = data_layer
                results["network_requests"] = [r for r in net_reqs if "googletagmanager.com" in r or "google-analytics.com" in r]
                results["gtm_script_loaded"] = any("googletagmanager.com/gtm.js" in r for r in net_reqs)

                browser.close()
        except Exception as p_err:
            logger.warning("Playwright verification error: %s", p_err)

        return results

    def ping_ga4_measurement_id(
        self, measurement_id: Optional[str] = None, domain: Optional[str] = None
    ) -> dict[str, Any]:
        m_id = measurement_id or self.resolve_measurement_id()
        d = domain or self.config.domain
        import urllib.request

        url = f"https://www.google-analytics.com/g/collect?v=2&tid={m_id}&cid=10000.67890&en=page_view&dl=https%3A%2F%2F{d}%2F&dt=Initial%20Setup"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status in (200, 204):
                    logger.info("Successfully sent initial telemetry ping to GA4 ID %s (HTTP %s)", m_id, resp.status)
                    return {"success": True, "status": resp.status}
                return {"success": False, "status": resp.status}
        except Exception as err:
            logger.warning("Initial telemetry ping note: %s", err)
            return {"success": False, "error": str(err)}

    def check_telemetry_status(self, domain: Optional[str] = None) -> dict[str, Any]:
        d = domain or self.config.domain
        manifest_path = Path.home() / ".local" / "share" / "gtm_telemetry_wizard" / "gtm-container-compiled.json"

        status: dict[str, Any] = {
            "active_account": None,
            "gcloud_token_valid": False,
            "ga4_measurement_id": self.resolve_measurement_id(domain=d),
            "compiled_manifest_exists": manifest_path.exists(),
            "compiled_manifest_path": str(manifest_path),
        }

        try:
            res = subprocess.run(["gcloud", "auth", "list", "--format=json"], capture_output=True, text=True, check=False)
            if res.returncode == 0 and res.stdout.strip():
                accounts = json.loads(res.stdout)
                for acc in accounts:
                    if acc.get("status") == "ACTIVE":
                        status["active_account"] = acc.get("account")
                        break
        except Exception as err:
            logger.debug("gcloud check note: %s", err)

        try:
            tok_res = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True, check=False)
            if tok_res.returncode == 0 and tok_res.stdout.strip():
                status["gcloud_token_valid"] = True
        except Exception as err:
            logger.debug("gcloud token check note: %s", err)

        return status
