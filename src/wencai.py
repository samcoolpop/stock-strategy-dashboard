from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from .config import Settings
from .parsing import parse_cny_amount, parse_decimal
from .strategy import (
    MonitorSnapshot,
    StockCandidate,
    infer_market,
    is_chinext_market,
    is_star_market,
)


class WencaiError(RuntimeError):
    pass


@dataclass(frozen=True)
class FundFlow:
    code: str
    trade_date: str
    main_net_inflow: Decimal | None
    raw_json: str | None = None


class WencaiClient:
    """Browser automation adapter for 同花顺问财.

    The page shape changes occasionally. This adapter keeps the browser-specific
    code isolated so field aliases can be adjusted without touching strategy code.
    """

    BASE_URL = "https://www.iwencai.com/unifiedwap/result?w={query}"
    TWO_LIMIT_QUERY = "今日二连板，非ST，非科创板，股票代码，股票简称，所属板块，是否一字板"
    MONITOR_QUERY = "{codes} 量比 成交额 主力资金净流入 股票简称 所属板块"
    FUND_FLOW_QUERY = "{code} 最近3个交易日主力资金净流入"

    CODE_ALIASES = ("股票代码", "代码", "code")
    NAME_ALIASES = ("股票简称", "股票名称", "简称", "名称", "name")
    MARKET_ALIASES = ("所属板块", "板块", "市场类型", "market")
    VOLUME_RATIO_ALIASES = ("量比",)
    TURNOVER_ALIASES = ("成交额", "成交金额")
    FUND_FLOW_ALIASES = ("主力资金净流入", "主力净流入", "净流入额")
    DATE_ALIASES = ("日期", "交易日期", "trade_date")
    ONE_WORD_ALIASES = ("是否一字板", "一字板")

    def __init__(self, settings: Settings):
        self.settings = settings

    def fetch_two_limit_up(self) -> list[StockCandidate]:
        rows = self._query_rows(self.TWO_LIMIT_QUERY)
        candidates = []
        for row in rows:
            code = self._clean_code(self._pick(row, self.CODE_ALIASES))
            name = str(self._pick(row, self.NAME_ALIASES) or "").strip()
            if not code or not name:
                continue
            market = infer_market(code, str(self._pick(row, self.MARKET_ALIASES) or "").strip() or None)
            is_st = "ST" in name.upper()
            candidate = StockCandidate(
                code=code,
                name=name,
                market=market,
                is_st=is_st,
                is_star=is_star_market(code, market),
                is_chinext=is_chinext_market(code, market),
                is_one_word_board=self._truthy(self._pick(row, self.ONE_WORD_ALIASES)),
            )
            if candidate.eligible_for_pool:
                candidates.append(candidate)
        return candidates

    def fetch_monitor_snapshots(self, codes: list[str]) -> list[MonitorSnapshot]:
        if not codes:
            return []
        query = self.MONITOR_QUERY.format(codes=" ".join(codes))
        rows = self._query_rows(query)
        snapshots = []
        for row in rows:
            code = self._clean_code(self._pick(row, self.CODE_ALIASES))
            if not code:
                continue
            snapshots.append(
                MonitorSnapshot(
                    code=code,
                    name=str(self._pick(row, self.NAME_ALIASES) or "").strip(),
                    volume_ratio=parse_decimal(self._pick(row, self.VOLUME_RATIO_ALIASES)),
                    turnover_amount=parse_cny_amount(self._pick(row, self.TURNOVER_ALIASES)),
                    is_limit_up=self._truthy(row.get("涨停") or row.get("是否涨停")),
                    is_one_word_board=self._truthy(self._pick(row, self.ONE_WORD_ALIASES)),
                    raw_json=json.dumps(row, ensure_ascii=False),
                )
            )
        return snapshots

    def fetch_recent_fund_flows(self, code: str, end_date: date) -> list[FundFlow]:
        rows = self._query_rows(self.FUND_FLOW_QUERY.format(code=code))
        flows = []
        fallback_dates = [(end_date - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
        for index, row in enumerate(rows[:3]):
            row_code = self._clean_code(self._pick(row, self.CODE_ALIASES)) or code
            trade_date = str(self._pick(row, self.DATE_ALIASES) or fallback_dates[min(index, 2)])
            flows.append(
                FundFlow(
                    code=row_code,
                    trade_date=trade_date[:10],
                    main_net_inflow=parse_cny_amount(self._pick(row, self.FUND_FLOW_ALIASES)),
                    raw_json=json.dumps(row, ensure_ascii=False),
                )
            )
        return flows

    def _query_rows(self, query: str) -> list[dict[str, Any]]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise WencaiError("缺少 playwright，请先安装 requirements.txt 并执行 playwright install chromium。") from exc

        url = self.BASE_URL.format(query=quote(query))
        self.settings.wencai_user_data_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.settings.wencai_user_data_dir),
                headless=self.settings.wencai_headless,
                viewport={"width": 1440, "height": 960},
            )
            page = context.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                rows = page.evaluate(_EXTRACT_TABLE_JS)
            finally:
                context.close()

        if not rows:
            raise WencaiError("问财没有返回可解析表格；可能需要手动登录、处理验证码，或调整查询语句/字段映射。")
        return rows

    @classmethod
    def _pick(cls, row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
        for alias in aliases:
            if alias in row:
                return row[alias]
        for key, value in row.items():
            if any(alias in key for alias in aliases):
                return value
        return None

    @staticmethod
    def _clean_code(value: Any) -> str:
        if value is None:
            return ""
        digits = "".join(ch for ch in str(value) if ch.isdigit())
        return digits[:6] if len(digits) >= 6 else ""

    @staticmethod
    def _truthy(value: Any) -> bool:
        text = str(value or "").strip().lower()
        return text in {"1", "true", "yes", "是", "一字板"} or "是" in text


_EXTRACT_TABLE_JS = r"""
() => {
  const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
  const tables = Array.from(document.querySelectorAll('table'));
  for (const table of tables) {
    const headerCells = Array.from(table.querySelectorAll('thead th, tr:first-child th, tr:first-child td'));
    const headers = headerCells.map((cell) => clean(cell.innerText)).filter(Boolean);
    if (headers.length < 2) continue;
    const bodyRows = Array.from(table.querySelectorAll('tbody tr')).length
      ? Array.from(table.querySelectorAll('tbody tr'))
      : Array.from(table.querySelectorAll('tr')).slice(1);
    const rows = bodyRows.map((tr) => {
      const cells = Array.from(tr.querySelectorAll('td')).map((cell) => clean(cell.innerText));
      const row = {};
      headers.forEach((header, index) => { row[header] = cells[index] || ''; });
      return row;
    }).filter((row) => Object.values(row).some(Boolean));
    if (rows.length) return rows;
  }

  const roleRows = Array.from(document.querySelectorAll('[role="row"]'));
  if (roleRows.length > 1) {
    const headers = Array.from(roleRows[0].querySelectorAll('[role="columnheader"], [role="gridcell"], div, span'))
      .map((cell) => clean(cell.innerText)).filter(Boolean);
    if (headers.length > 1) {
      return roleRows.slice(1).map((rowNode) => {
        const cells = Array.from(rowNode.querySelectorAll('[role="gridcell"], div, span'))
          .map((cell) => clean(cell.innerText)).filter(Boolean);
        const row = {};
        headers.forEach((header, index) => { row[header] = cells[index] || ''; });
        return row;
      }).filter((row) => Object.values(row).some(Boolean));
    }
  }
  return [];
}
"""

