from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from src.config import get_settings
from src.db import Database


st.set_page_config(page_title="二连板策略看板", page_icon="📈", layout="wide")


STATUS_LABELS = {
    "active": "备选",
    "passed": "通过",
    "expired": "过期",
    "watching": "观察中",
}


@st.cache_data(ttl=30)
def read_sql(query: str, params: tuple = ()) -> pd.DataFrame:
    settings = get_settings()
    if not settings.db_path.exists():
        return pd.DataFrame()
    with sqlite3.connect(settings.db_path) as conn:
        return pd.read_sql_query(query, conn, params=params)


def init_database_if_needed() -> None:
    settings = get_settings()
    if settings.db_path.exists():
        return
    Database(settings.db_path).init()


def fmt_amount(value) -> str:
    if pd.isna(value):
        return ""
    value = float(value)
    if abs(value) >= 100000000:
        return f"{value / 100000000:.2f} 亿"
    if abs(value) >= 10000:
        return f"{value / 10000:.2f} 万"
    return f"{value:.2f}"


def status_zh(value: str) -> str:
    return STATUS_LABELS.get(value, value)


def home_page() -> None:
    st.title("二连板策略看板")
    init_database_if_needed()

    latest_job = read_sql(
        """
        SELECT job_name, run_date, started_at, finished_at, status, message
        FROM job_runs
        ORDER BY started_at DESC
        LIMIT 1
        """
    )
    active = read_sql(
        """
        SELECT cp.id, cp.code, s.name, s.market, cp.pool_date, cp.monitor_until, cp.status
        FROM candidate_pool cp
        JOIN stocks s ON s.code = cp.code
        WHERE cp.status = 'active'
        ORDER BY cp.pool_date DESC, cp.code
        """
    )
    today_results = read_sql(
        """
        SELECT sr.trade_date, sr.code, s.name, sr.volume_ratio_ok, sr.turnover_amount_ok,
               sr.fund_flow_3d, sr.fund_flow_ok, sr.final_status,
               ds.volume_ratio, ds.turnover_amount
        FROM strategy_results sr
        JOIN stocks s ON s.code = sr.code
        LEFT JOIN daily_snapshots ds
            ON ds.code = sr.code AND ds.trade_date = sr.trade_date AND ds.captured_at = '14:30'
        WHERE sr.trade_date = (SELECT MAX(trade_date) FROM strategy_results)
        ORDER BY sr.final_status DESC, sr.code
        """
    )

    col1, col2, col3, col4 = st.columns(4)
    passed_count = int((today_results["final_status"] == "passed").sum()) if not today_results.empty else 0
    warning_count = (
        int((today_results["volume_ratio_ok"].eq(1) & today_results["turnover_amount_ok"].eq(1)).sum())
        if not today_results.empty
        else 0
    )
    col1.metric("活跃备选", len(active))
    col2.metric("今日预警", warning_count)
    col3.metric("今日通过", passed_count)
    col4.metric("最近任务", latest_job.iloc[0]["status"] if not latest_job.empty else "暂无")

    if not latest_job.empty:
        with st.expander("最近任务日志", expanded=False):
            st.dataframe(latest_job, use_container_width=True, hide_index=True)

    st.subheader("今日策略结果")
    if today_results.empty:
        st.info("暂无 14:30 监控结果。运行 `python -m src.jobs monitor` 后会显示。")
    else:
        display = today_results.copy()
        display["final_status"] = display["final_status"].map(status_zh)
        display["turnover_amount"] = display["turnover_amount"].map(fmt_amount)
        display["fund_flow_3d"] = display["fund_flow_3d"].map(fmt_amount)
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.subheader("当前备选池")
    if active.empty:
        st.info("暂无活跃备选。收盘后运行 `python -m src.jobs close-scan` 可加入股票。")
    else:
        active_display = active.copy()
        active_display["status"] = active_display["status"].map(status_zh)
        st.dataframe(active_display, use_container_width=True, hide_index=True)


def history_page() -> None:
    st.title("历史记录")
    dates = read_sql("SELECT DISTINCT trade_date FROM strategy_results ORDER BY trade_date DESC")
    statuses = ["全部", "passed", "watching"]

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
        df["turnover_amount"] = df["turnover_amount"].map(fmt_amount)
        df["fund_flow_3d"] = df["fund_flow_3d"].map(fmt_amount)
        df["final_status"] = df["final_status"].map(status_zh)
        st.dataframe(df, use_container_width=True, hide_index=True)


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
               sr.fund_flow_3d, sr.final_status
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
    st.dataframe(pool_display, use_container_width=True, hide_index=True)

    st.subheader("14:30 快照")
    if snapshots.empty:
        st.info("暂无快照。")
    else:
        display = snapshots.copy()
        display["turnover_amount"] = display["turnover_amount"].map(fmt_amount)
        display["fund_flow_3d"] = display["fund_flow_3d"].map(fmt_amount)
        display["final_status"] = display["final_status"].map(status_zh)
        st.dataframe(display, use_container_width=True, hide_index=True)

    st.subheader("主力资金流")
    if flows.empty:
        st.info("暂无资金流记录。")
    else:
        chart_df = flows.sort_values("trade_date").set_index("trade_date")
        st.bar_chart(chart_df["main_net_inflow"])
        flows_display = flows.copy()
        flows_display["main_net_inflow"] = flows_display["main_net_inflow"].map(fmt_amount)
        st.dataframe(flows_display, use_container_width=True, hide_index=True)


def config_page() -> None:
    st.title("配置与任务")
    settings = get_settings()
    col1, col2 = st.columns(2)
    col1.metric("数据库", str(settings.db_path))
    col2.metric("SMTP", "已配置" if settings.smtp_host and settings.smtp_to else "未完整配置")

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
        st.dataframe(logs, use_container_width=True, hide_index=True)

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
        st.dataframe(emails, use_container_width=True, hide_index=True)


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

