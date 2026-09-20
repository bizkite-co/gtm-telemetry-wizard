from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


class ConfigurationError(ValueError):
    """A missing campaign setting with an actionable resolution."""

    def __init__(self, missing: Iterable[str]) -> None:
        self.missing = tuple(missing)
        labels = {
            "domain": "campaign domain",
            "container_id": "GTM container ID",
            "gtm_container_api_id": "GTM API container ID",
            "ga4_measurement_id": "GA4 measurement ID",
            "analytics_account_id": "Google Analytics account ID",
            "gtm_account_id": "Google Tag Manager account ID",
        }
        fields = ", ".join(labels[field] for field in self.missing)
        if "gtm_container_api_id" in self.missing:
            solution = (
                "Add the numeric Tag Manager container ID as `gtm_container_api_id` "
                "in telemetry.toml, or run `gtw provision` for a new campaign."
            )
        elif {"container_id", "ga4_measurement_id"} & set(self.missing):
            solution = (
                "Run `gtw provision --domain YOUR_DOMAIN --analytics-account-id "
                "ANALYTICS_ACCOUNT_ID --gtm-account-id GTM_ACCOUNT_ID`, or add the "
                "missing values to telemetry.toml."
            )
        else:
            solution = "Pass the missing option or add it to telemetry.toml."
        super().__init__(f"Missing {fields}.")
        self.solution = solution

    @classmethod
    def from_reason(cls, reason: str, solution: str) -> ConfigurationError:
        error = cls.__new__(cls)
        ValueError.__init__(error, reason)
        error.missing = ()
        error.solution = solution
        return error


@dataclass
class TelemetryConfig:
    domain: Optional[str] = None
    container_id: Optional[str] = None
    gtm_container_api_id: Optional[str] = None
    ga4_measurement_id: Optional[str] = None
    analytics_account_id: Optional[str] = None
    gtm_account_id: Optional[str] = None
    campaign_name: Optional[str] = None
    deploy_mode: str = "browser"
    headful: bool = True
    config_path: Optional[Path] = None

    @classmethod
    def load(cls, config_path: Optional[Path] = None, **overrides: Any) -> TelemetryConfig:
        path = config_path or Path("telemetry.toml")
        cfg = cls(config_path=path)
        if path.exists():
            try:
                with path.open("rb") as file:
                    data = tomllib.load(file)
            except (OSError, tomllib.TOMLDecodeError) as error:
                raise ConfigurationError.from_reason(
                    f"Could not read configuration file {path}: {error}",
                    "Fix the TOML syntax or pass a readable path with `--config`.",
                ) from error
            site_data = data.get("site", {})
            deployment_data = data.get("deployment", {})
            cfg.domain = site_data.get("domain")
            cfg.container_id = site_data.get("container_id")
            cfg.gtm_container_api_id = site_data.get("gtm_container_api_id")
            cfg.ga4_measurement_id = site_data.get("ga4_measurement_id")
            cfg.analytics_account_id = site_data.get("analytics_account_id")
            cfg.gtm_account_id = site_data.get("gtm_account_id")
            cfg.campaign_name = site_data.get("campaign_name")
            cfg.deploy_mode = deployment_data.get("mode", cfg.deploy_mode)
            cfg.headful = deployment_data.get("headful", cfg.headful)

        for env_name, field_name in (
            ("TELEMETRY_DOMAIN", "domain"),
            ("GTM_CONTAINER_ID", "container_id"),
            ("GTM_API_CONTAINER_ID", "gtm_container_api_id"),
            ("GA4_MEASUREMENT_ID", "ga4_measurement_id"),
            ("GA4_ACCOUNT_ID", "analytics_account_id"),
            ("GTM_ACCOUNT_ID", "gtm_account_id"),
        ):
            if value := os.environ.get(env_name):
                setattr(cfg, field_name, value)

        for field_name, value in overrides.items():
            if value is not None and hasattr(cfg, field_name):
                setattr(cfg, field_name, value)

        return cfg

    def require(self, *fields: str) -> None:
        missing = [field for field in fields if not getattr(self, field)]
        if missing:
            raise ConfigurationError(missing)

    def write(self) -> Path:
        self.require("domain", "container_id", "ga4_measurement_id")
        path = self.config_path or Path("telemetry.toml")
        path.parent.mkdir(parents=True, exist_ok=True)
        site_values = {
            "domain": self.domain,
            "container_id": self.container_id,
            "gtm_container_api_id": self.gtm_container_api_id,
            "ga4_measurement_id": self.ga4_measurement_id,
            "analytics_account_id": self.analytics_account_id,
            "gtm_account_id": self.gtm_account_id,
            "campaign_name": self.campaign_name,
        }
        lines = ["[site]"]
        lines.extend(
            f"{key} = {json.dumps(value)}"
            for key, value in site_values.items()
            if value is not None
        )
        lines.extend(
            [
                "",
                "[deployment]",
                f"mode = {json.dumps(self.deploy_mode)}",
                f"headful = {'true' if self.headful else 'false'}",
                "",
            ]
        )
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            file.write("\n".join(lines))
            temp_path = Path(file.name)
        temp_path.replace(path)
        self.config_path = path
        return path
