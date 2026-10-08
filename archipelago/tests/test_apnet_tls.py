import asyncio
import ssl
import sys
import types
import unittest
from unittest import mock

from archipelago.client import apnet


def fake_websockets(connect):
    """Stand-in for websockets.asyncio.client so no network is used."""
    package = types.ModuleType("websockets")
    asyncio_module = types.ModuleType("websockets.asyncio")
    client = types.ModuleType("websockets.asyncio.client")
    client.connect = connect
    return mock.patch.dict(sys.modules, {"websockets": package, "websockets.asyncio": asyncio_module,
                                         "websockets.asyncio.client": client})


class UrlTests(unittest.TestCase):
    def test_public_server_tries_tls_first(self):
        self.assertEqual(apnet._urls("archipelago.gg:51938"), ["wss://archipelago.gg:51938", "ws://archipelago.gg:51938"])

    def test_other_hosts_try_plain_first(self):
        self.assertEqual(apnet._urls("localhost:38281"), ["ws://localhost:38281", "wss://localhost:38281"])
        self.assertEqual(apnet._urls("192.168.1.5"), ["ws://192.168.1.5:38281", "wss://192.168.1.5:38281"])

    def test_explicit_scheme_is_kept(self):
        self.assertEqual(apnet._urls("ws://example.org:1"), ["ws://example.org:1"])


class TlsFallbackTests(unittest.TestCase):
    def run_connect(self, url, connect):
        with fake_websockets(connect):
            return asyncio.run(apnet._connect(url))

    def test_bundled_roots_are_used_when_the_system_store_rejects_the_server(self):
        seen = []

        async def connect(url, **options):
            seen.append(options.get("ssl"))
            if len(seen) == 1:
                raise ssl.SSLCertVerificationError(1, "certificate verify failed: certificate has expired")
            return "connection"

        self.assertEqual(self.run_connect("wss://archipelago.gg:1", connect), "connection")
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(c.verify_mode == ssl.CERT_REQUIRED and c.check_hostname for c in seen))

    def test_a_server_rejected_by_both_still_fails(self):
        async def connect(url, **options):
            raise ssl.SSLCertVerificationError(1, "certificate verify failed: certificate has expired")

        with self.assertRaises(ssl.SSLCertVerificationError):
            self.run_connect("wss://archipelago.gg:1", connect)

    def test_other_errors_are_not_retried(self):
        calls = []

        async def connect(url, **options):
            calls.append(url)
            raise ConnectionRefusedError()

        with self.assertRaises(ConnectionRefusedError):
            self.run_connect("wss://archipelago.gg:1", connect)
        self.assertEqual(len(calls), 1)

    def test_plain_connections_use_no_tls_settings(self):
        seen = {}

        async def connect(url, **options):
            seen.update(options)
            return "connection"

        self.assertEqual(self.run_connect("ws://localhost:1", connect), "connection")
        self.assertNotIn("ssl", seen)


if __name__ == "__main__":
    unittest.main()
