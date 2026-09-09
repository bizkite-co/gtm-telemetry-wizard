from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass, field

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]


@dataclass
class TelemetryConfig:
    domain: str = "getretirementtaxanalyzer.com"
    container_id: str = "GTM-53F6J2WX"
    ga4_measurement_id: Optional[str] = "G-HJJ9TK2TKY"
    campaign_name: str = "roadmap"
    deploy_mode: str = "browser"  # 'browser' or 'api'
    headful: bool = True
    config_path: Optional[Path] = None

    @classmethod
    def load(cls, config_path: Optional[Path] = None, **overrides: Any) -> TelemetryConfig:
        cfg = cls()
        path = config_path or Path("telemetry.toml")
        if path.exists():
            try:
                with path.open("rb") as f:
                    data = tomllib.load(f)
                    site_data = data.get("site", {})
                    deploy_data = data.get("deployment", {})
                    cfg.domain = site_data.get("domain", cfg.domain)
                    cfg.container_id = site_data.get("container_id", cfg.container_id)
                    cfg.ga4_measurement_id = site_data.get("ga4_measurement_id", cfg.ga4_measurement_id)
                    cfg.campaign_name = site_data.get("campaign_name", cfg.campaign_name)
                    cfg.deploy_mode = deploy_data.get("mode", cfg.deploy_mode)
                    cfg.headful = deploy_data.get("headful", cfg.headful)
                    cfg.config_path = path
            except Exception as err:
                pass

        # Override from env vars if present
        if os.environ.get("TELEMETRY_DOMAIN"):
            cfg.domain = os.environ["TELEMETRY_DOMAIN"]
        if os.environ.get("GTM_CONTAINER_ID"):
            cfg.container_id = os.environ["GTM_CONTAINER_ID"]
        if os.environ.get("GA4_MEASUREMENT_ID"):
            cfg.ga4_measurement_id = os.environ["GA4_MEASUREMENT_ID"]

        # Apply explicit keyword overrides
        for k, v in overrides.items():
            if v is not None and hasattr(cfg, k):
                setattr(cfg, k, v)

        return cfg
