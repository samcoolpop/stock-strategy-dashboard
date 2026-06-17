from __future__ import annotations

import unittest
from decimal import Decimal

from src.strategy import StockCandidate, evaluate_snapshot


class StrategyTest(unittest.TestCase):
    def test_turnover_threshold_is_inclusive_and_volume_ratio_is_strict(self) -> None:
        decision = evaluate_snapshot(Decimal("0.79"), Decimal("500000000"), Decimal("1"))
        self.assertTrue(decision.volume_ratio_ok)
        self.assertTrue(decision.turnover_amount_ok)
        self.assertTrue(decision.fund_flow_ok)
        self.assertTrue(decision.passed)

        boundary = evaluate_snapshot(Decimal("0.8"), Decimal("500000000"), Decimal("1"))
        self.assertFalse(boundary.volume_ratio_ok)
        self.assertFalse(boundary.passed)

    def test_fund_flow_must_be_positive(self) -> None:
        decision = evaluate_snapshot(Decimal("0.6"), Decimal("600000000"), Decimal("0"))
        self.assertFalse(decision.fund_flow_ok)
        self.assertEqual(decision.final_status, "watching")

    def test_missing_fund_flow_stays_missing(self) -> None:
        decision = evaluate_snapshot(Decimal("0.6"), Decimal("600000000"), None)
        self.assertFalse(decision.fund_flow_ok)
        self.assertIsNone(decision.fund_flow_3d)
        self.assertEqual(decision.final_status, "watching")

    def test_pool_filters_st_and_star_market_but_keeps_chinext(self) -> None:
        self.assertFalse(StockCandidate(code="600001", name="ST测试", is_st=True).eligible_for_pool)
        self.assertFalse(StockCandidate(code="688001", name="科创测试", is_star=True).eligible_for_pool)
        self.assertFalse(StockCandidate(code="830001", name="北交测试", market="北交所").eligible_for_pool)
        self.assertTrue(StockCandidate(code="300001", name="创业测试", is_chinext=True).eligible_for_pool)


if __name__ == "__main__":
    unittest.main()
