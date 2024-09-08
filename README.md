# 做市腳本解釋

這個 Python 腳本是一個在 Binance 和 ACE 交易所之間操作的做市機器人。它使用 WebSocket 連接接收實時訂單簿更新，並根據從 Binance 收到的數據在 ACE 交易所執行交易。該腳本使用 `asyncio` 進行異步編程，以高效處理並發任務。

## 關鍵組件

1. **導入和依賴項**：
   - 腳本導入了一些標準 Python 庫（如 `asyncio`、`json`、`time` 等）和第三方庫（如 `BinanceSocketManager`、`requests`）。它還導入了數學和日誌記錄庫來處理數值計算和日誌記錄。

2. **日誌配置**：
   - `configure_logging(symbol)` 函數配置日誌輸出到文件和控制台（`stdout`）。它基於當前日期創建一個日誌目錄，並設置日誌記錄保存到與提供的 `self.config.ACE_SYMBOL` 對應的目錄中的 `mmaker.log` 文件。

3. **常數**：
   - `HEDGE_MAPPING` 是一個字典，用於確定交易的對沖方向（例如，如果需要對沖買單，則會下賣單）。

## 類別：`MMaker`

`MMaker` 類封裝了做市機器人的核心功能。該類包含用於處理訂單簿、發送通知、管理 WebSocket 連接和執行交易的方法。

### 構造函數：`__init__`

構造函數初始化了多個類屬性和對象，包括：
   - `self.bm1`：`BinanceSocketManager` 的實例，用於管理 WebSocket 連接。
   - `self.ace`：與 ACE 交易所交互的 API 對象。
   - 配置參數：`config` 和 `mm_config`。
   - `line_notify_token`：用於發送 LINE 通知的令牌。

### 方法：`need_to_del_list()`

- 一個異步方法，從 ACE 交易所獲取未完成訂單，並將狀態為待定（狀態為 0 或 1）的訂單填充到 `self.fast_del_list`。

### 方法：`send_line_notify(message)`

- 該方法使用提供的令牌向 LINE Notify 帳戶發送通知。它向 LINE Notify API 發送帶有消息內容的 `POST` 請求。

### 方法：`update_orderbook(symbol)`

- 一個異步方法，通過連接到 Binance 的 WebSocket 更新訂單簿。
- 該方法創建了一個 WebSocket 連接，以接收指定交易對的實時深度數據（`bids` 和 `asks`）。
- 在 WebSocket 循環中：
  - 檢查日期是否變更，如果變更則重新配置日誌。
  - 接收 WebSocket 響應並更新買賣價格。
  - 如果滿足某些條件（例如價格有顯著變動），它會觸發 `ace_trades()` 方法來在 ACE 上下單。
  - 處理異常，如 `asyncio.QueueFull`，通過重新啟動 WebSocket 連接來應對。

### 方法：`restart_websocket(symbol)`

- 重新啟動指定交易對的 WebSocket 連接。如果出現任何錯誤或 WebSocket 隊列已滿，則重新啟動。

### 方法：`ace_trades()`

- 這個異步方法是機器人的核心交易邏輯。它根據 Binance 的訂單簿數據在 ACE 交易所下單。
- 涉及的步驟：
  - 獲取 Binance 當前的訂單簿，並相應地更新 ACE 的訂單簿。
  - 獲取 USDT/TWD 的最優匯率（`twd_rate_bid`、`twd_rate_ask`）。
  - 計算初始買賣價格和數量，並創建批量提交這些訂單的任務。
  - 使用配置中定義的參數，為多個級別（買入和賣出）設置動態訂單。
  - 使用 `submit_batch_order` 將批量訂單提交到 ACE。
  - 如果有需要取消的開倉訂單，則批量處理取消訂單和單獨取消訂單。
  - 檢查在獲取未完成訂單過程中是否有任何錯誤或異常並適當處理。

### 方法：`execute()`

- 這是一個無限循環，持續調用 `update_orderbook()` 來保持訂單簿更新並根據實時數據觸發交易決策。

## 總結

該腳本是一個先進的做市機器人，執行以下任務：

- 連接到 Binance WebSocket 以接收實時深度數據。
- 處理數據並決定是否需要在 ACE 交易所下單或取消訂單。
- 使用動態訂單策略，隨機決定訂單大小和級別以減少可預測性。
- 結合錯誤處理和日誌記錄，確保運行順利和便於調試。


# 主程式解釋

這段 Python 腳本是做市機器人的主程式，負責初始化配置、清理未完成訂單、啟動做市操作，並處理異常情況。

## 關鍵組件

1. **導入模塊和配置**：
   - 腳本從不同的文件中導入了配置和模塊，包括 `BinanceConfig`、`MMaker`、`TokenConfig`。還使用了 `requests` 和 `traceback` 來處理 HTTP 請求和錯誤追蹤。

2. **更改工作目錄和設置路徑**：
   - 使用 `os.chdir(sys.path[0])` 將工作目錄更改為腳本所在目錄，並將 `'./module'` 路徑添加到 `sys.path` 以確保可以導入相關的自定義模塊。

### 函數：`send_line_notify(token, message)`

- 用於發送 LINE Notify 通知的函數。
- 接受 LINE Notify 的令牌和消息作為參數，然後使用 `requests.post()` 方法向 LINE Notify API 發送 `POST` 請求。

### 函數：`deleAceMaker(aceapi, acesymbol)`

- 異步函數，負責刪除 ACE 交易所中指定交易對的所有未完成訂單。
- 首先調用 `aceapi.get_open_orders(acesymbol)` 獲取未完成訂單列表。
- 如果有未完成訂單，會將它們的訂單編號添加到 `del_list` 列表中。
- 使用 `aceapi.cancel_batch_orders(del_list)` 批量取消所有未完成訂單。如果批量取消失敗，則逐個取消訂單。

### 函數：`main(binancesymbol, acesymbol)`

- 異步主函數，負責初始化做市機器人，並處理做市過程中的異常情況。
- 主要步驟：
  1. 讀取做市配置文件 `mm_config.ini`。
  2. 使用 `AsyncClient.create()` 創建 Binance 客戶端實例。
  3. 創建 ACE 交易所的 API 客戶端 `Spot`，並指定為測試網模式 (`mode='testnet'`)。
  4. 調用 `deleAceMaker(ace, acesymbol)` 函數刪除所有未完成的訂單，以確保造市操作開始前的清潔狀態。
  5. 創建 `MMaker` 類的實例 `maker`，並初始化做市機器人。
  6. 調用 `maker.execute()` 開始造市操作。
  7. 在異常情況下（`Exception`），記錄異常信息並使用 `send_line_notify()` 發送 LINE 通知。同時關閉 Binance 客戶端連接並刪除未完成訂單。
  8. 在手動中斷（`KeyboardInterrupt`）的情況下，關閉 Binance 客戶端連接並刪除未完成訂單。

### 主函數入口

- `if __name__ == '__main__':`：該部分定義了腳本的主入口點。
- 使用 `argparse` 來解析命令行參數，這些參數用於指定 Binance 和 ACE 的交易對符號。
- 使用 `asyncio.run(main(args.binance_symbol, args.ace_symbol))` 調用主函數，並傳遞解析的參數。

# 自成交程式解釋

這個 Python 腳本是一個自成交（Self-Trading）機器人，用於根據 Binance 和 ACE 交易所的訂單簿數據執行自動化交易策略。該腳本利用 `asyncio` 進行異步編程，以實現高效的交易執行和資金管理。

## 關鍵組件

1. **導入模塊和依賴項**：
   - 腳本導入了多個標準 Python 庫（如 `asyncio`、`json`、`logging` 等）以及第三方庫（如 `BinanceSocketManager` 和 `Oapi`），用於處理 Binance WebSocket、ACE API 和 Redis 操作等。

2. **日誌配置函數：`configure_logging(symbol)`**：
   - 該函數配置日誌輸出到文件和控制台。它基於當前日期創建日誌目錄，並將日誌記錄保存到文件中（例如 `selftrader.log`），同時也輸出到控制台（`stdout`）。

## 類別：`SelfTrader`

`SelfTrader` 類封裝了自成交機器人的核心功能。該類包括用於更新訂單簿、執行中價交易、管理交易和訂單取消的方法。

### 构造函数：`__init__`

构造函数初始化多个类属性和对象，包括：
- `self.socketbm`: BinanceSocketManager 实例，用于管理 WebSocket 连接。
- `self.tradeebm`: Binance API 实例，用于实际交易。
- `self.ace`: ACE 交易所的 API 客户端对象。
- `self.oapi`: `Oapi` 实例，用于通过 ACE 的 API 获取订单簿数据。
- `self.mm_config` 和 `self.config`: 用于管理交易配置。
- `self.trades_amount` 和 `self.sleep_time`: 用于跟踪交易数量和控制交易的睡眠时间。

### 方法：`Update_orderbook(symbol)`

- 一个异步方法，负责更新 Binance 交易对的订单簿。
- 创建一个 WebSocket 连接来接收指定交易对的实时交易数据。
- 内部循环中：
  - 检查日期是否改变，如果改变则重新配置日志。
  - 根据 WebSocket 响应计算累积交易量（`self.cum_qty`）。
  - 如果累积交易量达到配置的阈值，则调用 `self_midtrader()` 执行中价交易策略，并重置累积交易量。
  - 捕获任何异常并抛出。

### 方法：`self_midtrader()`

- 负责执行中价交易（mid-price trading）策略。
- 从 ACE 的 API 获取当前交易对的订单簿（`ab` 和 `aa`）。
- 计算买卖中价 `mid_price`，并随机生成交易数量 `amount`。
- 创建买卖订单，利用对冲映射（`HEDGE_MAPPING`）同时下反向订单。
- 如果订单成功提交，追加到 `self.del_list` 列表中。
- 提交订单后，通过 `cancel_batch_orders` 方法批量取消订单。

### 方法：`self_trader()`

- 负责执行买入和卖出策略的核心逻辑。
- 根据 ACE 订单簿的买一和卖一价格，随机生成订单价格和数量。
- 判断价差是否满足条件，如果是，则执行买入或卖出的策略。
- 同时提交反向对冲订单，以实现对冲交易。
- 交易执行后，取消所有未成交订单。

### 方法：`execute()`

- 主执行方法，启动自成交策略。
- 在一个无限循环中，启动 `Update_orderbook()` 任务并等待其完成。
- 捕获并处理任何异常，取消正在运行的任务并重新启动。