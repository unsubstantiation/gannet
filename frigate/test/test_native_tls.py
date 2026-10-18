# SPDX-License-Identifier: LicenseRef-GNCL-1.0
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from frigate.util.tls import ensure_tls_certificate, is_generated_certificate


def _write_pair(
    cert: Path, key: Path, organization: str, *, expires_in: timedelta
) -> None:
    """Write a self-signed pair with a chosen organization and lifetime."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
            x509.NameAttribute(NameOID.COMMON_NAME, "frigate.test"),
        ]
    )
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=400))
        .not_valid_after(now + expires_in)
        .sign(private_key, hashes.SHA256())
    )
    cert.parent.mkdir(parents=True, exist_ok=True)
    cert.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


class TestNativeTls(unittest.TestCase):
    def test_generates_persistent_self_signed_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "tls" / "fullchain.pem"
            key = Path(directory) / "tls" / "privkey.pem"

            cert_path, key_path = ensure_tls_certificate(str(cert), str(key))

            parsed_cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
            parsed_key = serialization.load_pem_private_key(
                Path(key_path).read_bytes(), password=None
            )
            self.assertEqual(
                parsed_cert.public_key().public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                ),
                parsed_key.public_key().public_bytes(
                    serialization.Encoding.DER,
                    serialization.PublicFormat.SubjectPublicKeyInfo,
                ),
            )

            original_cert = cert.read_bytes()
            original_key = key.read_bytes()
            ensure_tls_certificate(str(cert), str(key))
            self.assertEqual(cert.read_bytes(), original_cert)
            self.assertEqual(key.read_bytes(), original_key)

    def test_an_expired_generated_pair_is_replaced(self) -> None:
        """The generated certificate is only valid for a year.

        Once it lapsed the gateway kept serving it and every browser refused
        the connection; the only way out was deleting the files by hand.
        Frigate's own certificate is Frigate's to renew.
        """
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "fullchain.pem"
            key = Path(directory) / "privkey.pem"
            _write_pair(
                cert, key, "Frigate Native Windows", expires_in=timedelta(days=-1)
            )
            stale_cert = cert.read_bytes()
            stale_key = key.read_bytes()

            with self.assertLogs("frigate.util.tls", level="INFO") as logs:
                ensure_tls_certificate(str(cert), str(key))

            self.assertNotEqual(cert.read_bytes(), stale_cert)
            self.assertNotEqual(key.read_bytes(), stale_key)
            self.assertIn("generating a new one", "\n".join(logs.output))

            renewed = x509.load_pem_x509_certificate(cert.read_bytes())
            self.assertTrue(is_generated_certificate(renewed))
            self.assertGreater(
                renewed.not_valid_after_utc, datetime.now(UTC) + timedelta(days=300)
            )

    def test_a_generated_pair_about_to_expire_is_replaced_early(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "fullchain.pem"
            key = Path(directory) / "privkey.pem"
            _write_pair(
                cert, key, "Frigate Native Windows", expires_in=timedelta(days=10)
            )
            stale_cert = cert.read_bytes()

            ensure_tls_certificate(str(cert), str(key))

            self.assertNotEqual(cert.read_bytes(), stale_cert)

    def test_an_administrators_certificate_is_never_replaced(self) -> None:
        """Only a pair Frigate generated itself may be regenerated.

        An expired custom certificate is reported, but the files are theirs:
        overwriting them would silently swap a trusted certificate for a
        self-signed one.
        """
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "fullchain.pem"
            key = Path(directory) / "privkey.pem"
            _write_pair(cert, key, "Example Corp", expires_in=timedelta(days=-1))
            original_cert = cert.read_bytes()
            original_key = key.read_bytes()

            with self.assertLogs("frigate.util.tls", level="WARNING") as logs:
                ensure_tls_certificate(str(cert), str(key))

            self.assertEqual(cert.read_bytes(), original_cert)
            self.assertEqual(key.read_bytes(), original_key)
            self.assertIn("expired", "\n".join(logs.output))

    def test_an_unreadable_certificate_is_left_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "fullchain.pem"
            key = Path(directory) / "privkey.pem"
            cert.write_text("not a certificate", encoding="utf-8")
            key.write_text("not a key", encoding="utf-8")

            with self.assertLogs("frigate.util.tls", level="WARNING"):
                cert_path, key_path = ensure_tls_certificate(str(cert), str(key))

            self.assertEqual(Path(cert_path).resolve(), cert.resolve())
            self.assertEqual(Path(key_path).resolve(), key.resolve())
            self.assertEqual(cert.read_text(encoding="utf-8"), "not a certificate")

    def test_rejects_partial_pair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cert = Path(directory) / "fullchain.pem"
            key = Path(directory) / "privkey.pem"
            cert.write_text("certificate", encoding="utf-8")

            with self.assertRaisesRegex(FileNotFoundError, "requires both"):
                ensure_tls_certificate(str(cert), str(key))


if __name__ == "__main__":
    unittest.main()
