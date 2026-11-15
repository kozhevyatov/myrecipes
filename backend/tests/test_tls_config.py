"""Collector CA discovery preserves configured trust and certificate verification."""
from __future__ import annotations

import os
import ssl
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import tls_config
from tls_config import TLSConfigurationError, configure_tls


class TLSConfigurationTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    @staticmethod
    def context(count=0):
        context = Mock(spec=ssl.SSLContext)
        context.cert_store_stats.return_value = {"x509_ca": count}
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        return context

    def test_working_default_store_is_kept_without_system_discovery(self):
        context = self.context(128)
        with patch.object(tls_config.ssl, "create_default_context", return_value=context) as create, \
                patch.object(tls_config.ssl, "get_default_verify_paths", return_value=SimpleNamespace(cafile=None, capath=None)):
            configured, message = configure_tls()
        self.assertIs(configured, context)
        self.assertIn("default trusted CA store", message)
        create.assert_called_once_with()
        context.load_verify_locations.assert_not_called()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_lazy_default_capath_or_cafile_is_preserved_when_store_count_is_zero(self):
        for paths in (SimpleNamespace(cafile=None, capath="/system/public-certs"),
                      SimpleNamespace(cafile="/system/public-ca.pem", capath=None)):
            with self.subTest(paths=paths):
                context = self.context()
                with patch.object(tls_config.ssl, "create_default_context", return_value=context), \
                        patch.object(tls_config.ssl, "get_default_verify_paths", return_value=paths):
                    configured, message = configure_tls()
                self.assertIs(configured, context)
                self.assertIn("default trusted CA store", message)
                context.load_verify_locations.assert_not_called()

    def test_explicit_environment_file_or_directory_prevents_system_discovery(self):
        bundle = self.root / "trusted.pem"
        bundle.write_text("Synthetic test CA placeholder", encoding="utf-8")
        for name, value in (("SSL_CERT_FILE", str(bundle)), ("SSL_CERT_DIR", str(self.root))):
            with self.subTest(name=name), patch.dict(os.environ, {name: value}, clear=True):
                context = self.context()
                with patch.object(tls_config.ssl, "create_default_context", return_value=context), \
                        patch.object(tls_config.ssl, "get_default_verify_paths") as paths:
                    configured, message = configure_tls()
                self.assertIs(configured, context)
                self.assertIn("SSL_CERT_FILE/SSL_CERT_DIR", message)
                self.assertEqual(os.environ[name], value)
                context.load_verify_locations.assert_not_called()
                paths.assert_not_called()

    def test_invalid_environment_paths_fail_before_attempting_default_or_system_trust(self):
        for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
            with self.subTest(name=name), patch.dict(os.environ, {name: str(self.root / "missing")}, clear=True):
                with patch.object(tls_config.ssl, "create_default_context") as create:
                    with self.assertRaisesRegex(TLSConfigurationError, name):
                        configure_tls()
                create.assert_not_called()

    def test_empty_environment_paths_fail_before_trust_discovery(self):
        for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
            for value in ("", " ", "\t\n"):
                with self.subTest(name=name, value=value), patch.dict(os.environ, {name: value}, clear=True):
                    with patch.object(tls_config.ssl, "create_default_context") as create, \
                            patch.object(tls_config.ssl, "get_default_verify_paths") as paths:
                        with self.assertRaisesRegex(TLSConfigurationError, name):
                            configure_tls()
                    create.assert_not_called()
                    paths.assert_not_called()

    def test_explicit_bundle_takes_priority_over_environment_configuration(self):
        bundle = self.root / "selected.pem"
        context = self.context(128)
        with patch.dict(os.environ, {"SSL_CERT_FILE": str(self.root / "missing")}, clear=True), \
                patch.object(tls_config.ssl, "create_default_context", return_value=context) as create:
            configured, message = configure_tls(bundle)
        self.assertIs(configured, context)
        self.assertIn("--ca-bundle", message)
        create.assert_called_once_with(cafile=str(bundle))

    def test_missing_default_store_loads_first_existing_system_bundle_and_reports_it(self):
        bundle = self.root / "system-ca.pem"
        bundle.touch()
        unused = self.root / "unused.pem"
        unused.touch()
        context = self.context()
        context.cert_store_stats.side_effect = [{"x509_ca": 0}, {"x509_ca": 128}]
        with patch.object(tls_config.ssl, "create_default_context", return_value=context), \
                patch.object(tls_config.ssl, "get_default_verify_paths", return_value=SimpleNamespace(cafile=None, capath=None)), \
                patch.object(tls_config, "SYSTEM_CA_BUNDLES", (self.root / "missing", bundle, unused)):
            configured, message = configure_tls()
        self.assertIs(configured, context)
        self.assertIn("Python has no default CA store", message)
        self.assertIn(str(bundle), message)
        context.load_verify_locations.assert_called_once_with(cafile=str(bundle))
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_no_system_bundle_fails_with_explicit_configuration_guidance(self):
        context = self.context()
        with patch.object(tls_config.ssl, "create_default_context", return_value=context), \
                patch.object(tls_config.ssl, "get_default_verify_paths", return_value=SimpleNamespace(cafile=None, capath=None)), \
                patch.object(tls_config, "SYSTEM_CA_BUNDLES", (self.root / "missing",)):
            with self.assertRaisesRegex(TLSConfigurationError, "--ca-bundle or SSL_CERT_FILE"):
                configure_tls()
        context.load_verify_locations.assert_not_called()

    def test_broken_system_bundle_fails_without_silently_trying_another_bundle(self):
        bundle = self.root / "broken-system.pem"
        bundle.touch()
        context = self.context()
        context.load_verify_locations.side_effect = ssl.SSLError("Synthetic malformed CA error")
        with patch.object(tls_config.ssl, "create_default_context", return_value=context), \
                patch.object(tls_config.ssl, "get_default_verify_paths", return_value=SimpleNamespace(cafile=None, capath=None)), \
                patch.object(tls_config, "SYSTEM_CA_BUNDLES", (bundle, self.root / "another.pem")):
            with self.assertRaisesRegex(TLSConfigurationError, "Cannot load trusted CA certificates"):
                configure_tls()
        context.load_verify_locations.assert_called_once_with(cafile=str(bundle))

    def test_system_bundle_with_no_ca_certificates_is_rejected(self):
        bundle = self.root / "empty-system.pem"
        bundle.touch()
        context = self.context()
        with patch.object(tls_config.ssl, "create_default_context", return_value=context), \
                patch.object(tls_config.ssl, "get_default_verify_paths", return_value=SimpleNamespace(cafile=None, capath=None)), \
                patch.object(tls_config, "SYSTEM_CA_BUNDLES", (bundle,)):
            with self.assertRaisesRegex(TLSConfigurationError, "contains no trusted CA"):
                configure_tls()

    def test_actual_malformed_or_missing_explicit_bundle_fails_actionably(self):
        malformed = self.root / "malformed.pem"
        malformed.write_text("Not a PEM certificate", encoding="utf-8")
        for bundle in (malformed, self.root / "missing.pem"):
            with self.subTest(bundle=bundle), self.assertRaisesRegex(TLSConfigurationError, "--ca-bundle"):
                configure_tls(bundle)

    def test_malformed_configured_trust_does_not_trigger_system_discovery(self):
        bundle = self.root / "configured.pem"
        bundle.write_text("Synthetic test CA placeholder", encoding="utf-8")
        with patch.dict(os.environ, {"SSL_CERT_FILE": str(bundle)}, clear=True), \
                patch.object(tls_config.ssl, "create_default_context", side_effect=ssl.SSLError("Synthetic malformed CA error")), \
                patch.object(tls_config.ssl, "get_default_verify_paths") as paths:
            with self.assertRaisesRegex(TLSConfigurationError, "Cannot load trusted CA certificates"):
                configure_tls()
        paths.assert_not_called()


if __name__ == "__main__":
    unittest.main()
