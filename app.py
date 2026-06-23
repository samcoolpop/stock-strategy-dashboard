from __future__ import annotations

import hmac
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pandas as pd
import streamlit as st

from src.config import ROOT_DIR, get_settings
from src.db import Database


st.set_page_config(page_title="短线强势股预警看板", page_icon="chart_with_upwards_trend", layout="wide")


GITHUB_OWNER = "samcoolpop"
GITHUB_REPO = "stock-strategy-dashboard"
GITHUB_WORKFLOW = "sync-data.yml"
GITHUB_BRANCH = "main"


STATUS_LABELS = {
    "active": "备选",
    "passed": "通过",
    "expired": "过期",
    "watching": "观察中",
    "warning": "预警",
    "replaced": "已替换",
    "failed": "失败",
    "success": "成功",
    "running": "运行中",
    "skipped": "跳过",
}


def status_zh(value: str | None) -> str:
    if value is None:
        return ""
    return STATUS_LABELS.get(value, value)


def config_value(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, None)
        if value is not None:
            return str(value).strip()
    except Exception:
        pass
    return os.getenv(name, default).strip()


def trigger_github_workflow(job: str) -> tuple[bool, str]:
    token = config_value("GITHUB_ACTIONS_TOKEN")
    if not token:
        return False, "缺少 GITHUB_ACTIONS_TOKEN，无法触发 GitHub Actions。"

    owner = config_value("GITHUB_OWNER", GITHUB_OWNER)
    repo = config_value("GITHUB_REPO", GITHUB_REPO)
    workflow = config_value("GITHUB_WORKFLOW", GITHUB_WORKFLOW)
    branch = config_value("GITHUB_BRANCH", GITHUB_BRANCH)
    url = f"https://api.github.com/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
    payload = json.dumps({"ref": branch, "inputs": {"job": job}}).encode("utf-8")
    request = Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "stock-strategy-dashboard",
        },
    )
    try:
        with urlopen(request, timeout=20) as response:
            if response.status == 204:
                actions_url = f"https://github.com/{owner}/{repo}/actions/workflows/{workflow}"
                return True, f"已触发任务，稍后可在 {actions_url} 查看运行状态。"
            return False, f"GitHub 返回异常状态：{response.status}"
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        return False, f"GitHub API 请求失败：HTTP {exc.code} {detail}"
    except Exception as exc:
        return False, f"触发失败：{exc}"


def github_api_get(path: str) -> tuple[bool, dict | None, str]:
    token = config_value("GITHUB_ACTIONS_TOKEN")
    owner = config_value("GITHUB_OWNER", GITHUB_OWNER)
    repo = config_value("GITHUB_REPO", GITHUB_REPO)
    url = f"https://api.github.com/repos/{owner}/{repo}{path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "stock-strategy-dashboard",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=20) as response:
            return True, json.loads(response.read().decode("utf-8")), ""
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")[:500]
        return False, None, f"GitHub API 请求失败：HTTP {exc.code} {detail}"
    except Exception as exc:
        return False, None, f"读取 GitHub Actions 状态失败：{exc}"


@st.cache_data(ttl=15)
def workflow_runs() -> tuple[list[dict], str]:
    workflow = config_value("GITHUB_WORKFLOW", GITHUB_WORKFLOW)
    ok, data, error = github_api_get(f"/actions/workflows/{workflow}/runs?per_page=5")
    if not ok or data is None:
        return [], error
    return list(data.get("workflow_runs", [])), ""


def workflow_state() -> tuple[bool, str, list[dict]]:
    runs, error = workflow_runs()
    if error:
        return False, error, []
    busy_statuses = {"queued", "in_progress", "pending", "waiting", "requested"}
    busy = any(is_recent_busy_run(run, busy_statuses) for run in runs)
    return busy, "", runs


def is_recent_busy_run(run: dict, busy_statuses: set[str]) -> bool:
    if run.get("status") not in busy_statuses:
        return False
    timestamp = run.get("updated_at") or run.get("run_started_at") or run.get("created_at")
    if not timestamp:
        return True
    try:
        updated_at = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - updated_at <= timedelta(hours=2)


def run_status_zh(run: dict) -> str:
    status = run.get("status")
    conclusion = run.get("conclusion")
    if status != "completed":
        return {"queued": "排队中", "in_progress": "运行中", "pending": "等待中"}.get(status, str(status or "未知"))
    return {"success": "成功", "failure": "失败", "cancelled": "已取消", "skipped": "跳过"}.get(
        conclusion, str(conclusion or "完成")
    )


@st.cache_data(ttl=30)
def dashboard_db_path() -> str:
    settings = get_settings()
    remote_db_url = getattr(settings, "remote_db_url", "")
    if not remote_db_url:
        return str(settings.db_path)

    cache_dir = ROOT_DIR / ".cache"
    cache_dir.mkdir(exist_ok=True)
    remote_path = cache_dir / "dashboard_stock_strategy.sqlite3"
    try:
        separator = "&" if "?" in remote_db_url else "?"
        download_url = f"{remote_db_url}{separator}v={int(time.time() // 30)}"
        request = Request(
            download_url,
            headers={"Cache-Control": "no-cache", "Pragma": "no-cache"},
        )
        with urlopen(request, timeout=15) as response:
            content = response.read()
        if content.startswith(b"SQLite format 3"):
            remote_path.write_bytes(content)
            return str(remote_path)
    except Exception:
        pass
    return str(remote_path if remote_path.exists() else settings.db_path)


@st.cache_data(ttl=30)
def read_sql(query: str, params: tuple = ()) -> pd.DataFrame:
    try:
        db_path = Path(dashboard_db_path())
        if not db_path.exists():
            return pd.DataFrame()
        with sqlite3.connect(db_path) as conn:
            return pd.read_sql_query(query, conn, params=params)
    except Exception:
        return pd.DataFrame()


def init_database_if_needed() -> None:
    settings = get_settings()
    if settings.db_path.exists():
        return
    Database(settings.db_path).init()


def fmt_amount(value) -> str:
    if pd.isna(value):
        return "未取到"
    value = float(value)
    if abs(value) >= 100000000:
        return f"{value / 100000000:.2f} 亿"
    if abs(value) >= 10000:
        return f"{value / 10000:.2f} 万"
    return f"{value:.2f}"


def format_strategy_table(df: pd.DataFrame) -> pd.DataFrame:
    display = df.copy()
    if "final_status" in display.columns:
        display["final_status"] = display["final_status"].map(status_zh)
    if "pool_status" in display.columns:
        display["pool_status"] = display["pool_status"].map(status_zh)
    if "status" in display.columns:
        display["status"] = display["status"].map(status_zh)
    if "turnover_amount" in display.columns:
        display["turnover_amount"] = display["turnover_amount"].map(fmt_amount)
    if "fund_flow_3d" in display.columns:
        display["fund_flow_3d"] = display["fund_flow_3d"].map(fmt_amount)
        display = display.rename(columns={"fund_flow_3d": "intraday_fund_flow"})
    return display


def load_home_data() -> dict[str, pd.DataFrame]:
    return {
        "latest_monitor": read_sql(
            """
            SELECT id, job_name, run_date, started_at, finished_at, status, rows_processed, message
            FROM job_runs
            WHERE job_name = 'monitor'
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        "latest_close": read_sql(
            """
            SELECT id, job_name, run_date, started_at, finished_at, status, rows_processed, message
            FROM job_runs
            WHERE job_name = 'close_scan'
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        "active": read_sql(
            """
            SELECT cp.id, cp.code, s.name, s.market, cp.pool_date, cp.monitor_until, cp.status
            FROM candidate_pool cp
            JOIN stocks s ON s.code = cp.code
            WHERE cp.status = 'active'
            ORDER BY cp.pool_date DESC, cp.code
            """
        ),
        "latest_results": read_sql(
            """
            SELECT sr.trade_date, sr.code, s.name, sr.volume_ratio_ok, sr.turnover_amount_ok,
                   sr.fund_flow_3d, sr.fund_flow_ok, sr.final_status,
                   CASE
                       WHEN sr.fund_flow_3d IS NULL THEN '未取到'
                       WHEN sr.fund_flow_ok = 1 THEN '净流入'
                       ELSE '未净流入'
                   END AS fund_flow_status,
                   ds.volume_ratio, ds.turnover_amount,
                   cp.pool_date, cp.monitor_until, cp.status AS pool_status
            FROM strategy_results sr
            JOIN stocks s ON s.code = sr.code
            LEFT JOIN candidate_pool cp ON cp.id = sr.candidate_pool_id
            LEFT JOIN daily_snapshots ds
                ON ds.code = sr.code AND ds.trade_date = sr.trade_date AND ds.captured_at = '14:30'
            WHERE sr.trade_date = (SELECT MAX(trade_date) FROM strategy_results)
            ORDER BY cp.pool_date DESC, sr.final_status DESC, sr.code
            """
        ),
    }


def monitor_message(latest_monitor: pd.DataFrame, latest_results: pd.DataFrame) -> tuple[str, str]:
    if latest_monitor.empty:
        return "尚未运行", "还没有任何盘中监控任务记录。"

    monitor = latest_monitor.iloc[0]
    if monitor["status"] != "success":
        return "监控失败", str(monitor["message"] or "")[:400]

    if latest_results.empty:
        return "已运行，无结果表", "盘中监控任务成功运行，但没有写入策略结果。"

    warning_count = int(
        (
            latest_results["volume_ratio_ok"].eq(1)
            & latest_results["turnover_amount_ok"].eq(1)
        ).sum()
    )
    passed_count = int((latest_results["final_status"] == "passed").sum())
    missing_fund_count = int(
        (
            latest_results["volume_ratio_ok"].eq(1)
            & latest_results["turnover_amount_ok"].eq(1)
            & latest_results["fund_flow_3d"].isna()
        ).sum()
    )
    data_date = str(latest_results.iloc[0]["trade_date"])

    if warning_count == 0:
        return "已运行，未触发预警", f"{data_date} 已监控 {len(latest_results)} 只备选股，但暂无股票同时满足量比和成交额预警条件。"
    if passed_count == 0:
        if missing_fund_count:
            return (
                "已触发预警，资金流未取到",
                f"{data_date} 有 {warning_count} 只股票满足量比和成交额条件，其中 {missing_fund_count} 只未取到当日主力资金流，需要人工确认同花顺资金分析。",
            )
        return "已触发预警，未通过资金流", f"{data_date} 有 {warning_count} 只股票满足量比和成交额条件，但暂无股票通过当日主力资金净流入过滤。"
    return "已出现通过标的", f"{data_date} 有 {passed_count} 只股票通过全部条件。"


def home_page() -> None:
    st.title("短线强势股预警看板")
    init_database_if_needed()
    if st.button("刷新数据"):
        st.cache_data.clear()
        if hasattr(st, "rerun"):
            st.rerun()
        elif hasattr(st, "experimental_rerun"):
            st.experimental_rerun()

    data = load_home_data()
    latest_monitor = data["latest_monitor"]
    latest_close = data["latest_close"]
    active = data["active"]
    latest_results = data["latest_results"]

    status_title, status_detail = monitor_message(latest_monitor, latest_results)
    warning_count = (
        int((latest_results["volume_ratio_ok"].eq(1) & latest_results["turnover_amount_ok"].eq(1)).sum())
        if not latest_results.empty
        else 0
    )
    passed_count = int((latest_results["final_status"] == "passed").sum()) if not latest_results.empty else 0
    missing_fund_count = (
        int(
            (
                latest_results["volume_ratio_ok"].eq(1)
                & latest_results["turnover_amount_ok"].eq(1)
                & latest_results["fund_flow_3d"].isna()
            ).sum()
        )
        if not latest_results.empty
        else 0
    )

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("盘中监控状态", status_title)
    col2.metric("预警触发", warning_count)
    col3.metric("资金流未取到", missing_fund_count)
    col4.metric("最终通过", passed_count)
    col5.metric("活跃备选", len(active))

    st.subheader("盘中交易预警")
    st.info(status_detail)
    if not latest_monitor.empty:
        monitor_display = latest_monitor.copy()
        monitor_display["status"] = monitor_display["status"].map(status_zh)
        st.dataframe(monitor_display, width="stretch", hide_index=True)

    if latest_results.empty:
        st.info("暂无策略结果。盘中监控任务运行后会显示。")
    else:
        warning_results = latest_results[
            latest_results["volume_ratio_ok"].eq(1)
            & latest_results["turnover_amount_ok"].eq(1)
        ].copy()
        passed_results = latest_results[latest_results["final_status"].eq("passed")].copy()

        st.subheader("预警触发名单")
        if warning_results.empty:
            st.info("暂无股票同时满足量比和成交额预警条件。")
        else:
            missing_fund_results = warning_results[warning_results["fund_flow_3d"].isna()].copy()
            if not missing_fund_results.empty:
                st.warning(
                    f"{len(missing_fund_results)} 只预警股票未取到当日主力资金流，需人工查看同花顺资金分析确认。"
                )
            st.dataframe(format_strategy_table(warning_results), width="stretch", hide_index=True)

        st.subheader("最终通过名单")
        if passed_results.empty:
            st.info("暂无股票通过全部条件。若上方有预警触发名单，说明暂未通过当日主力资金净流入过滤。")
        else:
            st.dataframe(format_strategy_table(passed_results), width="stretch", hide_index=True)

        with st.expander("查看完整监控明细", expanded=False):
            st.dataframe(format_strategy_table(latest_results), width="stretch", hide_index=True)

    st.subheader("备选池更新")
    if latest_close.empty:
        st.info("暂无收盘后备选池更新任务记录。")
    else:
        close_display = latest_close.copy()
        close_display["status"] = close_display["status"].map(status_zh)
        st.dataframe(close_display, width="stretch", hide_index=True)

    st.subheader("当前备选池")
    if active.empty:
        st.info("暂无活跃备选。收盘后涨幅入池任务成功后会加入股票。")
    else:
        active_display = active.copy()
        active_display["status"] = active_display["status"].map(status_zh)
        st.dataframe(active_display, width="stretch", hide_index=True)


def history_page() -> None:
    st.title("历史记录")
    dates = read_sql("SELECT DISTINCT trade_date FROM strategy_results ORDER BY trade_date DESC")
    statuses = ["全部", "passed", "warning", "watching"]

    col1, col2, col3 = st.columns(3)
    selected_date = col1.selectbox("交易日期", ["全部"] + dates["trade_date"].tolist() if not dates.empty else ["全部"])
    selected_status = col2.selectbox("状态", statuses, format_func=status_zh)
    code_filter = col3.text_input("股票代码/名称")

    where = []
    params: list[str] = []
    if selected_date != "全部":
        where.append("sr.trade_date = ?")
        params.append(selected_date)
    if selected_status != "全部":
        where.append("sr.final_status = ?")
        params.append(selected_status)
    if code_filter:
        where.append("(sr.code LIKE ? OR s.name LIKE ?)")
        params.extend([f"%{code_filter}%", f"%{code_filter}%"])
    where_sql = "WHERE " + " AND ".join(where) if where else ""

    df = read_sql(
        f"""
        SELECT sr.trade_date, sr.code, s.name, s.market, ds.volume_ratio, ds.turnover_amount,
               sr.fund_flow_3d, sr.volume_ratio_ok, sr.turnover_amount_ok, sr.fund_flow_ok,
               CASE
                   WHEN sr.fund_flow_3d IS NULL THEN '未取到'
                   WHEN sr.fund_flow_ok = 1 THEN '净流入'
                   ELSE '未净流入'
               END AS fund_flow_status,
               sr.final_status
        FROM strategy_results sr
        JOIN stocks s ON s.code = sr.code
        LEFT JOIN daily_snapshots ds
            ON ds.code = sr.code AND ds.trade_date = sr.trade_date AND ds.captured_at = '14:30'
        {where_sql}
        ORDER BY sr.trade_date DESC, sr.code
        """,
        tuple(params),
    )
    if df.empty:
        st.info("没有匹配的历史记录。")
    else:
        st.dataframe(format_strategy_table(df), width="stretch", hide_index=True)


def stock_detail_page() -> None:
    st.title("个股详情")
    stocks = read_sql(
        """
        SELECT DISTINCT s.code, s.name
        FROM stocks s
        JOIN candidate_pool cp ON cp.code = s.code
        ORDER BY s.code
        """
    )
    if stocks.empty:
        st.info("暂无入池股票。")
        return
    options = [f"{row.code} {row.name}" for row in stocks.itertuples()]
    selected = st.selectbox("选择股票", options)
    code = selected.split(" ", 1)[0]

    pool = read_sql(
        """
        SELECT cp.*, s.name, s.market, s.is_chinext, s.is_star, s.is_st
        FROM candidate_pool cp
        JOIN stocks s ON s.code = cp.code
        WHERE cp.code = ?
        ORDER BY cp.pool_date DESC
        """,
        (code,),
    )
    snapshots = read_sql(
        """
        SELECT ds.trade_date, ds.captured_at, ds.volume_ratio, ds.turnover_amount,
               sr.fund_flow_3d,
               CASE
                   WHEN sr.fund_flow_3d IS NULL THEN '未取到'
                   WHEN sr.fund_flow_ok = 1 THEN '净流入'
                   ELSE '未净流入'
               END AS fund_flow_status,
               sr.final_status
        FROM daily_snapshots ds
        LEFT JOIN strategy_results sr ON sr.code = ds.code AND sr.trade_date = ds.trade_date
        WHERE ds.code = ?
        ORDER BY ds.trade_date DESC
        """,
        (code,),
    )
    flows = read_sql(
        """
        SELECT trade_date, main_net_inflow
        FROM fund_flow_snapshots
        WHERE code = ?
        ORDER BY trade_date DESC
        LIMIT 30
        """,
        (code,),
    )

    st.subheader("入池记录")
    pool_display = pool.copy()
    pool_display["status"] = pool_display["status"].map(status_zh)
    st.dataframe(pool_display, width="stretch", hide_index=True)

    st.subheader("14:30 快照")
    if snapshots.empty:
        st.info("暂无快照。")
    else:
        display = snapshots.copy()
        display["turnover_amount"] = display["turnover_amount"].map(fmt_amount)
        display["fund_flow_3d"] = display["fund_flow_3d"].map(fmt_amount)
        display["final_status"] = display["final_status"].map(status_zh)
        display = display.rename(columns={"fund_flow_3d": "intraday_fund_flow"})
        st.dataframe(display, width="stretch", hide_index=True)

    st.subheader("当日主力资金流")
    if flows.empty:
        st.info("暂无资金流记录。")
    else:
        chart_df = flows.sort_values("trade_date").set_index("trade_date")
        st.bar_chart(chart_df["main_net_inflow"])
        flows_display = flows.copy()
        flows_display["main_net_inflow"] = flows_display["main_net_inflow"].map(fmt_amount)
        st.dataframe(flows_display, width="stretch", hide_index=True)


def config_page() -> None:
    st.title("配置与任务")
    settings = get_settings()
    col1, col2, col3 = st.columns(3)
    col1.metric("数据库", str(dashboard_db_path()))
    col2.metric("SMTP", "已配置" if settings.smtp_host and settings.smtp_to else "未完整配置")
    col3.metric("收盘入池主源", "Tushare" if settings.tushare_token else "AkShare")

    st.subheader("手动补跑任务")
    admin_pin = config_value("ADMIN_PIN")
    token_ready = bool(config_value("GITHUB_ACTIONS_TOKEN"))
    workflow_busy, workflow_error, runs = workflow_state()

    if workflow_error:
        st.warning(workflow_error)
    elif runs:
        latest = runs[0]
        latest_url = latest.get("html_url", "")
        status_text = run_status_zh(latest)
        if workflow_busy:
            st.info(f"GitHub Actions 正在运行：#{latest.get('run_number')} {status_text}。请等待完成后再触发新的任务。")
        else:
            st.info(f"最近一次 GitHub Actions：#{latest.get('run_number')} {status_text}。")
        if latest_url:
            st.link_button("查看 GitHub 运行进度", latest_url)

        rows = []
        for run in runs:
            rows.append(
                {
                    "编号": run.get("run_number"),
                    "触发方式": run.get("event"),
                    "状态": run_status_zh(run),
                    "创建时间": run.get("created_at"),
                    "更新时间": run.get("updated_at"),
                    "链接": run.get("html_url"),
                }
            )
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if not admin_pin:
        st.warning("尚未配置 ADMIN_PIN，手动补跑按钮不可用。")
    elif not token_ready:
        st.warning("尚未配置 GITHUB_ACTIONS_TOKEN，手动补跑按钮不可用。")
    else:
        with st.form("manual_workflow_dispatch"):
            pin = st.text_input("操作密码", type="password")
            job_label = st.radio(
                "要执行的任务",
                ["盘中监控", "收盘入池", "两项都跑"],
                horizontal=True,
            )
            submitted = st.form_submit_button("触发抓数并同步网页", disabled=workflow_busy)
        if submitted:
            if not hmac.compare_digest(pin, admin_pin):
                st.error("操作密码不正确。")
            else:
                job_map = {"盘中监控": "monitor", "收盘入池": "close-scan", "两项都跑": "both"}
                ok, message = trigger_github_workflow(job_map[job_label])
                st.cache_data.clear()
                if ok:
                    st.success(message)
                    st.info("任务已发起。稍等几十秒后刷新本页查看进度；GitHub Actions 跑完并提交数据库后，回到首页点“刷新数据”即可看到新结果。")
                else:
                    st.error(message)

    st.subheader("任务日志")
    logs = read_sql(
        """
        SELECT job_name, run_date, started_at, finished_at, status, rows_processed, message
        FROM job_runs
        ORDER BY started_at DESC
        LIMIT 100
        """
    )
    if logs.empty:
        st.info("暂无任务日志。")
    else:
        logs["status"] = logs["status"].map(status_zh)
        st.dataframe(logs, width="stretch", hide_index=True)

    st.subheader("邮件日志")
    emails = read_sql(
        """
        SELECT code, trade_date, email_type, recipient, sent_at, subject
        FROM email_logs
        ORDER BY sent_at DESC
        LIMIT 100
        """
    )
    if emails.empty:
        st.info("暂无邮件发送记录。")
    else:
        st.dataframe(emails, width="stretch", hide_index=True)


def main() -> None:
    page = st.sidebar.radio("导航", ["首页", "历史记录", "个股详情", "配置与任务"])
    if page == "首页":
        home_page()
    elif page == "历史记录":
        history_page()
    elif page == "个股详情":
        stock_detail_page()
    else:
        config_page()


if __name__ == "__main__":
    main()
