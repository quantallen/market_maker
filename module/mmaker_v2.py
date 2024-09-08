import asyncio
import json
import time
import sys
import socket
from math import floor
from functools import partial
from datetime import timedelta, datetime
from decimal import Decimal
import ssl
import traceback
from binance.streams import BinanceSocketManager
import requests
import random
import os 
import logging
# Function to configure logging
def configure_logging(symbol):
    global log_filename, log_folder, date_folder
    base_log_folder = "/data/logs"
    date_folder = datetime.now().strftime('%Y-%m-%d')
    log_folder = os.path.join(base_log_folder, date_folder)
    os.makedirs(log_folder, exist_ok=True)
    symbol_folder = os.path.join(log_folder,symbol)
    os.makedirs(symbol_folder, exist_ok=True)
    log_filename = f"{symbol_folder}/mmaker.log"
    logging.basicConfig(
        level=logging.INFO,  # Adjust the level according to your needs (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename),  # Log to a file in the date folder
            logging.StreamHandler(sys.stdout)   # Also log to stdout
        ]
    )


HEDGE_MAPPING = {"BUY": "SELL", "SELL": "BUY"}

class MMaker:
    orderbook = {}
    trades = {}
    data = None
    current_bid1 = current_ask1 = 0
    new_bid1 = new_ask1 = 0
    response = None
    current_date = None
    def __init__(self, bianceasyncapi, api2, config, mm_config, line_notify_token):
        self.bm1 = BinanceSocketManager(bianceasyncapi)
        self.ace = api2
        self.config = config
        self.mm_config = mm_config
        self.line_notify_token = line_notify_token
        self.spread_prices = None
        self.remember_quotes = None 
        self.count = 0
        self.fast_del_list = []#= self.need_to_del_list()
        self.del_list = []
        self.first = True
        self.success = True
        self.change = False
        self.slow_ob_check = True
    
    async def need_to_del_list(self):
        ndl = self.ace.get_open_orders(self.config.ACE_SYMBOL)
        if len(ndl['attachment']) != 0 :
            for d in ndl['attachment']:
                if (d['status'] == 0 or d['status'] == 1) :
                    self.fast_del_list.append(d['orderNo'])
        
    def send_line_notify(self, message):
        url = "https://notify-api.line.me/api/notify"
        headers = {
            "Authorization": f"Bearer {self.line_notify_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "message": message
        }
        requests.post(url, headers=headers, data=data)

    def send_error_notification(self, symbol, detailed_message):
        """Send an error notification to Line Notify with a detailed message."""
        message = f"發生錯誤於交易對 {symbol}:\n{detailed_message}"
        self.send_line_notify(message)
    async def update_orderbook(self, symbol):
        try:
            ws = self.bm1.depth_socket(symbol, depth=5, interval=100)
            async with ws as wscm:
                while True:
                    # Check if the date has changed and reconfigure logging if it has
                    new_date = datetime.now().strftime('%Y-%m-%d')
                    if new_date != self.current_date:
                        self.current_date = new_date
                        logging.getLogger().handlers.clear()  # Clear existing handlers
                        configure_logging(symbol)
                    start = time.time()
                    try:
                        resp = await wscm.recv()
                        self.response = resp
                        #print(resp)
                        #print("buffer size : ", wscm._queue.qsize())
                        if 'bids' in resp and 'asks' in resp:
                            self.new_bid1 = float(resp['bids'][0][0])
                            self.new_ask1 = float(resp['asks'][0][0])
                            
                            if symbol not in self.orderbook:
                                self.orderbook[symbol] = {'bids': resp['bids'], 'asks': resp['asks']}
                            else:
                                self.current_bid1 = float(self.orderbook[symbol]['bids'][0][0])
                                self.current_ask1 = float(self.orderbook[symbol]['asks'][0][0])
                                
                                if self.first or abs(self.new_bid1 - self.current_bid1) / self.current_bid1 >= self.config.SPREAD_DIFF or abs(self.new_ask1 - self.current_ask1) / self.current_ask1 >= self.config.SPREAD_DIFF:
                                    #若第一次鋪單or 當幣安新價格跟源價格比差了設定之bps則變動Orderbook 
                                    self.first = False
                                    await self.ace_trades()
                    except asyncio.QueueFull as e:
                        error_message = f"Queue is full, restarting the WebSocket connection: {str(e)}"
                        print(error_message)
                        logging.info(error_message)
                        self.send_error_notification(symbol, error_message)
                        break
                    except Exception as e:
                        error_message = f"Error processing WebSocket data: {str(e)}\n{traceback.format_exc()}"
                        print(error_message)
                        logging.info(error_message)
                        self.send_error_notification(symbol, error_message)
                        await asyncio.sleep(1)  # Add delay to prevent rapid restarts

                    end = time.time()
                    #print("time to do all thing :", end - start)
                    await asyncio.sleep(0.01)
        except Exception as e:
            print(f"WebSocket error: {e}")
            #await self.restart_websocket(symbol)

    async def restart_websocket(self, symbol):
        """Restart the WebSocket connection."""
        await self.bm1.close()
        print("Reconnecting WebSocket...")
        await asyncio.sleep(5)  # Add a delay before reconnecting
        await self.update_orderbook(symbol)
        
    async def ace_trades(self):
        if not self.orderbook:
            return
        
        print("Executing ACE trades")
        self.orderbook[self.config._SYMBOL] = {'bids': self.response['bids'], 'asks': self.response['asks']}
        order_tasks = []
        _, _, twd_rate_bid, twd_rate_ask = await self.ace.optimal_exchange_rate() # 提取USDT/TWD的價格
        min_amount = float(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['min_amount']) # 提取各幣種的最小交易單位
        buy_levels = 20  # random.randint(10, 20)
        sell_levels = 20  # random.randint(10, 20)

        # Process buy orders
        for i in range(1):
            first_buy_price = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][0][0])) * Decimal(twd_rate_bid) * Decimal(1 - self.config.FEE) # 幣安價格 * TWD價格 * 扣除手續費0.1%後預計賺的bps
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][0][1])) * Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['firstbuysizefactor']) #/ random.randint(10,1000) # 畢安顆數的變化
            max_size = Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['firsttotalvalue']) / first_buy_price / Decimal(random.uniform(1.0,10.0)) # 第一層
            size = min(original_size, max_size) # 比較兩者size誰比較小
            
            if size < Decimal(min_amount):
                size = Decimal(min_amount) * Decimal(random.uniform(1.00, 20.00)) # 若size 小於最小下單單位量則要從最小下單單位量向上提升
            price = first_buy_price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["BUY", price, size])  
        
        # Process sell orders
        for i in range(1):
            first_sell_price = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][0][0])) * Decimal(twd_rate_ask) * Decimal(1 + self.config.FEE)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][0][1])) * Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['firstsellsizefactor'])# / random.randint(10,1000)
            max_size = Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['firsttotalvalue']) / first_sell_price / Decimal(random.uniform(1.0,10.0))
            size = min(original_size, max_size)
            
            if size < Decimal(min_amount):
                size = Decimal(min_amount) * Decimal(random.uniform(1.00, 20.00))
            price = first_sell_price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["SELL", price, size])

        # Additional buy levels
        for i in range(1, 5):
            price = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][i][0])) * Decimal(twd_rate_bid) * Decimal(1 - i * self.config.FEE)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][i][1])) * Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['firstbuysizefactor']) #/ random.randint(10,1000)
            max_size = Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['anothertotalvalue']) / price #/ Decimal(random.uniform(1.0,100.0))
            size = min(original_size, max_size)
            if size < Decimal(min_amount):
                size = Decimal(min_amount) * Decimal(random.uniform(1.00, 20.00))
            price = price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["BUY", price, size])                 
        
        # Additional sell levels
        for i in range(1, 5):
            price = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][i][0])) * Decimal(twd_rate_ask) * Decimal(1 + i * self.config.FEE)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][i][1])) * Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['firstsellsizefactor']) #/ random.randint(10,1000)
            max_size = Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['anothertotalvalue']) / price #/ Decimal(random.uniform(1.0,100.0))
            size = min(original_size, max_size)
            
            if size < Decimal(min_amount):
                size = Decimal(min_amount) * Decimal(random.uniform(1.00, 20.00))
            price = price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["SELL", price, size])
        
        # Dynamic buy orders
        for i in range(1, buy_levels):
            price = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][4][0])) * Decimal(twd_rate_bid) * Decimal(1 - self.config.FEE) * Decimal(1 - i * self.config.DECLINE_FACTOR)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][4][1])) * Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['firstbuysizefactor']) / random.randint(10,1000)
            max_size = Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['fartotalvalue']) / price #/ Decimal(random.uniform(1.0,100.0))
            size = min(original_size, max_size)
            if size < Decimal(min_amount):
                size = Decimal(min_amount) * Decimal(random.uniform(1.00, 20.00))
            price = price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["BUY", price, size])                 

        # Dynamic sell orders
        for i in range(1, sell_levels):
            price = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][4][0])) * Decimal(twd_rate_ask) * Decimal(1 + self.config.FEE) * Decimal(1 + i * self.config.DECLINE_FACTOR)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][4][1])) * Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['firstsellsizefactor']) / random.randint(10,1000)
            max_size = Decimal(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['fartotalvalue']) / price#/Decimal(random.uniform(1.0,100.0))
            size = min(original_size, max_size)
            if size < Decimal(min_amount):
                size = Decimal(min_amount) * Decimal(random.uniform(1.00, 20.00))
            price = price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["SELL", price, size])
        r = await self.ace.submit_batch_order(symbol=self.config.ACE_SYMBOL, orderinfo=order_tasks, isMakerOnly=False)
        logging.info(r)
        # Handle order cancellations
        if self.fast_del_list: # 有需要刪除的del_list 則用cancel_batch_orders下單, 雙重保險再刪一次
            resp_c = await self.ace.cancel_batch_orders(self.fast_del_list)
            print(resp_c)
            for d in resp_c['attachment']:
                if d['code'] != 0:
                    await self.ace.cancel_order(d['orderNo'])
            for d in self.fast_del_list :
                await self.ace.cancel_order(d)
            
            # double_check = self.ace.get_open_orders(self.config.ACE_SYMBOL)
            # if len(double_check['attachment']) != 0 :
            #     for d in double_check['attachment']:
            #         if (d['status'] == 0 or d['status'] == 1) and d['orderNo'] in self.fast_del_list :
            #             r = await self.ace.cancel_order(d['orderNo'])
            self.fast_del_list = []
        print(order_tasks)
        logging.info(str(order_tasks) + str(len(order_tasks)))
        # Uncomment the following code when ready to execute orders
        #self.need_to_del_list()
        try :
            ndl = await self.ace.get_open_orders(self.config.ACE_SYMBOL) # 把所有開倉點撈出來,免得有漏,並且記錄到list中
            if 'Error' in str(ndl):
                logging.error("Server Error encountered. Terminating program and cancelling all orders.")
                # Cancel all open orders immediately
                for nd in self.fast_del_list:
                    await self.ace.cancel_order(nd)
                self.send_error_notification(self.config.ACE_SYMBOL, "Program terminated due to server error.")
                sys.exit("Program terminated due to server error.")
            if len(ndl['attachment']) != 0: 
                for nd in ndl['attachment']:
                    self.fast_del_list.append(nd['orderNo'])
            logging.info(str(self.fast_del_list) + str(len(self.fast_del_list)))
        
        except Exception as e :
            logging.error(f"Error retrieving open orders: {e}")
            print(f"Error retrieving open orders: {e}")
            sys.exit("Program terminated due to an unexpected error while fetching open orders.")
        # for t in r['attachment']:
        #     if t['errorCode'] == 200:
        #         self.fast_del_list.append(t['orderNo'])
        # print(r)
        await asyncio.sleep(0.01)
    async def execute(self):
        while True:
            await self.update_orderbook(self.config._SYMBOL)
