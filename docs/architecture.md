# Architecture (贴近实盘版)

## Data sources

- **Gamma Markets API**: 取市场元数据、筛选 active/open，并按 `liquidityNum` 排序取 Top 50。参考官方 Gamma Get Markets 文档。 citeturn0search2
- **CLOB Public**: mid / orderbook / tick size 等公共方法（无需鉴权）。本项目实现中使用自建 httpx client + timeout，避免网络抖动导致主循环卡死。
- **CLOB User WebSocket**: `user` channel 需要 apiKey/secret/passphrase，用于接收你的订单与成交事件并形成 trade tape。 citeturn0search12turn1view4

## Execution

- **Live**：通过 py-clob-client 创建并提交订单；postOnly=true 的挂单如果跨价会被拒绝（这是你做市最需要的“保护带”之一）。 citeturn1view3turn1view0
- **Paper / Dry-run**：
  - 基于真实 orderbook 生成模拟成交（`PARTIAL/FILLED`），写入 `trades`
  - 对 YES/NO 两个 token 都报价与模拟成交（更贴近二元市场）
  - 成交强度支持按盘口顶部深度自适应（并可用分位数自动标定 depth_ref）
  - 生成成交后的 markout（成交后价格漂移）与 realized_spread，作为质量信号回写 calibration state（用于校准与资金分配）

## Order lifecycle

`OrderManager` 做三件事：
1. 定期撤掉 stale order（`cancel_reprice_sec`）
2. 价格变化超过 tick 则撤旧挂新
3. 单 token / 单市场最多挂 N 笔（防止订单堆积与撤单风暴）
