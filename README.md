# 本地股票策略看板

本项目实现一个本地运行的二连板策略看板：

- 默认使用 AkShare 接口，收盘后确认二连板股票并加入备选池。
- 每个交易日 14:30 监控备选池股票的量比、成交额和近 3 日主力资金流。
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

- 北京时间 14:30 运行 `python -m src.jobs monitor`
- 北京时间 15:40 运行 `python -m src.jobs close-scan`
- 任务完成后把 `stock_strategy.sqlite3` 提交回仓库

Streamlit Cloud 会从仓库读取数据库文件。首次部署或手动刷新后，小伙伴访问公网地址即可看到最新已同步的数据。

## 策略规则

- 二连板入池，收盘后确认。
- 一字板、创业板保留。
- ST、科创板剔除。
- 入池后监控 10 个交易日。
- 14:30 量比 `<= 0.7`。
- 当日成交额 `>= 5亿元`。
- 最近 3 个交易日主力资金净流入合计 `> 0`。
