import json
import unittest
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from gtm_telemetry_wizard.auth import (
    ALL_SCOPES,
    AccountScopeStatus,
    check_account_scopes,
    ensure_account_scopes,
    list_gcloud_accounts,
    scopes_arg,
)
from gtm_telemetry_wizard.cli import app


def _completed(returncode: int = 0, stdout: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    return result


class ScopesArgTests(unittest.TestCase):
    def test_scopes_arg_is_comma_joined(self) -> None:
        self.assertEqual(scopes_arg(("a", "b", "c")), "a,b,c")

    def test_all_scopes_includes_analytics_and_tagmanager_read_scopes(self) -> None:
        self.assertIn("https://www.googleapis.com/auth/analytics.readonly", ALL_SCOPES)
        self.assertIn("https://www.googleapis.com/auth/tagmanager.readonly", ALL_SCOPES)


class ListGcloudAccountsTests(unittest.TestCase):
    def test_parses_account_emails_from_gcloud_json(self) -> None:
        payload = json.dumps([{"account": "a@example.com"}, {"account": "b@example.com"}])
        with patch("subprocess.run", return_value=_completed(0, payload)):
            self.assertEqual(list_gcloud_accounts(), ["a@example.com", "b@example.com"])

    def test_returns_empty_list_when_gcloud_fails(self) -> None:
        with patch("subprocess.run", return_value=_completed(1, "")):
            self.assertEqual(list_gcloud_accounts(), [])


class CheckAccountScopesTests(unittest.TestCase):
    def test_reports_missing_when_token_lacks_a_required_scope(self) -> None:
        token_result = _completed(0, "faketoken\n")
        tokeninfo = MagicMock()
        tokeninfo.__enter__.return_value.read = MagicMock()
        with patch("subprocess.run", return_value=token_result), patch(
            "urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = MagicMock(
                read=lambda: json.dumps({"scope": "openid email"}).encode()
            )
            status = check_account_scopes("a@example.com", required=("openid", "https://x/analytics"))

        self.assertFalse(status.ok)
        self.assertEqual(status.missing, ("https://x/analytics",))

    def test_ok_when_all_required_scopes_present(self) -> None:
        token_result = _completed(0, "faketoken\n")
        with patch("subprocess.run", return_value=token_result), patch(
            "urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = MagicMock(
                read=lambda: json.dumps({"scope": "openid email analytics"}).encode()
            )
            status = check_account_scopes("a@example.com", required=("openid", "analytics"))

        self.assertTrue(status.ok)

    def test_error_when_no_gcloud_token_for_account(self) -> None:
        with patch("subprocess.run", return_value=_completed(1, "")):
            status = check_account_scopes("a@example.com")

        self.assertFalse(status.ok)
        self.assertIsNotNone(status.error)


class EnsureAccountScopesTests(unittest.TestCase):
    def test_does_not_run_login_when_already_ok(self) -> None:
        ok_status = AccountScopeStatus("a@example.com", granted_scopes=frozenset(ALL_SCOPES))
        with patch(
            "gtm_telemetry_wizard.auth.check_account_scopes", return_value=ok_status
        ), patch("subprocess.run") as mock_run:
            result = ensure_account_scopes("a@example.com")

        mock_run.assert_not_called()
        self.assertTrue(result.ok)

    def test_runs_login_when_scopes_missing(self) -> None:
        missing_status = AccountScopeStatus("a@example.com", missing=("https://x/analytics",))
        ok_status = AccountScopeStatus("a@example.com", granted_scopes=frozenset(ALL_SCOPES))
        with patch(
            "gtm_telemetry_wizard.auth.check_account_scopes",
            side_effect=[missing_status, ok_status],
        ), patch("subprocess.run") as mock_run:
            result = ensure_account_scopes("a@example.com", required=("https://x/analytics",))

        mock_run.assert_called_once()
        login_cmd = mock_run.call_args.args[0]
        self.assertEqual(login_cmd[:3], ["gcloud", "auth", "login"])
        self.assertIn("a@example.com", login_cmd)
        self.assertTrue(result.ok)


class AuthCliTests(unittest.TestCase):
    def test_auth_scopes_prints_canonical_list(self) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["auth", "scopes"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("analytics.readonly", result.output)

    def test_auth_status_reports_missing_scopes(self) -> None:
        runner = CliRunner()
        status = AccountScopeStatus("a@example.com", missing=("https://x/analytics",))
        with patch("gtm_telemetry_wizard.cli.check_account_scopes", return_value=status):
            result = runner.invoke(app, ["auth", "status", "a@example.com"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("a@example.com", result.output)

    def test_auth_login_reports_success(self) -> None:
        runner = CliRunner()
        ok_status = AccountScopeStatus("a@example.com", granted_scopes=frozenset(ALL_SCOPES))
        with patch("gtm_telemetry_wizard.cli.ensure_account_scopes", return_value=ok_status) as mock_ensure:
            result = runner.invoke(app, ["auth", "login", "a@example.com"])

        self.assertEqual(result.exit_code, 0)
        mock_ensure.assert_called_once_with("a@example.com", force=False)
        self.assertIn("has all required scopes", result.output)


class AccountsDiscoverCliTests(unittest.TestCase):
    def test_discover_reports_no_access_when_account_lacks_scopes(self) -> None:
        from gtm_telemetry_wizard.service import ProvisioningError

        runner = CliRunner()
        with patch(
            "gtm_telemetry_wizard.cli.list_gcloud_accounts", return_value=["a@example.com"]
        ), patch(
            "gtm_telemetry_wizard.cli.TelemetryProvider._access_token",
            side_effect=ProvisioningError("No usable gcloud credentials for account a@example.com.", "Run `gtw auth login a@example.com`."),
        ):
            result = runner.invoke(app, ["accounts", "discover", "--measurement-id", "G-TEST"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("No access", result.output)

    def test_discover_lists_matching_property_for_authorized_account(self) -> None:
        from gtm_telemetry_wizard.service import DiscoveredProperty

        runner = CliRunner()
        match = DiscoveredProperty(
            account_name="accounts/1",
            account_display_name="My GA4 Account",
            property_id="123456",
            property_display_name="my-site",
            measurement_id="G-TEST",
            web_stream_default_uri="https://my-site.example",
        )
        with patch(
            "gtm_telemetry_wizard.cli.list_gcloud_accounts", return_value=["a@example.com"]
        ), patch(
            "gtm_telemetry_wizard.cli.TelemetryProvider._access_token", return_value="token"
        ), patch(
            "gtm_telemetry_wizard.cli.find_ga4_properties", return_value=[match]
        ):
            result = runner.invoke(app, ["accounts", "discover", "--measurement-id", "G-TEST"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("123456", result.output)
        self.assertIn("My GA4 Account", result.output)


if __name__ == "__main__":
    unittest.main()
