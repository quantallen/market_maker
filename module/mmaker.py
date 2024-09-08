import asyncio
import json
import time
import sys
import socket
from math import floor
from functools import partial
from datetime import timedelta, datetime
from decimal import Decimal
import asyncio, ssl
import traceback
from binance.streams import BinanceSocketManager
import requests  # Import requests for sending notifications
import random
HEDGE_MAPPING = {"BUY" : "SELL", "SELL": "BUY"}

class MMaker:
    orderbook = {}
    trades = {}
    data = None
    
    def __init__(self, bianceasyncapi, api2, config, mm_config, TokenConfig, line_notify_token):
        self.bm1 = BinanceSocketManager(bianceasyncapi)
        self.ace = api2
        self.config = config
        self.mm_config = mm_config
        self.token_config = TokenConfig
        self.line_notify_token = line_notify_token  # LineNotify token
        self.spread_prices = None
        self.remember_quotos = None 
        self.count = 0
        self.fast_del_list = []
        self.del_list = []
        self.first = True
        self.success = True
        self.change = False
        self.slow_ob_check = True
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

    async def Update_orderbook(self, symbol):
        ws = self.bm1.depth_socket(symbol, depth=5, interval=100)
        trade_queue = asyncio.Queue()
        async with ws as wscm:
            while True:
                start = time.time()
                resp = await wscm.recv()
                
                print("buffer size : ", wscm._queue.qsize())
                if 'bids' in resp and 'asks' in resp:
                    new_bid1 = float(resp['bids'][0][0])
                    new_ask1 = float(resp['asks'][0][0])
                    
                    if symbol not in self.orderbook:
                        self.orderbook[symbol] = {'bids': resp['bids'], 'asks': resp['asks']}
                    else:
                        current_bid1 = float(self.orderbook[symbol]['bids'][0][0])
                        current_ask1 = float(self.orderbook[symbol]['asks'][0][0])                        
                        if self.first:
                            await trade_queue.put(self.ace_trades())
                            self.first = False

                        if abs(new_bid1 - current_bid1) / current_bid1 >= self.config.SPREAD_DIFF or abs(new_ask1 - current_ask1) / current_ask1 >= self.config.SPREAD_DIFF:
                            self.orderbook[symbol] = {'bids': resp['bids'], 'asks': resp['asks']}
                            await trade_queue.put(self.ace_trades())
                # Ensure ace_trades are processed asynchronously
                if not trade_queue.empty():
                    trade_task = await trade_queue.get()
                    asyncio.create_task(trade_task)
                print(trade_queue)
                #print("recent orderbook : ", self.orderbook)
                end = time.time()
                print("time to do all thing :", end - start)
                await asyncio.sleep(0.1)

    async def ace_trades(self):
        order_tasks = []
        _,_,twd_rate_bid,twd_rate_ask = await self.ace.optimal_exchange_rate()
        min_amount = float(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['min_amount'])
        # Randomly decide the number of levels to process for buy/sell orders
        buy_levels = random.randint(10, 20)
        sell_levels = random.randint(10, 20)

        for i in range(1):
            first_buy_price = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][0][0])) * Decimal(twd_rate_bid) * Decimal(1 - self.config.FEE)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][0][1])) * Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['firstbuysizefactor'])
            max_size = Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['firsttotalvalue']) / first_buy_price
            size = min(original_size, max_size)
            
            if size < Decimal(min_amount):
                size = Decimal(min_amount)
            price = first_buy_price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["BUY", price, size])  
        
        for i in range(1):
            first_sell_price = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][0][0])) * Decimal(twd_rate_ask) * Decimal(1 + self.config.FEE)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][0][1])) * Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['firstsellsizefactor'])
            max_size = Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['firsttotalvalue']) / first_sell_price
            size = min(original_size, max_size)
            
            if size < Decimal(min_amount):
                size = Decimal(min_amount)
            price = first_sell_price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["SELL", price, size])

        for i in range(1, 5):
            price = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][i][0])) * Decimal(twd_rate_bid) * Decimal(1 - i * self.config.FEE)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][0][1])) * Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['firstbuysizefactor'])
            max_size = Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['anothertotalvalue']) / price
            size = min(original_size, max_size)
            if size < Decimal(min_amount):
                size = Decimal(min_amount)
            price = price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["BUY", price, size])                 
        for i in range(1, 5):
            price = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][i][0])) * Decimal(twd_rate_ask) * Decimal(1 + i * self.config.FEE)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][0][1])) * Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['firstsellsizefactor'])
            max_size = Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['anothertotalvalue']) / price
            size = min(original_size, max_size)
            
            if size < Decimal(min_amount):
                size = Decimal(min_amount)
            price = price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["SELL", price, size])
        
        for i in range(1, buy_levels):
            price = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][4][0])) * Decimal(twd_rate_bid) * Decimal(1 - self.config.FEE) * Decimal(1 - i * self.DECLINE_FACTOR)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['bids'][0][1])) * Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['firstbuysizefactor'])
            max_size = Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['anothertotalvalue']) / price
            size = min(original_size, max_size)
            
            if size < Decimal(min_amount):
                size = Decimal(min_amount)
            price = price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["BUY", price, size])                 

        for i in range(1, sell_levels):
            price = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][4][0])) * Decimal(twd_rate_ask) * Decimal(1 + self.config.FEE) * Decimal(1 + i * self.DECLINE_FACTOR)
            original_size = Decimal(float(self.orderbook[self.config._SYMBOL]['asks'][0][1])) * Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['firstsellsizefactor'])
            max_size = Decimal(self.token_config[self.config.ACE_SYMBOL.replace('_', '')]['anothertotalvalue']) / price
            size = min(original_size, max_size)
            if size < Decimal(min_amount):
                size = Decimal(min_amount)
            price = price.quantize(self.config.PRICE_PRECISION)
            size = size.quantize(self.config.SIZE_PRECISION)
            order_tasks.append(["SELL", price, size])
        
        print(order_tasks)
        #Uncomment the following code when ready to execute orders
        r = await self.ace.submit_batch_order(symbol=self.config.ACE_SYMBOL, orderinfo=order_tasks, isMakerOnly=False)
        print(r)
        if self.fast_del_list:
            resp_c = await self.ace.cancel_batch_orders(self.fast_del_list)
            for d in resp_c['attachment']:
                if d['code'] == 2062:
                    await self.ace.cancel_order(d['orderNo'])
            self.fast_del_list = []
        for t in r['attachment']:
            if t['errorCode'] == 200:
                self.fast_del_list.append(t['orderNo'])
        await asyncio.sleep(0.01)

    async def execute(self):
        #notify_task = asyncio.create_task(self.notify_spread())
        while True:
            try:
                #print("logging")
                update_ob_ref = asyncio.create_task(self.Update_orderbook(self.config._SYMBOL))
                await asyncio.gather(
                    update_ob_ref,
                )            
            except Exception as e:
                print(traceback.format_exc())
                update_ob_ref.cancel()
                time.sleep(5)
                continue