"""Choose a verified CA store for the collector without changing global TLS settings."""
from __future__ import annotations

import os
import ssl
from pathlib import Path

SYSTEM_CA_BUNDLES = (
    Path("/etc/ssl/cert.pem"),
    Path("/etc/ssl/certs/ca-certificates.crt"),
    Path("/etc/pki/tls/certs/ca-bundle.crt"),
)


class TLSConfigurationError(ValueError):
    """Trusted CA certificates could not be configured for this run."""


def configure_tls(ca_bundle: Path | None = None) -> tuple[ssl.SSLContext, str]:
    """Keep configured trust; use a public system bundle when Python has no default store."""
    try:
        if ca_bundle is not None:
            context = ssl.create_default_context(cafile=str(ca_bundle))
            return context, "TLS: using the CA bundle specified by --ca-bundle."
        # Explicit environment configuration always takes precedence over discovery.
        configured = any(name in os.environ for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"))
        for name in ("SSL_CERT_FILE", "SSL_CERT_DIR"):
            if name in os.environ and not os.environ[name].strip():
                raise TLSConfigurationError(f"{name} is empty; unset it or specify a valid CA path")
        if "SSL_CERT_FILE" in os.environ and not Path(os.environ["SSL_CERT_FILE"]).is_file():
            raise TLSConfigurationError("SSL_CERT_FILE does not point to a CA bundle file")
        if "SSL_CERT_DIR" in os.environ and not Path(os.environ["SSL_CERT_DIR"]).is_dir():
            raise TLSConfigurationError("SSL_CERT_DIR does not point to a CA certificate directory")
        context = ssl.create_default_context()
        if configured:
            return context, "TLS: using the certificate trust configured in SSL_CERT_FILE/SSL_CERT_DIR."
        paths = ssl.get_default_verify_paths()
        if context.cert_store_stats()["x509_ca"] or paths.cafile or paths.capath:
            return context, "TLS: using Python's default trusted CA store."
        for bundle in SYSTEM_CA_BUNDLES:
            if bundle.is_file():
                context.load_verify_locations(cafile=str(bundle))
                if not context.cert_store_stats()["x509_ca"]:
                    raise TLSConfigurationError("The system CA bundle contains no trusted CA certificates")
                return context, f"TLS: Python has no default CA store; using system CA bundle {bundle}."
    except (OSError, ssl.SSLError) as exc:
        raise TLSConfigurationError(
            "Cannot load trusted CA certificates; check --ca-bundle, SSL_CERT_FILE and SSL_CERT_DIR"
        ) from exc
    raise TLSConfigurationError(
        "Python has no trusted CA store and no system CA bundle was found. "
        "Supply a trusted PEM bundle with --ca-bundle or SSL_CERT_FILE."
    )
