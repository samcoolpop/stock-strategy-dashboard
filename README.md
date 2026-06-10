# 本地股票策略看板

本项目实现一个本地运行的二连板策略看板：

- 默认使用 AkShare 接口，收盘后确认二连板股票并加入备选池。
- 每个交易日 14:30 监控备选池股票的量比、成交额和近 3 日主力资金流。
- 满足策略条件后写入 SQLite，并通过邮件提醒。
- Streamlit 网页展示今日结果、历史记录、个股详情和任务日志。

## 安装

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

编辑 `.env`，填写 SMTP 配置。默认 `APP_DATA_SOURCE=akshare`，不需要 token。

如果要切回同花顺问财网页采集，把 `.env` 改为 `APP_DATA_SOURCE=wencai`。第一次使用同花顺问财时建议保持 `WENCAI_HEADLESS=false`，手动登录后浏览器状态会保存在 `.wencai_browser`。

## 初始化数据库

```bash
.venv/bin/python -m src.jobs init-db
```

## 启动看板

```bash
.venv/bin/streamlit run app.py
```

默认访问：`http://localhost:8501`

## 手动运行任务

收盘后入池：

```bash
.venv/bin/python -m src.jobs close-scan
```

14:30 监控：

```bash
.venv/bin/python -m src.jobs monitor
```

发送测试邮件：

```bash
.venv/bin/python -m src.jobs test-email
```

## macOS 定时任务

这台 Mac 可以用 `launchd` 定时运行任务。执行一次安装脚本：

```bash
./scripts/install_macos_launchd.sh
```

安装后会创建两个用户定时任务：

- 周一至周五 14:10、14:15、14:20：运行 `scripts/run_monitor_and_push.sh`
- 周一至周五 15:40：运行 `scripts/run_close_scan_and_push.sh`

脚本会先运行对应任务，再把 `stock_strategy.sqlite3` 提交并推送到 GitHub。这台 Mac 需要提前配置好 GitHub push 权限。安装脚本会把 `launchd` 配置写入 `~/Library/LaunchAgents/`，登录后会自动按时运行。

## 云端同步

仓库保留 GitHub Actions 工作流 `.github/workflows/sync-data.yml` 作为手动备用入口。自动定时抓数由这台 Mac 的 `launchd` 负责。

任务完成后，脚本会把 `stock_strategy.sqlite3` 提交回仓库。

Streamlit Cloud 会从仓库读取数据库文件。首次部署或手动刷新后，小伙伴访问公网地址即可看到最新已同步的数据。

## 策略规则

- 二连板入池，收盘后确认。
- 一字板、创业板保留。
- ST、科创板剔除。
- 入池后监控 10 个交易日。
- 14:30 量比 `<= 0.7`。
- 当日成交额 `>= 5亿元`。
- 最近 3 个交易日主力资金净流入合计 `> 0`。
