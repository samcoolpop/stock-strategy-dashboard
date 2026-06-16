from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.db import Database, Repository


class DatabaseTest(unittest.TestCase):
    def test_database_init_and_candidate_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Repository(Database(Path(temp_dir) / "test.sqlite3"))
            repo.init()
            stock = {
                "code": "300001",
                "name": "测试股份",
                "market": "创业板",
                "is_st": False,
                "is_star": False,
                "is_chinext": True,
            }
            self.assertTrue(repo.add_candidate(stock, "2026-06-02", "2026-06-16"))
            self.assertFalse(repo.add_candidate(stock, "2026-06-02", "2026-06-16"))
            self.assertEqual(len(repo.active_candidates("2026-06-03")), 1)

    def test_expire_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Repository(Database(Path(temp_dir) / "test.sqlite3"))
            repo.init()
            stock = {
                "code": "000001",
                "name": "测试股份",
                "market": "深市主板",
                "is_st": False,
                "is_star": False,
                "is_chinext": False,
            }
            repo.add_candidate(stock, "2026-06-01", "2026-06-10")
            self.assertEqual(repo.expire_candidates("2026-06-11"), 1)
            self.assertEqual(len(repo.active_candidates("2026-06-11")), 0)

    def test_reentering_candidate_replaces_previous_active_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = Repository(Database(Path(temp_dir) / "test.sqlite3"))
            repo.init()
            stock = {
                "code": "000001",
                "name": "测试股份",
                "market": "深市主板",
                "is_st": False,
                "is_star": False,
                "is_chinext": False,
            }
            self.assertTrue(repo.add_candidate(stock, "2026-06-01", "2026-06-15"))
            self.assertTrue(repo.add_candidate(stock, "2026-06-03", "2026-06-17"))
            active = repo.active_candidates("2026-06-04")
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0]["pool_date"], "2026-06-03")


if __name__ == "__main__":
    unittest.main()
