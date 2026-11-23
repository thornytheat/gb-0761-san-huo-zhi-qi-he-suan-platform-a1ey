# 散货滞期核算台

港口商务专员用船方通知、港方事件簿、合同和账单复算滞期。在 `/` 查看船港分档差额，经左侧导航复核 7 个环节，从留档页执行重跑并在签发页下载证据包。

## 启动与验收

`docker compose up --build` 后访问 `http://localhost:18460/`。本地可执行 `pip install -r requirements.txt`、`python -m flask --app app.main run --port=18460` 和 `pytest -q`。`HARBOR_DB` 控制数据库文件，Compose 用命名卷。重置演示数据用 `docker compose down --volumes`。

前五个独立预览入口接收 `{"sample":"dirty"}`、`{"sample":"clean"}` 或 `{"sources":{"events":"CSV","stops":"CSV","terms":"CSV","invoice":"CSV"}}`。留档用 `POST /api/runs`，查询用 `GET /api/runs/<run_id>`，证据审读和下载见模块表。源码位于 `app/`，航次材料位于 `sample_data/`。

跨年争议样例应计 160.00 USD，船方列账 155.00 USD，尚有 15 分钟缺证。应用输出供核对与复核，签发状态取决于完整性和差异。

账单支持两种表头：旧式 `tier,minutes,usd` 按档单行对照；新式 `ticket,tier,minutes,usd` 允许同档拆多张原票，红字票以负分钟/负美元列示。对账页逐档给出可确认净额（净额在 0 处封边），红字票先于原票到时，超出已到原票的部分另列"待冲红字"（`RED_UNCOVERED`），该档差值待证且不可签发；晚到原票补齐后重新核对该档分钟与金额，核齐才恢复可签发。同票号重跑按完全一致去重，同一批票据留档重跑不重复冲减。

- [模块与陷阱](docs/DEPTH.md)
- [数据定义](docs/DATA-DICTIONARY.md)
