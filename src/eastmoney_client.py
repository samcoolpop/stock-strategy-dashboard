from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, TypeVar

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


class EastMoneyError(RuntimeError):
    pass


T = TypeVar("T")
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


@dataclass(frozen=True)
class EastMoneyClient:
    retries: int = 2
    retry_delay: float = 1.0
    max_workers: int = 24

    def fetch_momentum_candidates(self, run_date: date | None = None) -> list[StockCandidate]:
        query_date = run_date or date.today()
        rows = self._fetch_stock_universe()
        if not rows:
            raise EastMoneyError("东方财富股票列表为空，无法计算收盘入池。")

        candidates: list[StockCandidate] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._fetch_recent_closes, row["code"], query_date, 4): row
                for row in rows
            }
            for future in as_completed(futures):
                row = futures[future]
                closes = future.result()
                if len(closes) < 3:
                    continue
                gain_2d = (closes[-1] / closes[-3]) - Decimal("1")
                gain_3d = (closes[-1] / closes[-4]) - Decimal("1") if len(closes) >= 4 else None
                if gain_2d >= MIN_TWO_DAY_GAIN or (
                    gain_3d is not None and gain_3d >= MIN_THREE_DAY_GAIN
                ):
                    candidates.append(
                        StockCandidate(
                            code=row["code"],
                            name=row["name"],
                            market=row["market"],
                            is_st=row["is_st"],
                            is_star=row["is_star"],
                            is_chinext=row["is_chinext"],
                            gain_2d=gain_2d,
                            gain_3d=gain_3d,
                        )
                    )
        return sorted(candidates, key=lambda item: item.code)

    def _fetch_stock_universe(self) -> list[dict[str, object]]:
        fields = "f12,f14"
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            "?pn=1&pz=6000&po=1&np=1&fltt=2&invt=2&fid=f3"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            f"&fields={fields}"
        )
        response = self._call(lambda: requests.get(url, timeout=20, headers=REQUEST_HEADERS), "stock universe")
        rows = ((response.json().get("data") or {}).get("diff") or [])
        result: list[dict[str, object]] = []
        for item in rows:
            code = self._clean_code(item.get("f12"))
            name = str(item.get("f14") or "").strip()
            if not code or not name:
                continue
            market = infer_market(code)
            candidate = StockCandidate(
                code=code,
                name=name,
                market=market,
                is_st="ST" in name.upper(),
                is_star=is_star_market(code, market),
                is_chinext=is_chinext_market(code, market),
            )
            if not candidate.eligible_for_pool:
                continue
            result.append(
                {
                    "code": code,
                    "name": name,
                    "market": market,
                    "is_st": candidate.is_st,
                    "is_star": candidate.is_star,
                    "is_chinext": candidate.is_chinext,
                }
            )
        return result

    def _fetch_recent_closes(self, code: str, end_date: date, limit: int) -> list[Decimal]:
        clean = self._clean_code(code)
        secid = self._eastmoney_secid(clean)
        begin = (end_date - timedelta(days=30)).strftime("%Y%m%d")
        end = end_date.strftime("%Y%m%d")
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101&fqt=0&beg={begin}&end={end}"
        )
        try:
            response = self._call(lambda: requests.get(url, timeout=10, headers=REQUEST_HEADERS), f"{clean} kline")
            payload = response.json()
        except Exception:
            return []
        closes: list[Decimal] = []
        for line in ((payload.get("data") or {}).get("klines") or [])[-limit:]:
            fields = str(line).split(",")
            if len(fields) < 3:
                continue
            close = parse_decimal(fields[2])
            if close is not None:
                closes.append(close)
        return closes[-limit:]

    def _call(self, func: Callable[[], T], label: str) -> T:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                response = func()
                if hasattr(response, "raise_for_status"):
                    response.raise_for_status()
                return response
            except Exception as exc:
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.retry_delay * (attempt + 1))
        raise EastMoneyError(f"东方财富接口失败：{label}：{last_error}") from last_error

    @staticmethod
    def _clean_code(value: object) -> str:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return digits[-6:] if len(digits) >= 6 else ""

    @staticmethod
    def _eastmoney_secid(code: str) -> str:
        clean = EastMoneyClient._clean_code(code)
        if clean.startswith(("6", "688")):
            return "1." + clean
        return "0." + clean

    @staticmethod
    def _json(row: object) -> str:
        return json.dumps(row, ensure_ascii=False, default=str)
