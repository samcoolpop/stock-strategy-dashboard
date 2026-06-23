from __future__ import annotations

import unittest
import json
from datetime import date
from unittest.mock import patch

from src.tushare_client import TushareClient


class TushareClientTest(unittest.TestCase):
    def test_recent_trade_dates_are_sorted_before_limit(self) -> None:
        rows = [
            {"cal_date": "20260618", "is_open": 1},
            {"cal_date": "20260617", "is_open": 1},
            {"cal_date": "20260616", "is_open": 1},
            {"cal_date": "20260615", "is_open": 1},
            {"cal_date": "20260614", "is_open": 0},
            {"cal_date": "20260612", "is_open": 1},
        ]
        client = TushareClient("token")
        with patch("src.tushare_client.TushareClient._call", return_value=rows):
            self.assertEqual(
                client._recent_trade_dates(date(2026, 6, 18), 4),
                ["20260615", "20260616", "20260617", "20260618"],
            )

    def test_rate_limit_waits_between_calls(self) -> None:
        client = TushareClient("token", min_call_interval=65)
        client._last_call_at = 100
        with patch("src.tushare_client.time.monotonic", return_value=120), patch(
            "src.tushare_client.time.sleep"
        ) as sleep:
            client._wait_for_rate_limit()

        sleep.assert_called_once_with(45)

    def test_call_uses_cache_before_network(self) -> None:
        cached = json.dumps([{"cal_date": "20260623", "is_open": 1}])
        client = TushareClient("token", cache_get=lambda _key: cached)

        with patch("src.tushare_client.requests.post") as post:
            rows = client._call("trade_cal", {"exchange": "SSE"}, "cal_date,is_open")

        self.assertEqual(rows, [{"cal_date": "20260623", "is_open": 1}])
        post.assert_not_called()

    def test_call_writes_successful_response_to_cache(self) -> None:
        writes: dict[str, str] = {}

        class Response:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {
                    "code": 0,
                    "data": {
                        "fields": ["cal_date", "is_open"],
                        "items": [["20260623", 1]],
                    },
                }

        client = TushareClient("token", cache_get=lambda _key: None, cache_set=writes.__setitem__)
        with patch("src.tushare_client.requests.post", return_value=Response()):
            rows = client._call("trade_cal", {"exchange": "SSE"}, "cal_date,is_open")

        self.assertEqual(rows, [{"cal_date": "20260623", "is_open": 1}])
        self.assertEqual(len(writes), 1)


if __name__ == "__main__":
    unittest.main()
