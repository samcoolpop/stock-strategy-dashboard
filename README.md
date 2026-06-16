# 本地股票策略看板

本项目实现一个本地运行的短线强势股预警看板：

- 默认使用 AkShare 接口，收盘后按 2/3 日累计收盘涨幅确认股票并加入备选池。
- 每个交易日 14:30 监控备选池股票的量比、成交额和当日主力资金流。
- 满足策略条件后写入 SQLite，并通过邮件提醒。
- Streamlit 网页展示今日结果、历史记录、个股详情和任务日志。

## 安装

```powershell
pip install -r requirements.txt
playwright install chromium
Copy-Item .env.example .env
```

编辑 `.env`，填写 SMTP 配置。默认 `APP_DATA_SOURCE=akshare`，不需要 token。

如果要切回同花顺问财网页采集，把 `.env` 改为 `APP_DATA_SOURCE=wencai`。第一次使用同花顺问财时建议保持 `WENCAI_HEADLESS=false`，手动登录后浏览器状态会保存在 `.wencai_browser`。

## 初始化数据库

```powershell
python -m src.jobs init-db
```

## 启动看板

```powershell
streamlit run app.py
```

默认访问：`http://localhost:8501`

## 手动运行任务

收盘后入池：

```powershell
python -m src.jobs close-scan
```

14:30 监控：

```powershell
python -m src.jobs monitor
```

发送测试邮件：

```powershell
python -m src.jobs test-email
```

## Windows 任务计划建议

创建两个任务：

- 周一至周五 14:30：运行 `python -m src.jobs monitor`
- 周一至周五 15:30 或 16:00：运行 `python -m src.jobs close-scan`

任务工作目录设置为本项目目录。

## 云端同步

仓库包含 GitHub Actions 工作流 `.github/workflows/sync-data.yml`：

- 北京时间 14:10、14:15、14:20 冗余运行 `python -m src.jobs monitor`
- 北京时间 15:40 运行 `python -m src.jobs close-scan`
- 任务完成后把 `stock_strategy.sqlite3` 提交回仓库

Streamlit Cloud 会从仓库读取数据库文件。首次部署或手动刷新后，小伙伴访问公网地址即可看到最新已同步的数据。

### 网页手动补跑

“配置与任务”页支持手动触发 GitHub Actions。朋友发现数据没有刷新时，可以输入操作密码并点击按钮补跑：

- `盘中监控`：触发 `python -m src.jobs monitor`
- `收盘入池`：触发 `python -m src.jobs close-scan`
- `两项都跑`：两个任务都执行

需要在 Streamlit Cloud 的 Secrets 中配置：

```toml
ADMIN_PIN = "一个只告诉可信使用者的操作密码"
GITHUB_ACTIONS_TOKEN = "可触发 workflow_dispatch 的 GitHub token"
GITHUB_OWNER = "samcoolpop"
GITHUB_REPO = "stock-strategy-dashboard"
GITHUB_WORKFLOW = "sync-data.yml"
GITHUB_BRANCH = "main"
```

`GITHUB_ACTIONS_TOKEN` 建议使用 fine-grained token，仅授权 `stock-strategy-dashboard` 仓库，并授予 Actions 读写权限。不要把 token 写进代码或提交到仓库。

## 策略规则

- 收盘后入池，按收盘价计算：近 2 个交易日累计涨幅 `>= 15%`，或近 3 个交易日累计涨幅 `>= 20%`。
- ST、科创板、北交所剔除。
- 入池后监控 10 个交易日。
- 14:30 量比 `< 0.8`。
- 当日成交额 `>= 5亿元`。
- 14:30 当日主力资金净流入 `> 0`。

## 数据源兜底

盘中监控会尽量从多个来源补齐关键字段：

- 实时行情主源：东方财富全市场行情，取量比和成交额。
- 量比兜底：东方财富单股盘口报价，逐只补查主源缺失的量比。
- 成交额兜底：腾讯实时行情。
- 资金流主源：东方财富当日主力资金流排名。
- 资金流兜底：东方财富单股历史资金流中当天记录。

如果量比仍缺失，系统不会误判为通过；快照原始数据中会记录字段缺失状态，方便排查未预警原因。
