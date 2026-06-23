from __future__ import annotations

import argparse
import traceback
from datetime import date

from .akshare_client import AkShareClient
from .config import get_settings
from .dates import add_business_days, close_scan_default_date, is_business_day, parse_date
from .db import Database, Repository
from .eastmoney_client import EastMoneyClient
from .emailer import EmailNotConfigured, Emailer
from .parsing import to_db_decimal
from .strategy import MAX_VOLUME_RATIO, MIN_TURNOVER_AMOUNT, evaluate_snapshot
from .tushare_client import TushareClient
from .wencai import WencaiClient


def make_repo() -> Repository:
    settings = get_settings()
    repo = Repository(Database(settings.db_path))
    repo.init()
    return repo


def make_data_client(settings):
    if settings.data_source == "wencai":
        return WencaiClient(settings)
    return AkShareClient()


def fetch_close_scan_candidates(settings, run_date: date, repo: Repository | None = None):
    errors: list[str] = []
    if settings.tushare_token:
        try:
            cache_kwargs = {}
            if repo is not None:
                cache_kwargs = {"cache_get": repo.get_api_cache, "cache_set": repo.set_api_cache}
            client = TushareClient(
                settings.tushare_token,
                min_call_interval=settings.tushare_min_call_interval,
                **cache_kwargs,
            )
            return client.fetch_momentum_candidates(run_date), "tushare", errors
        except Exception as exc:
            errors.append(f"Tushare 失败：{exc}")

    try:
        candidates = AkShareClient().fetch_momentum_candidates(run_date)
        if candidates:
            return candidates, "akshare", errors
        errors.append("AkShare 返回 0 只")
    except Exception as exc:
        errors.append(f"AkShare 失败：{exc}")

    try:
        candidates = EastMoneyClient().fetch_momentum_candidates(run_date)
        return candidates, "eastmoney", errors
    except Exception as exc:
        errors.append(f"东方财富直连失败：{exc}")
        raise RuntimeError("收盘入池数据源全部失败：" + "；".join(errors)) from exc


def close_scan(run_date: date) -> int:
    settings = get_settings()
    repo = make_repo()
    job_id = repo.start_job("close_scan", run_date.isoformat())
    if not is_business_day(run_date):
        repo.finish_job(job_id, "skipped", "非交易日，跳过收盘后入池。", 0)
        return 0

    try:
        candidates, source, source_errors = fetch_close_scan_candidates(settings, run_date, repo)
        inserted = 0
        monitor_until = add_business_days(run_date, 10).isoformat()
        for candidate in candidates:
            if repo.add_candidate(candidate.to_record(), run_date.isoformat(), monitor_until):
                inserted += 1
        message = f"入池 {inserted} 只，数据源 {source} 返回 {len(candidates)} 只。"
        if source_errors:
            message += " 备用说明：" + "；".join(source_errors)
        repo.finish_job(job_id, "success", message, inserted)
        return inserted
    except Exception as exc:
        repo.finish_job(job_id, "failed", f"{exc}\n{traceback.format_exc()}", 0)
        raise


def monitor(run_date: date) -> int:
    settings = get_settings()
    repo = make_repo()
    job_id = repo.start_job("monitor", run_date.isoformat())
    if not is_business_day(run_date):
        repo.finish_job(job_id, "skipped", "非交易日，跳过盘中监控。", 0)
        return 0

    try:
        expired = repo.expire_candidates(run_date.isoformat())
        candidates = repo.active_candidates(run_date.isoformat())
        if not candidates:
            repo.finish_job(job_id, "success", f"无活跃备选，过期 {expired} 只。", 0)
            return 0

        client = make_data_client(settings)
        codes = [row["code"] for row in candidates]
        snapshots = {item.code: item for item in client.fetch_monitor_snapshots(codes)}
        warning_codes: list[str] = []
        for candidate in candidates:
            snapshot = snapshots.get(candidate["code"])
            if (
                snapshot is not None
                and snapshot.volume_ratio is not None
                and snapshot.volume_ratio < MAX_VOLUME_RATIO
                and snapshot.turnover_amount is not None
                and snapshot.turnover_amount >= MIN_TURNOVER_AMOUNT
            ):
                warning_codes.append(candidate["code"])

        intraday_flows = (
            client.fetch_intraday_fund_flows(warning_codes, run_date)
            if warning_codes and hasattr(client, "fetch_intraday_fund_flows")
            else {}
        )
        passed_results: list[dict[str, object]] = []

        for candidate in candidates:
            code = candidate["code"]
            snapshot = snapshots.get(code)
            if snapshot is None:
                continue

            repo.insert_daily_snapshot(
                {
                    "code": code,
                    "trade_date": run_date.isoformat(),
                    "captured_at": "14:30",
                    "volume_ratio": to_db_decimal(snapshot.volume_ratio),
                    "turnover_amount": to_db_decimal(snapshot.turnover_amount),
                    "is_limit_up": snapshot.is_limit_up,
                    "is_one_word_board": snapshot.is_one_word_board,
                    "raw_json": snapshot.raw_json,
                }
            )

            flow = intraday_flows.get(code)
            intraday_fund_flow = flow.main_net_inflow if flow is not None else None
            if flow is not None:
                repo.insert_fund_flow(
                    {
                        "code": code,
                        "trade_date": flow.trade_date,
                        "main_net_inflow": to_db_decimal(flow.main_net_inflow),
                        "raw_json": flow.raw_json,
                    }
                )

            decision = evaluate_snapshot(snapshot.volume_ratio, snapshot.turnover_amount, intraday_fund_flow)
            repo.upsert_strategy_result(
                {
                    "code": code,
                    "trade_date": run_date.isoformat(),
                    "candidate_pool_id": candidate["id"],
                    "volume_ratio_ok": decision.volume_ratio_ok,
                    "turnover_amount_ok": decision.turnover_amount_ok,
                    "fund_flow_3d": to_db_decimal(decision.fund_flow_3d),
                    "fund_flow_ok": decision.fund_flow_ok,
                    "final_status": decision.final_status,
                }
            )
            if decision.passed:
                repo.mark_candidate_passed(candidate["id"])
                passed_results.append(
                    {
                        "code": code,
                        "name": candidate["name"],
                        "volume_ratio": snapshot.volume_ratio,
                        "turnover_amount": snapshot.turnover_amount,
                        "intraday_fund_flow": decision.fund_flow_3d,
                    }
                )

        send_strategy_email(repo, settings, run_date, passed_results)
        repo.finish_job(
            job_id,
            "success",
            (
                f"监控 {len(candidates)} 只，预警 {len(warning_codes)} 只，"
                f"资金流取到 {len(intraday_flows)} 只，通过 {len(passed_results)} 只，过期 {expired} 只。"
            ),
            len(candidates),
        )
        return len(passed_results)
    except Exception as exc:
        repo.finish_job(job_id, "failed", f"{exc}\n{traceback.format_exc()}", 0)
        raise


def send_strategy_email(
    repo: Repository,
    settings,
    run_date: date,
    passed_results: list[dict[str, object]],
) -> None:
    if not passed_results:
        return
    emailer = Emailer(settings)
    subject = f"{run_date.isoformat()} 短线强势股预警通过名单"
    lines = [subject, ""]
    for item in passed_results:
        lines.append(
            f"{item['code']} {item['name']} | 量比 {item['volume_ratio']} | "
            f"成交额 {item['turnover_amount']} | 当日主力净流入 {item['intraday_fund_flow']}"
        )
    body = "\n".join(lines)

    try:
        unsent = [
            item
            for item in passed_results
            if any(
                not repo.email_already_sent(item["code"], run_date.isoformat(), "strategy_passed", recipient)
                for recipient in settings.smtp_to
            )
        ]
        if not unsent:
            return
        recipients = emailer.send(subject, body)
        for item in passed_results:
            for recipient in recipients:
                repo.log_email(item["code"], run_date.isoformat(), "strategy_passed", recipient, subject)
    except EmailNotConfigured:
        return


def test_email() -> None:
    settings = get_settings()
    Emailer(settings).send("股票策略看板测试邮件", "SMTP 配置可用。")


def main() -> None:
    parser = argparse.ArgumentParser(description="本地股票策略任务")
    parser.add_argument("command", choices=["init-db", "close-scan", "monitor", "test-email"])
    parser.add_argument("--date", dest="run_date", help="运行日期，格式 YYYY-MM-DD。close-scan 默认按收盘归属日自动判断。")
    args = parser.parse_args()

    if args.command == "close-scan":
        run_date = parse_date(args.run_date) if args.run_date else close_scan_default_date()
        print(f"新增入池：{close_scan(run_date)}")
        return

    run_date = parse_date(args.run_date)
    if args.command == "init-db":
        make_repo()
        print("数据库初始化完成")
    elif args.command == "monitor":
        print(f"通过数量：{monitor(run_date)}")
    elif args.command == "test-email":
        test_email()
        print("测试邮件已发送")


if __name__ == "__main__":
    main()
