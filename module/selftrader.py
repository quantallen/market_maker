import asyncio
import json
import time
import logging
from math import floor
from datetime import timedelta, datetime
from decimal import Decimal
import asyncio
import traceback
import random
import math
import random
HEDGE_MAPPING = {"BUY" : "SELL", "SELL": "BUY"}
from module.ACEREST_v2 import Oapi
import redis
from binance.streams import BinanceSocketManager
import os 
import sys
import requests
def configure_logging(symbol):
    global log_filename, log_folder, date_folder
    base_log_folder = "/data/logs"
    date_folder = datetime.now().strftime('%Y-%m-%d')
    log_folder = os.path.join(base_log_folder, date_folder)
    os.makedirs(log_folder, exist_ok=True)
    symbol_folder = os.path.join(log_folder,symbol)
    os.makedirs(symbol_folder, exist_ok=True)
    log_filename = f"{symbol_folder}/selftrader.log"
    logging.basicConfig(
        level=logging.INFO,  # Adjust the level according to your needs (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename),  # Log to a file in the date folder
            logging.StreamHandler(sys.stdout)   # Also log to stdout
        ]
    )

class SelfTrader:
    orderbook = {}
    trades = {}
    cum_qty = 0
    current_date = None
    data = None
    def __init__(self, bianceasyncapi, binanceapi, api2, config,mm_config, line_notify_token):
        logging.getLogger('').handlers = []
        self.socketbm = BinanceSocketManager(bianceasyncapi)
        self.tradeebm = binanceapi
        self.ace = api2
        self.config = config
        self.del_list = []
        self.oapi = Oapi()
        self.mm_config = mm_config
        self.trades_amount = 0
        self.sleep_time = 0
        self.ace_symbol = self.config.ACE_SYMBOL.replace("_","")
        self.line_notify_token = line_notify_token
    def send_line_notify(self, message):
        """Send a message to Line Notify."""
        url = "https://notify-api.line.me/api/notify"
        headers = {
            "Authorization": f"Bearer {self.line_notify_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {"message": message}
        requests.post(url, headers=headers, data=data)

    def send_error_notification(self, symbol, detailed_message):
        """Send an error notification to Line Notify with a detailed message."""
        message = f"發生錯誤於交易對 {symbol}:\n{detailed_message}"
        self.send_line_notify(message)
    async def Update_orderbook(self, symbol):
        try :
            ws = self.socketbm.trade_socket(symbol)
            async with ws as wscm:
                while True:
                    resp = await wscm.recv()                
                    # Check if the date has changed and reconfigure logging if it has
                    new_date = datetime.now().strftime('%Y-%m-%d')
                    if new_date != self.current_date:
                        self.current_date = new_date
                        logging.getLogger().handlers.clear()  # Clear existing handlers
                        configure_logging(symbol)  # Reconfigure logging for the new date
                    #print("buffer size : ", wscm._queue.qsize())
                    #print(resp)
                    self.cum_qty += float(resp['q'])
                    if self.cum_qty >= float(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['cum_qty']):
                        await self.self_midtrader()
                        self.cum_qty = 0
                    #await asyncio.sleep(0.001)
        except Exception as e:
            error_message = f"Error in Update_orderbook for symbol {self.config.ACE_SYMBOL}: {str(e)}\n{traceback.format_exc()}"
            print(error_message)
            logging.info(error_message)
            self.send_error_notification(symbol, error_message)
    async def self_midtrader(self):
        order_task = []
        self.del_list = []
        ab,aa = await self.oapi.get_orderbooks(self.config.ACE_SYMBOL)
        amount = random.uniform(1.00, 15.00) * float(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['min_amount'])
        side = "BUY" if random.randint(1,101) % 2 == 0 else "SELL" 
        if Decimal(ab) + 10 * self.config.PRICE_PRECISION <= Decimal(aa) :    
            mid_price = (ab+ aa) / 2 #* random.uniform(1.00000, 1.00010)
            print(ab,aa)
            print(mid_price)
            mid_price = Decimal(mid_price).quantize(self.config.PRICE_PRECISION)
            print("中價 : " , mid_price)
            amount = Decimal(amount).quantize(self.config.SIZE_PRECISION)
            order_task.append([side,mid_price,amount])
            order_task.append([HEDGE_MAPPING[side],mid_price,amount])
            logging.info(order_task)
            r = await self.ace.submit_order(symbol= self.config.ACE_SYMBOL ,side = side, price= mid_price ,amount= amount, type_= 1)
            self.del_list.append(r['attachment'])
            r = await self.ace.submit_order(symbol= self.config.ACE_SYMBOL ,side = HEDGE_MAPPING[side], price= mid_price ,amount= amount,type_= 1)
            self.del_list.append(r['attachment'])
        else :
            logging.info('spread不夠空間畫造市')
        resp_c = await self.ace.cancel_batch_orders(self.del_list)
        print(resp_c)
    async def self_trader(self):
        order_task = []
        self.del_list = []
        ab,aa = await self.oapi.get_orderbooks(self.config.ACE_SYMBOL)
        amount = random.uniform(1.00, 15.00) * float(self.mm_config[self.config.ACE_SYMBOL.replace('_', '')]['min_amount'])
        side = "BUY" if random.randint(1,101) % 2 == 0 else "SELL" 
        if ab * (1 + 1.5 * self.config.FEE) <= aa :
            if side == "BUY":
                buy_price = ab + (self.config.PRICE_PRECISION * random.uniform(1.00, 50.00))
                buy_price = Decimal(buy_price).quantize(self.config.PRICE_PRECISION)
                print("放入買價, 比最佳買一高一點 ", buy_price)
                amount = Decimal(amount).quantize(self.config.SIZE_PRECISION)
                order_task.append([side,buy_price,amount])
                order_task.append([HEDGE_MAPPING[side],buy_price,amount])
                print(order_task)
                r = await self.ace.submit_order(symbol= self.config.ACE_SYMBOL ,side = side, price= buy_price ,amount= amount, type_= 1)
                self.del_list.append(r['attachment'])
                r = await self.ace.submit_order(symbol= self.config.ACE_SYMBOL ,side = HEDGE_MAPPING[side], price= buy_price ,amount= amount,type_= 1)
                self.del_list.append(r['attachment'])
            elif side == "SELL":
                sell_price = aa - (self.config.PRICE_PRECISION * random.uniform(1.00, 50.00))
                sell_price = Decimal(sell_price).quantize(self.config.PRICE_PRECISION)
                print("放入賣價, 比最佳賣一低一點 ", sell_price)
                amount = Decimal(amount).quantize(self.config.SIZE_PRECISION)
                order_task.append([side,sell_price,amount])
                order_task.append([HEDGE_MAPPING[side],sell_price,amount])
                print(order_task)
                r = await self.ace.submit_order(symbol= self.config.ACE_SYMBOL ,side = side, price= sell_price ,amount= amount, type_= 1)
                self.del_list.append(r['attachment'])
                r = await self.ace.submit_order(symbol= self.config.ACE_SYMBOL ,side = HEDGE_MAPPING[side], price= sell_price ,amount= amount,type_= 1)
                self.del_list.append(r['attachment'])
            #time.sleep(0.001)
            #self.log.info("need del list : {}".format(self.del_list))   
            
            #self.log.info("delete resp_c : {}".format(resp_c)) 
        elif ab * (1 + self.config.FEE / 2) >= aa :
            # side = "BUY" if random.randint(1,101) % 2 == 0 else "SELL"
            # if amount < float(self.mm_config[self.ace_symbol]['min_amount']):
            #     amount = float(self.mm_config[self.ace_symbol]['min_amount']) * random.uniform(1, 10)
            # elif amount > float(self.mm_config[self.ace_symbol]['max_amount']):
            #     amount = float(self.mm_config[self.ace_symbol]['max_amount']) * self.config.AMOUNT_RATIO 
            print(ab,aa)
            mid_price = (ab+ aa) / 2 * random.uniform(1.00000, 1.00010)
            mid_price = Decimal(mid_price).quantize(self.config.PRICE_PRECISION)
            print("中價 : " , mid_price)
            amount = Decimal(amount).quantize(self.config.SIZE_PRECISION)
            order_task.append([side,mid_price,amount])
            order_task.append([HEDGE_MAPPING[side],mid_price,amount])
            print(order_task)
            r = await self.ace.submit_order(symbol= self.config.ACE_SYMBOL ,side = side, price= mid_price ,amount= amount, type_= 1)
            self.del_list.append(r['attachment'])
            r = await self.ace.submit_order(symbol= self.config.ACE_SYMBOL ,side = HEDGE_MAPPING[side], price= mid_price ,amount= amount,type_= 1)
            self.del_list.append(r['attachment'])
            #time.sleep(0.001)
        else :
            print("now ace price :",ab,aa)
        resp_c = await self.ace.cancel_batch_orders(self.del_list)
        print(resp_c)
        # self.sleep_time = random.uniform(25, 100)
        # print("sleep time :",self.sleep_time)
        # time.sleep(self.sleep_time) 
            
    async def execute(self):
        while True:
            try:
                print("loggin")
                self_trade = asyncio.create_task(self.Update_orderbook(self.config._SYMBOL))
                await asyncio.gather(
                    self_trade
                )
            except Exception as e:
                error_message = f"SELF TRADE ERROR for {self.config.ACE_SYMBOL}: {str(e)}\n{traceback.format_exc()}"
                print(error_message)
                logging.info(error_message)
                self.send_error_notification(self.config.ACE_SYMBOL, error_message)
                self_trade.cancel()
                continue
 