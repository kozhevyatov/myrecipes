"""Adaptive timing is deterministic, bounded and independent for each source host."""
from __future__ import annotations

import contextlib
import io
import unittest
import urllib.error
from unittest.mock import patch

import collect_recipes as collector
from app import importer
from request_pacing import AdaptivePacer, retry_after_seconds


class Clock:
    def __init__(self):
        self.now = 100.0
        self.pauses = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.pauses.append(seconds)
        self.now += seconds


class PacingTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.pacer = AdaptivePacer(2, 0.25, 10, clock=self.clock, sleep=self.clock.sleep)

    def successful_request(self, host="food.ru", latency=0.1, floor=0):
        started = self.pacer.start(host, floor)
        self.clock.now += latency
        return self.pacer.success(host, started)

    def test_fast_successes_gradually_reduce_pause_without_crossing_minimum(self):
        self.successful_request()
        self.successful_request()
        self.assertEqual(self.pacer.state("food.ru").delay, 2)
        self.successful_request()
        self.assertEqual(self.pacer.state("food.ru").delay, 1.5)
        for _ in range(60):
            self.successful_request()
        self.assertEqual(self.pacer.state("food.ru").delay, 0.25)

    def test_slow_responses_raise_pause_using_smoothed_latency(self):
        self.successful_request(latency=4)
        self.assertEqual(self.pacer.state("food.ru").delay, 6)
        self.successful_request(latency=0)
        self.assertEqual(self.pacer.state("food.ru").latency, 3)
        self.assertEqual(self.pacer.state("food.ru").delay, 6)

    def test_hosts_have_separate_timing_and_first_request_has_no_artificial_wait(self):
        self.successful_request("food.ru")
        self.pacer.start("cdn.food.ru")
        self.assertEqual(self.clock.pauses[-1], 0)
        self.pacer.failure("food.ru")
        self.assertEqual(self.pacer.state("food.ru").delay, 4)
        self.assertEqual(self.pacer.state("cdn.food.ru").delay, 2)

    def test_failures_slow_down_reset_success_streak_and_respect_maximum(self):
        self.successful_request()
        for _ in range(10):
            self.pacer.failure("food.ru")
        state = self.pacer.state("food.ru")
        self.assertEqual((state.delay, state.successes, state.errors), (10, 0, 10))

    def test_robots_floor_can_exceed_configured_maximum(self):
        self.successful_request(floor=20)
        self.pacer.start("food.ru", floor=20)
        self.assertAlmostEqual(self.clock.pauses[-1], 19.9)
        self.assertEqual(self.pacer.state("food.ru").delay, 2)

    def test_retry_after_wait_starts_at_response_and_summary_records_changes(self):
        self.successful_request()
        self.pacer.failure("food.ru", retry_after=7)
        self.pacer.start("food.ru")
        self.assertEqual(self.clock.pauses[-1], 7)
        self.assertEqual(self.pacer.summary()["food.ru"]["requests"], 2)
        self.assertEqual(self.pacer.summary()["food.ru"]["errors"], 1)

    def test_retry_after_supports_seconds_dates_and_rejects_bad_values(self):
        self.assertEqual(retry_after_seconds("5", now=0), 5)
        self.assertEqual(retry_after_seconds("Thu, 01 Jan 1970 00:00:10 GMT", now=3), 7)
        self.assertEqual(retry_after_seconds("Thu, 01 Jan 1970 00:00:01 GMT", now=3), 0)
        for value in (None, "", "tomorrow", "-5"):
            self.assertIsNone(retry_after_seconds(value, now=0))


class AdaptiveClientTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.client = collector.Client(2, 2, adaptive_delay=True)
        self.client.pacer = AdaptivePacer(2, 0.25, 10, clock=self.clock, sleep=self.clock.sleep)

    @staticmethod
    def http_error(status, retry_after=None):
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        try:
            raise urllib.error.HTTPError("https://food.ru/recipe", status, "Synthetic response", headers, None)
        except urllib.error.HTTPError as exc:
            exc.close()
            try:
                raise importer.ImportError_(f"HTTP {status}")
            except importer.ImportError_ as wrapped:
                return wrapped

    def request(self):
        return self.client.request("https://food.ru/recipe", 100, "text/html")

    def test_rate_limit_honors_retry_after_and_recovers_with_bounded_retry(self):
        with patch.object(importer, "fetch", side_effect=[self.http_error(429, "7"), (b"Page", "text/html", "https://food.ru/recipe")]) as fetch, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.request()[0], b"Page")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(self.clock.pauses, [0, 7])
        self.assertNotIn("food.ru", self.client.blocked)

    def test_long_retry_after_stops_host_without_retrying_early(self):
        with patch.object(importer, "fetch", side_effect=self.http_error(429, "120")) as fetch, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(collector.CollectionError, "longer than 60 seconds"):
                self.request()
        self.assertEqual(fetch.call_count, 1)
        self.assertIn("food.ru", self.client.blocked)

    def test_rate_limit_exhaustion_blocks_host_after_configured_attempts(self):
        with patch.object(importer, "fetch", side_effect=self.http_error(429)) as fetch, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(collector.CollectionError):
                self.request()
            with self.assertRaisesRegex(collector.CollectionError, "stopped"):
                self.request()
        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(self.client.pacing_summary()["food.ru"]["errors"], 3)

    def test_server_failures_slow_down_and_authentication_failure_is_never_retried(self):
        with patch.object(importer, "fetch", side_effect=[self.http_error(503), (b"Page", "text/html", "https://food.ru/recipe")]), \
                contextlib.redirect_stderr(io.StringIO()):
            self.request()
        self.assertEqual(self.client.pacer.state("food.ru").delay, 4)
        with patch.object(importer, "fetch", side_effect=self.http_error(403)) as fetch:
            with self.assertRaises(collector.CollectionError):
                self.request()
        self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
