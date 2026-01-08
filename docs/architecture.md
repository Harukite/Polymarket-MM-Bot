# Architecture (贴近实盘版)

## Data sources

- **Gamma Markets API**: 取市场元数据、筛选 active/open，并按 `liquidityNum` 排序取 Top 50。参考官方 Gamma Get Markets 文档。 citeturn0search2
- **CLOB Public**: mid / orderbook / tick size 等公共方法（无需鉴权）。参考 Public Methods 列表。 citeturn1view1
- **CLOB User WebSocket**: `user` channel 需要 apiKey/secret/passphrase，用于接收你的订单与成交事件并形成 trade tape。 citeturn0search12turn1view4

## Execution

- **Live**：通过 py-clob-client 创建并提交订单；postOnly=true 的挂单如果跨价会被拒绝（这是你做市最需要的“保护带”之一）。 citeturn1view3turn1view0
- **Paper**：当前实现以“全链路落库/复盘”为主；如果你要更逼真的 paper 撮合（队列、部分成交、trade tape 触发），可以把你之前的撮合器移植进来。

## Order lifecycle

`OrderManager` 做三件事：
1. 定期撤掉 stale order（`cancel_reprice_sec`）
2. 价格变化超过 tick 则撤旧挂新
3. 单 token / 单市场最多挂 N 笔（防止订单堆积与撤单风暴）
