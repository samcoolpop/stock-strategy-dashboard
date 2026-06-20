from __future__ import annotations

import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from src.jobs import fetch_close_scan_candidates


class JobsTest(unittest.TestCase):
    def test_close_scan_uses_tushare_when_token_exists(self) -> None:
        settings = SimpleNamespace(tushare_token="token")
        with patch("src.jobs.TushareClient") as tushare_client, patch("src.jobs.AkShareClient") as akshare_client:
            tushare_client.return_value.fetch_momentum_candidates.return_value = ["candidate"]
            candidates, source, errors = fetch_close_scan_candidates(settings, date(2026, 6, 18))

        self.assertEqual(candidates, ["candidate"])
        self.assertEqual(source, "tushare")
        self.assertEqual(errors, [])
        akshare_client.assert_not_called()

    def test_close_scan_falls_back_to_akshare_when_tushare_fails(self) -> None:
        settings = SimpleNamespace(tushare_token="token")
        with patch("src.jobs.TushareClient") as tushare_client, patch("src.jobs.AkShareClient") as akshare_client:
            tushare_client.return_value.fetch_momentum_candidates.side_effect = RuntimeError("bad token")
            akshare_client.return_value.fetch_momentum_candidates.return_value = ["fallback"]
            candidates, source, errors = fetch_close_scan_candidates(settings, date(2026, 6, 18))

        self.assertEqual(candidates, ["fallback"])
        self.assertEqual(source, "akshare")
        self.assertEqual(len(errors), 1)
        self.assertIn("Tushare 失败", errors[0])


if __name__ == "__main__":
    unittest.main()
