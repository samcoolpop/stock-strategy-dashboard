from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable

import requests

from .parsing import parse_decimal
from .strategy import (
    MIN_THREE_DAY_GAIN,
    MIN_TWO_DAY_GAIN,
    StockCandidate,
    infer_market,
    is_chinext_market,
    is_star_market,
)


class TushareError(RuntimeError):
    pass


CacheGet = Callable[[str], str | None]
CacheSet = Callable[[str, str], None]


@dataclass
class TushareClient:
    token: str
    retries: int = 2
    retry_delay: float = 1.0
    min_call_interval: float = 65.0
    api_url: str = "https://api.tushare.pro"
    cache_get: CacheGet | None = None
    cache_set: CacheSet | None = None
    _last_call_at: float = field(default=0.0, init=False, repr=False)

    def fetch_momentum_candidates(self, run_date: date | None = None) -> list[StockCandidate]:
        if not self.token:
            raise TushareError("缺少 TUSHARE_TOKEN，无法使用 Tushare 收盘入池数据源。")

        query_date = run_date or date.today()
        trade_dates = self._recent_trade_dates(query_date, 4)
        if len(trade_dates) < 4:
            raise TushareError("Tushare 交易日历返回不足 4 个交易日，无法计算入池条件。")

        stocks = self._stock_basic()
        close_by_code: dict[str, dict[str, Decimal]] = {}
        for trade_date in trade_dates:
            for row in self._daily_close(trade_date):
                ts_code = str(row.get("ts_code") or "")
                close = parse_decimal(row.get("close"))
                if not ts_code or close is None:
                    continue
                close_by_code.setdefault(ts_code, {})[trade_date] = close

        candidates: list[StockCandidate] = []
        for ts_code, closes_by_date in close_by_code.items():
            if any(trade_date not in closes_by_date for trade_date in trade_dates):
                continue
            stock = stocks.get(ts_code)
            if not stock:
                continue

            closes = [closes_by_date[trade_date] for trade_date in trade_dates]
            gain_2d = (closes[-1] / closes[-3]) - Decimal("1")
            gain_3d = (closes[-1] / closes[-4]) - Decimal("1")
            if gain_2d < MIN_TWO_DAY_GAIN and gain_3d < MIN_THREE_DAY_GAIN:
                continue

            code = str(stock["symbol"])
            name = str(stock["name"]).strip()
            market = infer_market(code, str(stock.get("market") or ""))
            candidate = StockCandidate(
                code=code,
                name=name,
                market=market,
                is_st="ST" in name.upper(),
                is_star=is_star_market(code, market),
                is_chinext=is_chinext_market(code, market),
                gain_2d=gain_2d,
                gain_3d=gain_3d,
            )
            if candidate.eligible_for_pool:
                candidates.append(candidate)
        return sorted(candidates, key=lambda item: item.code)

    def _recent_trade_dates(self, end_date: date, limit: int) -> list[str]:
        start_date = (end_date - timedelta(days=30)).strftime("%Y%m%d")
        rows = self._call(
            "trade_cal",
            {"exchange": "SSE", "start_date": start_date, "end_date": end_date.strftime("%Y%m%d")},
            "cal_date,is_open",
        )
        open_dates = sorted(str(row["cal_date"]) for row in rows if int(row.get("is_open") or 0) == 1)
        return open_dates[-limit:]

    def _stock_basic(self) -> dict[str, dict[str, Any]]:
        rows = self._call(
            "stock_basic",
            {"exchange": "", "list_status": "L"},
            "ts_code,symbol,name,market",
        )
        return {str(row["ts_code"]): row for row in rows if row.get("ts_code") and row.get("symbol")}

    def _daily_close(self, trade_date: str) -> list[dict[str, Any]]:
        return self._call("daily", {"trade_date": trade_date}, "ts_code,trade_date,close")

    def _call(self, api_name: str, params: dict[str, Any], fields: str) -> list[dict[str, Any]]:
        cache_key = self._cache_key(api_name, params, fields)
        cached = self._read_cache(cache_key)
        if cached is not None:
            return cached

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                self._wait_for_rate_limit()
                response = requests.post(
                    self.api_url,
                    json={"api_name": api_name, "token": self.token, "params": params, "fields": fields},
                    timeout=30,
                )
                response.raise_for_status()
                payload = response.json()
                self._last_call_at = time.monotonic()
                if payload.get("code") != 0:
                    raise TushareError(f"Tushare {api_name} 返回错误：{payload.get('msg') or payload}")
                data = payload.get("data") or {}
                columns = data.get("fields") or []
                items = data.get("items") or []
                rows = [dict(zip(columns, item)) for item in items]
                self._write_cache(cache_key, rows)
                return rows
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.retry_delay * (attempt + 1))
        raise TushareError(
            f"Tushare 接口失败：{api_name} {json.dumps(params, ensure_ascii=False)}：{last_error}"
        ) from last_error

    def _cache_key(self, api_name: str, params: dict[str, Any], fields: str) -> str:
        payload = json.dumps({"api_name": api_name, "params": params, "fields": fields}, sort_keys=True)
        return f"tushare:{payload}"

    def _read_cache(self, cache_key: str) -> list[dict[str, Any]] | None:
        if self.cache_get is None:
            return None
        try:
            payload = self.cache_get(cache_key)
            if not payload:
                return None
            data = json.loads(payload)
            if isinstance(data, list):
                return [row for row in data if isinstance(row, dict)]
        except Exception:
            return None
        return None

    def _write_cache(self, cache_key: str, rows: list[dict[str, Any]]) -> None:
        if self.cache_set is None:
            return
        try:
            self.cache_set(cache_key, json.dumps(rows, ensure_ascii=False, default=str))
        except Exception:
            return

    def _wait_for_rate_limit(self) -> None:
        if self.min_call_interval <= 0 or self._last_call_at <= 0:
            return
        elapsed = time.monotonic() - self._last_call_at
        remaining = self.min_call_interval - elapsed
        if remaining > 0:
            time.sleep(remaining)
