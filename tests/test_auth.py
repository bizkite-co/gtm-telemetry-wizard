import json
import re
import subprocess
import unittest
from unittest.mock import MagicMock, patch

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)

from typer.testing import CliRunner

from gtm_telemetry_wizard.auth import (
    ALL_SCOPES,
    AccountScopeStatus,
    check_adc_scopes,
    ensure_adc_scopes,
    scopes_arg,
)
from gtm_telemetry_wizard.cli import app


def _completed(returncode: int = 0, stdout: str = "") -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = stdout
    return result


class GcloudCliSurfaceTests(unittest.TestCase):
    """Regression guard for the actual bug hit in production: `auth.py`
    originally built commands against gcloud flags that don't exist
    (`gcloud auth login --scopes=...`), and the mocked unit tests couldn't
    catch it because they only asserted the code agreed with itself, not
    with the real CLI. These tests shell out to the installed gcloud and
    check its --help text for the exact flags this module relies on, so a
    wrong assumption fails here instead of in a live terminal.

    Skipped (not failed) if gcloud isn't installed in the test environment,
    since that's an environment gap, not a code regression.
    """

    def _gcloud_help(self, *args: str) -> str:
        try:
            result = subprocess.run(
                ["gcloud", *args, "--help"], capture_output=True, text=True, timeout=15
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.skipTest("gcloud not available in this environment")
        return result.stdout + result.stderr

    def test_auth_login_has_no_scopes_flag(self) -> None:
        help_text = self._gcloud_help("auth", "login")
        self.assertNotIn(
            "--scopes",
            help_text,
            "gcloud auth login gained a --scopes flag, or this assumption is stale either way - "
            "re-check auth.py's comment explaining why ensure_adc_scopes uses "
            "application-default login instead.",
        )

    def test_application_default_login_has_scopes_and_optional_account(self) -> None:
        help_text = _strip_ansi(self._gcloud_help("auth", "application-default", "login"))
        self.assertIn("--scopes", help_text)
        # ACCOUNT is documented as an optional positional in the synopsis
        # (ANSI-underlined in real terminal output, hence the strip above).
        self.assertIn("[ACCOUNT]", help_text)

    def test_application_default_print_access_token_cannot_pick_a_different_identity(self) -> None:
        """`--account` is a *universal* gcloud-wide flag on every command (it
        selects which credentialed account gcloud CLI itself authenticates
        as to talk to Google) - it does NOT let this specific command return
        a token for a different stored Application Default Credentials
        identity, because there is only ever one ADC file. The real
        constraint this module relies on is narrower and is spelled out
        explicitly in this command's own --scopes flag text: scopes are
        limited to a small fixed set unless they were already granted via
        `application-default login --scopes`. If Google ever adds real
        per-identity ADC selection, this specific sentence is what will
        change first."""
        help_text = _strip_ansi(
            self._gcloud_help("auth", "application-default", "print-access-token")
        )
        self.assertIn("previously specified through", help_text)
        self.assertIn("application-default login", help_text)


class ScopesArgTests(unittest.TestCase):
    def test_scopes_arg_is_comma_joined(self) -> None:
        self.assertEqual(scopes_arg(("a", "b", "c")), "a,b,c")

    def test_all_scopes_includes_analytics_and_tagmanager_read_scopes(self) -> None:
        self.assertIn("https://www.googleapis.com/auth/analytics.readonly", ALL_SCOPES)
        self.assertIn("https://www.googleapis.com/auth/tagmanager.readonly", ALL_SCOPES)


class CheckAdcScopesTests(unittest.TestCase):
    """check_adc_scopes mints a token scoped to exactly `required` and
    treats success/failure of THAT request as the capability check - it
    does not inspect a default/unscoped token's granted scopes. That
    distinction is the actual bug this replaced: a service account's
    default token is scoped to bare cloud-platform only (confirmed against
    a real service-account token) and never carries an `email` field, so
    checking a default token's scopes/email reported a fully-capable
    service account as "missing everything"."""

    def test_reports_missing_when_scoped_request_fails(self) -> None:
        # The scoped request (with --scopes=) fails; the fallback default
        # (unscoped) request succeeds, used only to identify who's active.
        scoped_fail = _completed(1, "")
        default_ok = _completed(0, "defaulttoken\n")
        with patch(
            "gtm_telemetry_wizard.auth._adc_identity_label", return_value=""
        ), patch("subprocess.run", side_effect=[scoped_fail, default_ok]), patch(
            "urllib.request.urlopen"
        ) as mock_urlopen:
            mock_urlopen.return_value.__enter__.return_value = MagicMock(
                read=lambda: json.dumps({"email": "a@example.com"}).encode()
            )
            status = check_adc_scopes(required=("https://x/analytics",))

        self.assertFalse(status.ok)
        self.assertEqual(status.account, "a@example.com")
        self.assertEqual(status.missing, ("https://x/analytics",))

    def test_ok_when_scoped_request_succeeds_even_without_email_in_tokeninfo(self) -> None:
        # Simulates a service account: the scoped print-access-token call
        # succeeds, tokeninfo would return no `email` at all, but the ADC
        # credentials file itself supplies client_email.
        with patch(
            "gtm_telemetry_wizard.auth._adc_identity_label",
            return_value="sa@project.iam.gserviceaccount.com",
        ), patch("subprocess.run", return_value=_completed(0, "scopedtoken\n")):
            status = check_adc_scopes(required=("https://x/analytics",))

        self.assertTrue(status.ok)
        self.assertEqual(status.account, "sa@project.iam.gserviceaccount.com")

    def test_error_when_no_adc_at_all(self) -> None:
        with patch(
            "gtm_telemetry_wizard.auth._adc_identity_label", return_value=""
        ), patch("subprocess.run", return_value=_completed(1, "")):
            status = check_adc_scopes()

        self.assertFalse(status.ok)
        self.assertIsNotNone(status.error)

    def test_requests_scopes_via_application_default_print_access_token(self) -> None:
        """The actual regression: must call `gcloud auth
        application-default print-access-token --scopes=...` (matching what
        TelemetryProvider._access_token actually requests) - not a bare
        unscoped call, and not `gcloud auth print-access-token
        --account=...` (--account isn't valid here at all)."""
        with patch(
            "gtm_telemetry_wizard.auth._adc_identity_label", return_value="a@example.com"
        ), patch("subprocess.run", return_value=_completed(0, "tok\n")) as mock_run:
            check_adc_scopes(required=("https://x/analytics",))

        cmd = mock_run.call_args.args[0]
        self.assertEqual(cmd[:4], ["gcloud", "auth", "application-default", "print-access-token"])
        self.assertIn("--scopes=https://x/analytics", cmd)


class EnsureAdcScopesTests(unittest.TestCase):
    def test_does_not_run_login_when_already_the_right_identity_and_ok(self) -> None:
        ok_status = AccountScopeStatus("a@example.com", granted_scopes=frozenset(ALL_SCOPES))
        with patch(
            "gtm_telemetry_wizard.auth.check_adc_scopes", return_value=ok_status
        ), patch("subprocess.run") as mock_run:
            result = ensure_adc_scopes("a@example.com")

        mock_run.assert_not_called()
        self.assertTrue(result.ok)

    def test_runs_login_when_scopes_missing(self) -> None:
        missing_status = AccountScopeStatus("a@example.com", missing=("https://x/analytics",))
        ok_status = AccountScopeStatus("a@example.com", granted_scopes=frozenset(ALL_SCOPES))
        with patch(
            "gtm_telemetry_wizard.auth.check_adc_scopes",
            side_effect=[missing_status, ok_status],
        ), patch("subprocess.run") as mock_run:
            result = ensure_adc_scopes("a@example.com", required=("https://x/analytics",))

        mock_run.assert_called_once()
        login_cmd = mock_run.call_args.args[0]
        self.assertEqual(login_cmd[:4], ["gcloud", "auth", "application-default", "login"])
        self.assertIn("a@example.com", login_cmd)
        self.assertTrue(any(arg.startswith("--scopes=") for arg in login_cmd))
        self.assertTrue(result.ok)

    def test_runs_login_when_current_identity_does_not_match_requested_account(self) -> None:
        """Even if the current ADC has all scopes, a different account being
        active must still trigger a re-login - scopes-ok-for-someone-else
        is not the same as scopes-ok-for-the-account-you-asked-for."""
        wrong_identity_ok = AccountScopeStatus(
            "someone-else@example.com", granted_scopes=frozenset(ALL_SCOPES)
        )
        right_identity_ok = AccountScopeStatus(
            "a@example.com", granted_scopes=frozenset(ALL_SCOPES)
        )
        with patch(
            "gtm_telemetry_wizard.auth.check_adc_scopes",
            side_effect=[wrong_identity_ok, right_identity_ok],
        ), patch("subprocess.run") as mock_run:
            result = ensure_adc_scopes("a@example.com")

        mock_run.assert_called_once()
        self.assertEqual(result.account, "a@example.com")


class AuthCliTests(unittest.TestCase):
    def test_auth_scopes_prints_canonical_list(self) -> None:
        runner = CliRunner()
        result = runner.invoke(app, ["auth", "scopes"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("analytics.readonly", result.output)

    def test_auth_status_reports_missing_scopes(self) -> None:
        runner = CliRunner()
        status = AccountScopeStatus("a@example.com", missing=("https://x/analytics",))
        with patch("gtm_telemetry_wizard.cli.check_adc_scopes", return_value=status):
            result = runner.invoke(app, ["auth", "status"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("a@example.com", result.output)
        self.assertIn("Missing scopes", result.output)

    def test_auth_login_reports_success(self) -> None:
        runner = CliRunner()
        ok_status = AccountScopeStatus("a@example.com", granted_scopes=frozenset(ALL_SCOPES))
        with patch("gtm_telemetry_wizard.cli.ensure_adc_scopes", return_value=ok_status) as mock_ensure:
            result = runner.invoke(app, ["auth", "login", "a@example.com"])

        self.assertEqual(result.exit_code, 0)
        mock_ensure.assert_called_once_with("a@example.com", force=False)
        self.assertIn("all required scopes", result.output)


class AccountsDiscoverCliTests(unittest.TestCase):
    def test_discover_reports_no_access_when_current_identity_lacks_scopes(self) -> None:
        from gtm_telemetry_wizard.service import ProvisioningError

        runner = CliRunner()
        bad_status = AccountScopeStatus("a@example.com", missing=("https://x/analytics",))
        with patch(
            "gtm_telemetry_wizard.cli.check_adc_scopes", return_value=bad_status
        ), patch(
            "gtm_telemetry_wizard.cli.TelemetryProvider._access_token",
            side_effect=ProvisioningError("No usable credentials.", "Run `gtw auth login`."),
        ):
            result = runner.invoke(app, ["accounts", "discover", "--measurement-id", "G-TEST"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("No access", result.output)

    def test_discover_lists_matching_property_for_current_identity(self) -> None:
        from gtm_telemetry_wizard.service import DiscoveredProperty

        runner = CliRunner()
        ok_status = AccountScopeStatus("a@example.com", granted_scopes=frozenset(ALL_SCOPES))
        match = DiscoveredProperty(
            account_name="accounts/1",
            account_display_name="My GA4 Account",
            property_id="123456",
            property_display_name="my-site",
            measurement_id="G-TEST",
            web_stream_default_uri="https://my-site.example",
        )
        with patch(
            "gtm_telemetry_wizard.cli.check_adc_scopes", return_value=ok_status
        ), patch(
            "gtm_telemetry_wizard.cli.TelemetryProvider._access_token", return_value="token"
        ), patch(
            "gtm_telemetry_wizard.cli.find_ga4_properties", return_value=[match]
        ):
            result = runner.invoke(app, ["accounts", "discover", "--measurement-id", "G-TEST"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("123456", result.output)
        self.assertIn("a@example.com", result.output)

    def test_discover_service_account_path_reports_no_access(self) -> None:
        from gtm_telemetry_wizard.service import ProvisioningError

        runner = CliRunner()
        with patch(
            "gtm_telemetry_wizard.cli.TelemetryProvider._access_token",
            side_effect=ProvisioningError("No usable gcloud credentials.", "Fix it."),
        ):
            result = runner.invoke(
                app,
                [
                    "accounts",
                    "discover",
                    "--measurement-id",
                    "G-TEST",
                    "--service-account",
                    "svc@project.iam.gserviceaccount.com",
                ],
            )

        self.assertEqual(result.exit_code, 0)
        self.assertIn("No access", result.output)


if __name__ == "__main__":
    unittest.main()
