from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


MIN_TURNOVER_AMOUNT = Decimal("500000000")
MAX_VOLUME_RATIO = Decimal("0.7")


@dataclass(frozen=True)
class StockCandidate:
    code: str
    name: str
    market: str | None = None
    is_st: bool = False
    is_star: bool = False
    is_chinext: bool = False
    is_one_word_board: bool = False

    @property
    def eligible_for_pool(self) -> bool:
        return not self.is_st and not self.is_star

    def to_record(self) -> dict[str, object]:
        return {
            "code": self.code,
            "name": self.name,
            "market": self.market,
            "is_st": self.is_st,
            "is_star": self.is_star,
            "is_chinext": self.is_chinext,
        }


@dataclass(frozen=True)
class MonitorSnapshot:
    code: str
    name: str
    volume_ratio: Decimal | None
    turnover_amount: Decimal | None
    is_limit_up: bool = False
    is_one_word_board: bool = False
    raw_json: str | None = None


@dataclass(frozen=True)
class StrategyDecision:
    volume_ratio_ok: bool
    turnover_amount_ok: bool
    fund_flow_3d: Decimal
    fund_flow_ok: bool
    final_status: str

    @property
    def passed(self) -> bool:
        return self.final_status == "passed"


def evaluate_snapshot(
    volume_ratio: Decimal | None,
    turnover_amount: Decimal | None,
    fund_flow_3d: Decimal,
) -> StrategyDecision:
    volume_ratio_ok = volume_ratio is not None and volume_ratio <= MAX_VOLUME_RATIO
    turnover_amount_ok = turnover_amount is not None and turnover_amount >= MIN_TURNOVER_AMOUNT
    fund_flow_ok = fund_flow_3d > 0
    final_status = "passed" if volume_ratio_ok and turnover_amount_ok and fund_flow_ok else "watching"
    return StrategyDecision(
        volume_ratio_ok=volume_ratio_ok,
        turnover_amount_ok=turnover_amount_ok,
        fund_flow_3d=fund_flow_3d,
        fund_flow_ok=fund_flow_ok,
        final_status=final_status,
    )


def infer_market(code: str, explicit_market: str | None = None) -> str:
    if explicit_market:
        return explicit_market
    if code.startswith("688"):
        return "科创板"
    if code.startswith("300") or code.startswith("301"):
        return "创业板"
    if code.startswith("60"):
        return "沪市主板"
    if code.startswith("00"):
        return "深市主板"
    if code.startswith("8") or code.startswith("4"):
        return "北交所"
    return "未知"


def is_star_market(code: str, market: str | None) -> bool:
    return code.startswith("688") or ("科创" in (market or ""))


def is_chinext_market(code: str, market: str | None) -> bool:
    return code.startswith(("300", "301")) or ("创业" in (market or ""))

