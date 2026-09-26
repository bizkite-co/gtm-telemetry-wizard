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
                {"publicId": "GTM-NEW456", "containerId": "789"},
            ]

            with patch.object(TelemetryProvider, "_access_token", return_value="token"), patch.object(
                GoogleApiClient, "post", side_effect=responses
            ):
                written_path = provider.provision()

            written = TelemetryConfig.load(config_path=written_path)
            self.assertEqual(written.domain, "image-annex.store")
            self.assertEqual(written.ga4_measurement_id, "G-NEW123")
            self.assertEqual(written.container_id, "GTM-NEW456")
            self.assertEqual(written.gtm_container_api_id, "789")

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


class DeploymentTests(unittest.TestCase):
    def test_deploy_imports_manifest_and_publishes_version(self) -> None:
        config = TelemetryConfig(
            domain="image-annex.store",
            container_id="GTM-NEW456",
            gtm_container_api_id="789",
            ga4_measurement_id="G-NEW123",
            gtm_account_id="456",
        )
        responses = [
            {"workspaceId": "111"},
            {"triggerId": "222"},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {},
            {"containerVersion": {"containerVersionId": "333"}},
            {},
        ]
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(TelemetryProvider, "_access_token", return_value="token"), patch.object(
                GoogleApiClient, "post", side_effect=responses
            ) as post:
                result = TelemetryProvider(config).deploy_container(output_dir=Path(directory))

        self.assertEqual(result, {"workspace_id": "111", "version_id": "333", "published": "true"})
        calls = [call.args[0] for call in post.call_args_list]
        self.assertTrue(any(url.endswith("/workspaces") for url in calls))
        self.assertTrue(any(url.endswith("/triggers") for url in calls))
        self.assertTrue(any(url.endswith("/variables") for url in calls))
        self.assertTrue(any(url.endswith("/built_in_variables") for url in calls))
        self.assertTrue(any(url.endswith("/tags") for url in calls))
        self.assertTrue(any(url.endswith(":create_version") for url in calls))
        self.assertTrue(any(url.endswith("/versions/333:publish") for url in calls))

    def test_deploy_requires_gtm_api_container_id(self) -> None:
        config = TelemetryConfig(
            domain="image-annex.store",
            container_id="GTM-NEW456",
            ga4_measurement_id="G-NEW123",
            gtm_account_id="456",
        )

        with self.assertRaisesRegex(ConfigurationError, "GTM API container ID"):
            TelemetryProvider(config).deploy_container()


class QueryAnalyticsTests(unittest.TestCase):
    def test_query_requires_property_id_when_not_discoverable(self) -> None:
        config = TelemetryConfig(domain="example.com")
        with self.assertRaisesRegex(ConfigurationError, "property ID"):
            TelemetryProvider(config).query_analytics()

    def test_query_analytics_run_report(self) -> None:
        config = TelemetryConfig(domain="example.com", ga4_property_id="123456")
        expected_response = {
            "dimensionHeaders": [{"name": "pagePath"}, {"name": "sessionCampaignName"}],
            "metricHeaders": [{"name": "activeUsers"}],
            "rows": [
                {
                    "dimensionValues": [{"value": "/testimonials/"}, {"value": "testimonials"}],
                    "metricValues": [{"value": "5"}],
                }
            ],
        }
        with patch.object(TelemetryProvider, "_access_token", return_value="token"), patch.object(
            GoogleApiClient, "post", return_value=expected_response
        ) as post:
            result = TelemetryProvider(config).query_analytics(campaign="testimonials", days=3)

        self.assertEqual(result, expected_response)
        url, payload = post.call_args.args
        self.assertIn("/properties/123456:runReport", url)
        self.assertEqual(payload["dateRanges"], [{"startDate": "3daysAgo", "endDate": "today"}])
        self.assertEqual(
            payload["dimensionFilter"],
            {
                "filter": {
                    "fieldName": "sessionCampaignName",
                    "stringFilter": {"matchType": "CONTAINS", "value": "testimonials"},
                }
            },
        )

    def test_query_analytics_cli_command(self) -> None:
        runner = CliRunner()
        mock_response = {
            "dimensionHeaders": [{"name": "pagePath"}],
            "metricHeaders": [{"name": "activeUsers"}],
            "rows": [
                {
                    "dimensionValues": [{"value": "/testimonials/"}],
                    "metricValues": [{"value": "3"}],
                }
            ],
        }
        with patch.object(TelemetryProvider, "_access_token", return_value="token"), patch.object(
            GoogleApiClient, "post", return_value=mock_response
        ):
            result = runner.invoke(app, ["query", "--property-id", "999999", "--campaign", "testimonials"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("Google Analytics 4 Data Report", result.output)
        self.assertIn("/testimonials/", result.output)

