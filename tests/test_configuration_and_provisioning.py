import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from gtm_telemetry_wizard.cli import app
from gtm_telemetry_wizard.config import ConfigurationError, TelemetryConfig
from gtm_telemetry_wizard.service import GoogleApiClient, ProvisioningError, TelemetryProvider


class ConfigurationTests(unittest.TestCase):
    def test_new_configuration_has_no_campaign_defaults(self) -> None:
        config = TelemetryConfig()

        self.assertIsNone(config.domain)
        self.assertIsNone(config.container_id)
        self.assertIsNone(config.ga4_measurement_id)

    def test_missing_values_have_an_actionable_error(self) -> None:
        with self.assertRaisesRegex(ConfigurationError, "campaign domain") as raised:
            TelemetryConfig().require("domain", "container_id", "ga4_measurement_id")

        self.assertIn("gtw provision", raised.exception.solution)

    def test_sync_exits_before_creating_a_manifest_when_config_is_incomplete(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "campaign" / "telemetry.toml"
            result = runner.invoke(app, ["sync", "--config", str(config_path)])

        self.assertEqual(result.exit_code, 2)
        self.assertIn("Unable to continue", result.output)
        self.assertIn("campaign domain", result.output)
        self.assertIn("Solution:", result.output)


class ProvisioningTests(unittest.TestCase):
    def test_provision_refuses_to_overwrite_existing_campaign_ids(self) -> None:
        config = TelemetryConfig(
            domain="image-annex.store",
            container_id="GTM-EXISTING",
            analytics_account_id="analytics-123",
            gtm_account_id="gtm-456",
        )

        with self.assertRaisesRegex(ProvisioningError, "already contains"):
            TelemetryProvider(config).provision()

    def test_provision_persists_mocked_google_ids_to_requested_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "campaign" / "telemetry.toml"
            config = TelemetryConfig.load(
                config_path=config_path,
                domain="image-annex.store",
                analytics_account_id="analytics-123",
                gtm_account_id="gtm-456",
            )
            provider = TelemetryProvider(config)
            responses = [
                {"name": "properties/123"},
                {
                    "name": "properties/123/dataStreams/456",
                    "webStreamData": {"measurementId": "G-NEW123"},
                },
                {"publicId": "GTM-NEW456"},
            ]

            with patch.object(TelemetryProvider, "_access_token", return_value="token"), patch.object(
                GoogleApiClient, "post", side_effect=responses
            ):
                written_path = provider.provision()

            written = TelemetryConfig.load(config_path=written_path)
            self.assertEqual(written.domain, "image-annex.store")
            self.assertEqual(written.ga4_measurement_id, "G-NEW123")
            self.assertEqual(written.container_id, "GTM-NEW456")

    def test_manifest_uses_configured_ids(self) -> None:
        config = TelemetryConfig(
            domain="image-annex.store",
            container_id="GTM-NEW456",
            ga4_measurement_id="G-NEW123",
        )
        with tempfile.TemporaryDirectory() as directory:
            manifest = TelemetryProvider(config).compile_container_manifest(
                output_dir=Path(directory)
            )

            content = manifest.read_text(encoding="utf-8")
            self.assertIn("image-annex.store", content)
            self.assertIn("GTM-NEW456", content)
            self.assertIn("G-NEW123", content)
            self.assertNotIn("getretirementtaxanalyzer.com", content)
