from __future__ import annotations

import json
import logging
import subprocess
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

from .config import ConfigurationError, TelemetryConfig

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
      "name": "{{GTM_CONTAINER_NAME}}",
      "publicId": "{{GTM_CONTAINER_ID}}",
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


class ProvisioningError(RuntimeError):
    """An external provisioning failure with an actionable resolution."""

    def __init__(self, reason: str, solution: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.solution = solution


class GoogleApiClient:
    """Minimal authenticated client for the Google Analytics and Tag Manager APIs."""

    def __init__(self, access_token: str) -> None:
        self.access_token = access_token

    def post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.access_token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            try:
                details = json.load(error)
                reason = details.get("error", {}).get("message", str(error))
            except (json.JSONDecodeError, OSError):
                reason = str(error)
            raise ProvisioningError(
                f"Google API request failed: {reason}",
                "Confirm the selected account IDs, enable the Analytics Admin and Tag Manager APIs, "
                "and authenticate with analytics.edit and tagmanager.edit.containers scopes.",
            ) from error
        except OSError as error:
            raise ProvisioningError(
                f"Could not reach the Google API: {error}",
                "Check your network connection and retry.",
            ) from error


class TelemetryProvider:
    """Standalone TelemetryProvider for GTM container IaC, site verification, and GA4 telemetry warm-up."""

    def __init__(self, config: Optional[TelemetryConfig] = None) -> None:
        self.config = config or TelemetryConfig.load()

    def resolve_measurement_id(self) -> str:
        self.config.require("ga4_measurement_id")
        return self.config.ga4_measurement_id or ""

    @staticmethod
    def _account_path(account_id: str) -> str:
        return account_id if account_id.startswith("accounts/") else f"accounts/{account_id}"

    @staticmethod
    def _access_token() -> str:
        try:
            result = subprocess.run(
                ["gcloud", "auth", "application-default", "print-access-token"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as error:
            raise ProvisioningError(
                "gcloud is not installed.",
                "Install the Google Cloud CLI, then run `gcloud auth application-default login`.",
            ) from error
        if result.returncode != 0 or not result.stdout.strip():
            raise ProvisioningError(
                "No Application Default Credentials are available.",
                "Run `gcloud auth application-default login --scopes="
                "https://www.googleapis.com/auth/analytics.edit,"
                "https://www.googleapis.com/auth/tagmanager.edit.containers`.",
            )
        return result.stdout.strip()

    def provision(self) -> Path:
        self.config.require("domain", "analytics_account_id", "gtm_account_id")
        if self.config.container_id or self.config.ga4_measurement_id:
            raise ProvisioningError(
                "This configuration already contains a GA4 measurement ID or GTM container ID.",
                "Use the existing IDs, or remove both IDs only when you intentionally want to create "
                "a new Analytics property and Tag Manager container.",
            )
        domain = self.config.domain or ""
        analytics_parent = self._account_path(self.config.analytics_account_id or "")
        gtm_parent = self._account_path(self.config.gtm_account_id or "")
        client = GoogleApiClient(self._access_token())

        property_data = client.post(
            "https://analyticsadmin.googleapis.com/v1alpha/properties",
            {
                "displayName": domain,
                "parent": analytics_parent,
                "timeZone": "Etc/UTC",
                "currencyCode": "USD",
            },
        )
        property_name = property_data.get("name")
        if not property_name:
            raise ProvisioningError(
                "Google Analytics did not return a property name.",
                "Review the Analytics Admin API response and retry provisioning.",
            )
        stream_data = client.post(
            f"https://analyticsadmin.googleapis.com/v1alpha/{property_name}/dataStreams",
            {
                "displayName": domain,
                "type": "WEB_DATA_STREAM",
                "webStreamData": {"defaultUri": f"https://{domain}"},
            },
        )
        measurement_id = stream_data.get("webStreamData", {}).get("measurementId")
        if not measurement_id:
            raise ProvisioningError(
                "Google Analytics did not return a web-stream measurement ID.",
                "Review the Analytics Admin API response; the property was created but is not configured.",
            )
        container_data = client.post(
            f"https://tagmanager.googleapis.com/tagmanager/v2/{gtm_parent}/containers",
            {"name": domain, "usageContext": ["web"]},
        )
        container_id = container_data.get("publicId")
        container_api_id = container_data.get("containerId")
        if not container_id or not container_api_id:
            raise ProvisioningError(
                "Google Tag Manager did not return both a public and API container ID.",
                "Review the Tag Manager API response; the Analytics property and data stream were created.",
            )

        self.config.ga4_measurement_id = measurement_id
        self.config.container_id = container_id
        self.config.gtm_container_api_id = str(container_api_id)
        return self.config.write()

    @staticmethod
    def _resource_payload(resource: dict[str, Any], identity_fields: set[str]) -> dict[str, Any]:
        return {
            key: deepcopy(value)
            for key, value in resource.items()
            if key not in identity_fields
        }

    def deploy_container(self, publish: bool = True) -> dict[str, str]:
        self.config.require(
            "domain",
            "container_id",
            "ga4_measurement_id",
            "gtm_account_id",
            "gtm_container_api_id",
        )
        manifest_path = self.compile_container_manifest()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        container_version = manifest["containerVersion"]
        account_path = self._account_path(self.config.gtm_account_id or "")
        container_path = f"{account_path}/containers/{self.config.gtm_container_api_id}"
        client = GoogleApiClient(self._access_token())

        workspace = client.post(
            f"https://tagmanager.googleapis.com/tagmanager/v2/{container_path}/workspaces",
            {"name": f"gtw deploy {self.config.domain}"},
        )
        workspace_id = workspace.get("workspaceId")
        if not workspace_id:
            raise ProvisioningError(
                "Google Tag Manager did not return a workspace ID.",
                "Review the Tag Manager API response and retry deployment.",
            )
        workspace_path = f"{container_path}/workspaces/{workspace_id}"
        trigger_ids: dict[str, str] = {}
        for trigger in container_version.get("trigger", []):
            original_id = str(trigger.get("triggerId", ""))
            created = client.post(
                f"https://tagmanager.googleapis.com/tagmanager/v2/{workspace_path}/triggers",
                self._resource_payload(
                    trigger,
                    {"accountId", "containerId", "workspaceId", "triggerId", "path", "fingerprint"},
                ),
            )
            if original_id and created.get("triggerId"):
                trigger_ids[original_id] = str(created["triggerId"])

        for variable in container_version.get("variable", []):
            client.post(
                f"https://tagmanager.googleapis.com/tagmanager/v2/{workspace_path}/variables",
                self._resource_payload(
                    variable,
                    {"accountId", "containerId", "workspaceId", "variableId", "path", "fingerprint"},
                ),
            )

        for variable in container_version.get("builtInVariable", []):
            client.post(
                f"https://tagmanager.googleapis.com/tagmanager/v2/{workspace_path}/built_in_variables",
                self._resource_payload(
                    variable,
                    {"accountId", "containerId", "workspaceId", "path", "fingerprint"},
                ),
            )

        for tag in container_version.get("tag", []):
            payload = self._resource_payload(
                tag,
                {"accountId", "containerId", "workspaceId", "tagId", "path", "fingerprint"},
            )
            payload["firingTriggerId"] = [
                trigger_ids.get(str(trigger_id), str(trigger_id))
                for trigger_id in payload.get("firingTriggerId", [])
            ]
            client.post(
                f"https://tagmanager.googleapis.com/tagmanager/v2/{workspace_path}/tags",
                payload,
            )

        version_response = client.post(
            f"https://tagmanager.googleapis.com/tagmanager/v2/{workspace_path}:create_version",
            {"name": f"gtw deploy {self.config.domain}"},
        )
        version = version_response.get("containerVersion", version_response)
        version_id = version.get("containerVersionId")
        if not version_id:
            raise ProvisioningError(
                "Google Tag Manager did not return a container version ID.",
                "The workspace was populated but was not published; review it in Tag Manager.",
            )
        result = {"workspace_id": str(workspace_id), "version_id": str(version_id)}
        if publish:
            client.post(
                f"https://tagmanager.googleapis.com/tagmanager/v2/{container_path}/versions/{version_id}:publish",
                {},
            )
            result["published"] = "true"
        else:
            result["published"] = "false"
        return result

    def compile_container_manifest(
        self, measurement_id: Optional[str] = None, output_dir: Optional[Path] = None
    ) -> Path:
        self.config.require("domain", "container_id", "ga4_measurement_id")
        m_id = measurement_id or self.resolve_measurement_id()
        updated_content = (
            DEFAULT_CONTAINER_SPEC_JSON.replace("G-MEASUREMENT-ID-HERE", m_id)
            .replace("{{GTM_CONTAINER_NAME}}", self.config.domain or "")
            .replace("{{GTM_CONTAINER_ID}}", self.config.container_id or "")
        )

        target_dir = output_dir or Path.home() / ".local" / "share" / "gtm_telemetry_wizard"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "gtm-container-compiled.json"
        target_path.write_text(updated_content, encoding="utf-8")
        logger.info("Compiled GTM IaC manifest for GA4 ID %s at %s", m_id, target_path)
        return target_path

    def verify_live_telemetry(self, target_url: Optional[str] = None) -> dict[str, Any]:
        self.config.require("domain")
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
        m_id = measurement_id or self.config.ga4_measurement_id
        d = domain or self.config.domain
        missing = []
        if not d:
            missing.append("domain")
        if not m_id:
            missing.append("ga4_measurement_id")
        if missing:
            raise ConfigurationError(missing)

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
        self.config.require("domain", "ga4_measurement_id", "container_id")
        manifest_path = Path.home() / ".local" / "share" / "gtm_telemetry_wizard" / "gtm-container-compiled.json"

        status: dict[str, Any] = {
            "active_account": None,
            "gcloud_token_valid": False,
            "ga4_measurement_id": self.resolve_measurement_id(),
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
