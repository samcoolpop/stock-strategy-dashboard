from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, TypeVar

import pandas as pd
import requests

from .parsing import parse_cny_amount, parse_decimal
from .strategy import (
    MonitorSnapshot,
    MIN_THREE_DAY_GAIN,
    MIN_TWO_DAY_GAIN,
    StockCandidate,
    infer_market,
    is_chinext_market,
    is_star_market,
)
from .wencai import FundFlow


class AkShareError(RuntimeError):
    pass


T = TypeVar("T")
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"}


@dataclass(frozen=True)
class AkShareClient:
    retries: int = 2
    retry_delay: float = 1.0

    def fetch_momentum_candidates(self, run_date: date | None = None) -> list[StockCandidate]:
        query_date = run_date or date.today()
        spot = self._fetch_spot_with_volume_ratio()
        if spot is None or spot.empty:
            return []

        rows = []
        for row in spot.to_dict("records"):
            code = self._clean_code(row.get("代码"))
            name = str(row.get("名称") or "").strip()
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
            if candidate.eligible_for_pool:
                rows.append((code, name, market, candidate))

        candidates: list[StockCandidate] = []
        with ThreadPoolExecutor(max_workers=24) as executor:
            futures = {
                executor.submit(self._fetch_recent_closes, code, query_date, 4): (code, name, market)
                for code, name, market, _candidate in rows
            }
            for future in as_completed(futures):
                code, name, market = futures[future]
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
                            code=code,
                            name=name,
                            market=market,
                            is_st=False,
                            is_star=is_star_market(code, market),
                            is_chinext=is_chinext_market(code, market),
                            gain_2d=gain_2d,
                            gain_3d=gain_3d,
                        )
                    )
        return sorted(candidates, key=lambda item: item.code)

    def fetch_two_limit_up(self, run_date: date | None = None) -> list[StockCandidate]:
        import akshare as ak

        query_date = (run_date or date.today()).strftime("%Y%m%d")
        df = self._call(lambda: ak.stock_zt_pool_em(date=query_date), "涨停池")
        if df.empty:
            return []

        candidates: list[StockCandidate] = []
        for row in df.to_dict("records"):
            code = self._clean_code(row.get("代码"))
            name = str(row.get("名称") or "").strip()
            if not code or not name:
                continue
            limit_count = parse_decimal(row.get("连板数")) or Decimal("0")
            if limit_count != Decimal("2"):
                continue
            market = infer_market(code)
            candidate = StockCandidate(
                code=code,
                name=name,
                market=market,
                is_st="ST" in name.upper(),
                is_star=is_star_market(code, market),
                is_chinext=is_chinext_market(code, market),
                is_one_word_board=self._is_one_word_board(row),
            )
            if candidate.eligible_for_pool:
                candidates.append(candidate)
        return candidates

    def fetch_monitor_snapshots(self, codes: list[str]) -> list[MonitorSnapshot]:
        if not codes:
            return []
        wanted = {self._clean_code(code) for code in codes}
        spot = self._fetch_spot_with_volume_ratio()
        if spot is None:
            spot = self._fetch_tencent_quotes(list(wanted))

        snapshots: list[MonitorSnapshot] = []
        for row in spot.to_dict("records"):
            code = self._clean_code(row.get("代码"))
            if code not in wanted:
                continue
            snapshots.append(
                MonitorSnapshot(
                    code=code,
                    name=str(row.get("名称") or "").strip(),
                    volume_ratio=parse_decimal(row.get("量比")),
                    turnover_amount=parse_cny_amount(row.get("成交额")),
                    raw_json=json.dumps(row, ensure_ascii=False, default=str),
                )
            )
        return snapshots

    def fetch_recent_fund_flows(self, code: str, end_date: date) -> list[FundFlow]:
        import akshare as ak

        market = self._market_arg(code)
        try:
            df = self._call(
                lambda: ak.stock_individual_fund_flow(stock=self._clean_code(code), market=market),
                f"{code} 资金流",
            )
        except Exception:
            return []
        if df.empty:
            return []

        date_col = self._find_col(df, "日期", "交易日期")
        flow_col = self._find_col(df, "主力净流入-净额", "主力净流入")
        if not date_col or not flow_col:
            return []

        flows: list[FundFlow] = []
        recent = df.sort_values(date_col).tail(3)
        for row in recent.to_dict("records"):
            flows.append(
                FundFlow(
                    code=self._clean_code(code),
                    trade_date=str(row.get(date_col))[:10],
                    main_net_inflow=parse_cny_amount(row.get(flow_col)),
                    raw_json=json.dumps(row, ensure_ascii=False, default=str),
                )
            )
        return flows

    def fetch_intraday_fund_flows(self, codes: list[str], run_date: date) -> dict[str, FundFlow]:
        wanted = {self._clean_code(code) for code in codes if self._clean_code(code)}
        if not wanted:
            return {}

        flows = self._fetch_rank_fund_flows(wanted, run_date)
        return flows

    def _fetch_rank_fund_flows(self, wanted: set[str], run_date: date) -> dict[str, FundFlow]:
        fields = "f12,f14,f62"
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            "?pn=1&pz=6000&po=1&np=1&fltt=2&invt=2&fid=f62"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            f"&fields={fields}"
        )
        try:
            response = requests.get(url, timeout=15, headers=REQUEST_HEADERS)
            response.raise_for_status()
            rows = ((response.json().get("data") or {}).get("diff") or [])
        except Exception:
            return {}

        result: dict[str, FundFlow] = {}
        for row in rows:
            code = self._clean_code(row.get("f12"))
            if code not in wanted:
                continue
            flow = parse_cny_amount(row.get("f62"))
            if flow is None:
                continue
            result[code] = FundFlow(
                code=code,
                trade_date=run_date.isoformat(),
                main_net_inflow=flow,
                raw_json=json.dumps(
                    {"code": row.get("f12"), "name": row.get("f14"), "main_net_inflow": row.get("f62")},
                    ensure_ascii=False,
                    default=str,
                ),
            )
        return result

    def _fetch_single_day_fund_flow(self, code: str, run_date: date) -> FundFlow | None:
        flows = self.fetch_recent_fund_flows(code, run_date)
        for flow in flows:
            if flow.trade_date == run_date.isoformat():
                return flow
        return None

    def _fetch_spot_with_volume_ratio(self) -> pd.DataFrame | None:
        import akshare as ak

        direct = self._fetch_eastmoney_spot()
        if direct is not None and not direct.empty:
            return direct
        try:
            return self._call(lambda: ak.stock_zh_a_spot_em(), "实时行情-东方财富")
        except Exception:
            return None

    def _fetch_tencent_quotes(self, codes: list[str]) -> pd.DataFrame:
        symbols = [self._tencent_symbol(code) for code in codes if self._clean_code(code)]
        if not symbols:
            return pd.DataFrame()
        url = "https://qt.gtimg.cn/q=" + ",".join(symbols)
        response = self._call(lambda: requests.get(url, timeout=15), "实时行情-腾讯")
        response.encoding = "gbk"
        rows: list[dict[str, object]] = []
        for line in response.text.splitlines():
            if '="' not in line:
                continue
            payload = line.split('="', 1)[1].rstrip('";')
            fields = payload.split("~")
            if len(fields) < 38:
                continue
            amount = None
            if "/" in fields[35]:
                amount = parse_cny_amount(fields[35].split("/")[-1])
            if amount is None:
                amount_wan = parse_decimal(fields[37])
                amount = amount_wan * Decimal("10000") if amount_wan is not None else None
            rows.append(
                {
                    "代码": self._clean_code(fields[2]),
                    "名称": fields[1],
                    "成交额": amount,
                    "量比": None,
                }
            )
        return pd.DataFrame(rows)

    def _fetch_eastmoney_spot(self) -> pd.DataFrame | None:
        fields = "f12,f14,f3,f6,f10"
        url = (
            "https://push2.eastmoney.com/api/qt/clist/get"
            "?pn=1&pz=6000&po=1&np=1&fltt=2&invt=2&fid=f3"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            f"&fields={fields}"
        )
        try:
            response = requests.get(url, timeout=15, headers=REQUEST_HEADERS)
            response.raise_for_status()
            rows = ((response.json().get("data") or {}).get("diff") or [])
        except Exception:
            return None
        return pd.DataFrame(
            {
                "代码": self._clean_code(row.get("f12")),
                "名称": str(row.get("f14") or "").strip(),
                "涨跌幅": parse_decimal(row.get("f3")),
                "成交额": parse_cny_amount(row.get("f6")),
                "量比": parse_decimal(row.get("f10")),
            }
            for row in rows
        )

    def _fetch_recent_closes(self, code: str, end_date: date, limit: int) -> list[Decimal]:
        clean = self._clean_code(code)
        secid = self._eastmoney_secid(clean)
        begin = (end_date - timedelta(days=21)).strftime("%Y%m%d")
        end = end_date.strftime("%Y%m%d")
        url = (
            "https://push2his.eastmoney.com/api/qt/stock/kline/get"
            f"?secid={secid}&fields1=f1,f2,f3,f4,f5,f6"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            f"&klt=101&fqt=0&beg={begin}&end={end}"
        )
        try:
            response = self._call(lambda: requests.get(url, timeout=10, headers=REQUEST_HEADERS), f"{clean} 日线")
            payload = response.json()
        except Exception:
            return []
        klines = (payload.get("data") or {}).get("klines") or []
        closes: list[Decimal] = []
        for line in klines[-limit:]:
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
                return func()
            except Exception as exc:  # pragma: no cover - network-dependent
                last_error = exc
                if attempt < self.retries:
                    time.sleep(self.retry_delay * (attempt + 1))
        raise AkShareError(f"AkShare 接口失败：{label}：{last_error}") from last_error

    @staticmethod
    def _clean_code(value: object) -> str:
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        return digits[-6:] if len(digits) >= 6 else ""

    @staticmethod
    def _market_arg(code: str) -> str:
        clean = AkShareClient._clean_code(code)
        if clean.startswith(("6", "688")):
            return "sh"
        if clean.startswith(("4", "8", "9")):
            return "bj"
        return "sz"

    @staticmethod
    def _eastmoney_secid(code: str) -> str:
        clean = AkShareClient._clean_code(code)
        if clean.startswith(("6", "688")):
            return "1." + clean
        if clean.startswith(("4", "8", "9")):
            return "0." + clean
        return "0." + clean

    @staticmethod
    def _tencent_symbol(code: str) -> str:
        clean = AkShareClient._clean_code(code)
        if clean.startswith(("6", "688")):
            return "sh" + clean
        if clean.startswith(("4", "8", "9")):
            return "bj" + clean
        return "sz" + clean

    @staticmethod
    def _find_col(df: pd.DataFrame, *candidates: str) -> str | None:
        for candidate in candidates:
            if candidate in df.columns:
                return candidate
        for col in df.columns:
            if any(candidate in str(col) for candidate in candidates):
                return str(col)
        return None

    @staticmethod
    def _find_flow_col(df: pd.DataFrame) -> str | None:
        preferred = (
            "今日主力净流入净额",
            "主力净流入-净额",
            "主力净流入",
            "主力净额",
            "净额",
        )
        for name in preferred:
            if name in df.columns:
                return name
        for col in df.columns:
            text = str(col)
            if "主力" in text and ("净流入" in text or "净额" in text):
                return text
        for col in df.columns:
            text = str(col)
            if text.endswith("净额") or text == "净流入":
                return text
        return None

    @staticmethod
    def _is_one_word_board(row: dict[str, object]) -> bool:
        first = str(row.get("首次封板时间") or "")
        last = str(row.get("最后封板时间") or "")
        breaks = parse_decimal(row.get("炸板次数")) or Decimal("0")
        return bool(first and first <= "092500" and first == last and breaks == 0)
