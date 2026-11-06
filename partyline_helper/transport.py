"""Actionable TLS failures without exposing device credentials."""
import ssl
from urllib.parse import urlsplit


class CertificateError(RuntimeError):
    """Certificate verification requires an operator fix, not reconnect backoff."""


def certificate_failure(error, server):
    seen = set()
    while isinstance(error, BaseException) and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, ssl.SSLCertVerificationError):
            origin = server if "://" in server else "https://" + server
            host = urlsplit(origin).hostname
            reason = getattr(error, "verify_message", None) or str(error)
            return f"TLS certificate verification failed for {host}: {reason}. Fix the certificate and retry."
        error = getattr(error, "reason", None) or error.__cause__ or error.__context__
    return None
