from __future__ import annotations

import unittest
from datetime import datetime

from src.dates import close_scan_default_date


class DatesTest(unittest.TestCase):
    def test_close_scan_before_open_uses_previous_business_day(self) -> None:
        self.assertEqual(
            close_scan_default_date(datetime(2026, 6, 24, 0, 45)),
            datetime(2026, 6, 23).date(),
        )

    def test_close_scan_after_close_uses_same_day(self) -> None:
        self.assertEqual(
            close_scan_default_date(datetime(2026, 6, 23, 16, 0)),
            datetime(2026, 6, 23).date(),
        )

    def test_close_scan_weekend_uses_previous_friday(self) -> None:
        self.assertEqual(
            close_scan_default_date(datetime(2026, 6, 27, 12, 0)),
            datetime(2026, 6, 26).date(),
        )


if __name__ == "__main__":
    unittest.main()
