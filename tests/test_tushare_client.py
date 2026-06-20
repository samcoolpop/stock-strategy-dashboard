from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()
