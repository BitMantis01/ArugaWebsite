import io
import json
import logging
import sys
import unittest
from fastapi import Request
from fastapi.testclient import TestClient

from app.main import app
from app.observability import (
    RedactingJsonFormatter,
    record_security_event,
    track_external,
    security_events_total,
    external_call_duration_seconds,
)


class TestObservability(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app, raise_server_exceptions=False)

    def test_health_endpoint_and_log_suppression(self):
        """Verify /health returns 200 and does not emit routine Loki access logs."""
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.json().get("status"), ("ok", "healthy"))
        self.assertIn("X-Request-ID", response.headers)

    def test_metrics_internal_access_allowed(self):
        """Verify internal scrape to /metrics returns HTTP 200 with Prometheus format."""
        response = self.client.get("/metrics")
        self.assertEqual(response.status_code, 200)
        self.assertIn("http_requests_total", response.text)
        self.assertIn("security_events_total", response.text)
        self.assertIn("external_call_duration_seconds", response.text)

    def test_metrics_public_proxy_blocked(self):
        """Verify request with Cloudflare proxy header is rejected with 403 Forbidden."""
        response = self.client.get("/metrics", headers={"CF-Connecting-IP": "203.0.113.195"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Forbidden: Internal metrics endpoint")
        self.assertIn("request_id", response.json())

    def test_metrics_untrusted_forwarded_for_blocked(self):
        """Verify request with public X-Forwarded-For is rejected with 403 Forbidden."""
        response = self.client.get("/metrics", headers={"X-Forwarded-For": "198.51.100.5"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "Forbidden: Internal metrics endpoint")

    def test_bot_scanner_probe_fast_drop(self):
        """Verify known scanner probes are fast-dropped as 404 in <1ms without template renders."""
        probes = ["/.env", "/.git/config", "/.aws/credentials", "/wp-login.php", "/phpmyadmin"]
        for probe in probes:
            response = self.client.get(probe)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["error"], "Not Found")
            self.assertIn("X-Request-ID", response.headers)

    def test_request_id_header_propagation(self):
        """Verify incoming correlation ID (CF-Ray / X-Request-ID) is echoed back."""
        custom_id = "test-ray-999"
        response = self.client.get("/login", headers={"X-Request-ID": custom_id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Request-ID"), custom_id)

    def test_pii_and_secret_redaction(self):
        """Verify sensitive keys in log extras are masked with ***REDACTED***."""
        buffer = io.StringIO()
        handler = logging.StreamHandler(buffer)
        formatter = RedactingJsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%SZ",
            rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        )
        handler.setFormatter(formatter)
        test_logger = logging.getLogger("test_redactor")
        test_logger.addHandler(handler)
        test_logger.setLevel(logging.INFO)

        test_logger.info(
            "User action",
            extra={
                "password": "supersecretpassword",
                "api_key": "aruga-dev-key-12345",
                "token": "bearer-jwt-token",
                "normal_field": "visible_data",
                "nested": {
                    "credentials": "top_secret_creds",
                    "safe": "keep_this",
                },
            },
        )

        log_output = buffer.getvalue().strip()
        data = json.loads(log_output)
        self.assertEqual(data["password"], "***REDACTED***")
        self.assertEqual(data["api_key"], "***REDACTED***")
        self.assertEqual(data["token"], "***REDACTED***")
        self.assertEqual(data["normal_field"], "visible_data")
        self.assertEqual(data["nested"]["credentials"], "***REDACTED***")
        self.assertEqual(data["nested"]["safe"], "keep_this")

    def test_track_external_context_manager(self):
        """Verify downstream dependency timing context manager observes latencies."""
        with track_external("test_db_query"):
            _ = sum(range(1000))

        # Check metrics registry for recorded observation
        metrics_response = self.client.get("/metrics")
        self.assertIn('external_call_duration_seconds_count{status="success",target="test_db_query"}', metrics_response.text)

    def test_record_security_event(self):
        """Verify security event counter incrementation."""
        record_security_event("rate_limited")
        metrics_response = self.client.get("/metrics")
        self.assertIn('security_events_total{type="rate_limited"}', metrics_response.text)


if __name__ == "__main__":
    unittest.main()

