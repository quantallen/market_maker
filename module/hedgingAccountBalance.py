import asyncio
import time
import logging
import sys
from datetime import timedelta, datetime,date
from decimal import Decimal, ROUND_HALF_UP,ROUND_DOWN
import traceback
from binance.streams import BinanceSocketManager
import os
from prettytable import PrettyTable
from requests import Session
#sys.path.append('/home/ubuntu/ace_maker_final')
import redis
import json
import pymysql

# Function to configure logging
def configure_logging(symbol):
    global log_filename, log_folder, date_folder
    base_log_folder = "/data/logs"
    date_folder = datetime.now().strftime('%Y-%m-%d')
    log_folder = os.path.join(base_log_folder, date_folder)
    os.makedirs(log_folder, exist_ok=True)
    symbol_folder = os.path.join(log_folder,symbol)
    os.makedirs(symbol_folder, exist_ok=True)
    log_filename = f"{symbol_folder}/hedge.log"
    logging.basicConfig(
        level=logging.INFO,  # Adjust the level according to your needs (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_filename),  # Log to a file in the date folder
            logging.StreamHandler(sys.stdout)   # Also log to stdout
        ]
    )

class Hedging:
    orderbook = {}
    trades = {}
    record_trade_ids = []
    data = None
    buy_price_ratio = 0.01
    sell_price_ratio = 0.01
    def __init__(self, bapi,api2,balance_config,db_config,hedge_config,ISTWD):
        self.bm1 = bapi
        self.ace = api2
        self.balance_config = balance_config
        print(self.balance_config)
        self.lock = asyncio.Lock()
        self.db_config = db_config
        self.hedge_config = hedge_config
        self.conn = pymysql.connect(**self.db_config)
        self.ISTWD = ISTWD
        self.table_name = 'hedging_table_TWD' if self.ISTWD == True else 'hedging_table'
    def log_to_db(self, data):
        try:
            with self.conn.cursor() as cursor:
                if self.ISTWD == True:
                    sql = """
                    INSERT INTO %s (time, binance_symbol, ace_symbol, side, Best_Price, symbol_quantity, USDT, TWD,  profit)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (
                        self.table_name,
                        data['time'], data['binance_symbol'], data['ace_symbol'], 
                        data['side'], data['Best_Price'] , data['symbol_quantity'], 
                        data['USDT'], data['TWD'], data['profit']
                    ))
                elif self.ISTWD == False:
                    sql = """
                    INSERT INTO %s (time, binance_symbol, ace_symbol, side, Best_Price, symbol_quantity, USDT,  profit)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (
                        self.table_name,
                        data['time'], data['binance_symbol'], data['ace_symbol'], 
                        data['side'], data['Best_Price'] , data['symbol_quantity'], 
                        data['USDT'], data['profit']
                    ))
            self.conn.commit()
        except:
            print('log to db error')
    async def hedging_trades_test(self):
        while True :
            try :
                try :
                    # ACE　Balance 
                    resp = await self.ace.account_balance(None)
                except :
                    time.sleep(2)
                    pass
                    # raise ValueError("get ACE balance wrong")
                try :
                    # Binance Balance
                    binance_balance = {}
                    binance_resp = await self.bm1.get_account()
                    for re in binance_resp['balances']:
                        symbol = re['asset']
                        free = re['free']
                        binance_balance[symbol] = free
                except :
                    raise ValueError("get Binance balance wrong")
                if resp :
                    Ticker = await self.bm1.get_all_tickers()
                    Ticker = {i['symbol']:i['price'] for i in Ticker}
                    Logs = []
                    for re in resp:
                        symbol = re['currencyName']
                        if symbol not in self.balance_config:
                            continue
                        if (symbol == 'USDT') or (symbol == 'TWD'):
                            continue
                        # print(datetime.now(),re)
                        Log = {}
                        Log['time'] = datetime.now()
                        Log['binance_symbol'] = symbol+'USDT'
                        Log['ace_symbol'] = symbol+'_TWD' if self.ISTWD == True else symbol+'_USDT'
                        ace_amount = Decimal(str(re['amount']))
                        binance_amount = 0 #Decimal(str(binance_resp[symbol]))
                        balance = ace_amount + binance_amount
                        initial_balance = Decimal(str(self.balance_config[symbol]['Total'])) 
                        minQty = Decimal(str(self.hedge_config[symbol]['minQty']))
                        minNotional = Decimal(str(self.hedge_config[symbol]['minNotional']))
                        print(datetime.now(),re,initial_balance,binance_balance[symbol])
                        
                        if initial_balance > balance: # 幣變少 別人在ACE買幣 , 我們得去BINANCE買幣
                            diff = Decimal(str(initial_balance - balance))
                            print(balance,initial_balance,diff)

                            Notional = diff * Decimal(str(Ticker[symbol+'USDT']))
                            if diff < minQty:
                                print(datetime.now(),symbol + "diff "+str(diff)+" smaller than minQty")
                                continue
                            elif Notional < minNotional:
                                print(datetime.now(),symbol + "Notional "+str(Notional)+" smaller than minQty")
                                continue
                            else:
                                #少幣，幣安買幣 少U，ACE賣台幣拿U
                                quantity = diff.quantize(minQty, ROUND_DOWN)
                                Log['side'] = 'BUY'
                                Log['symbol_quantity'] = str(quantity)
                                print("binance market buy",quantity,diff,Notional)
                                try:
                                    order_resp = self.bm1.order_market_buy(
                                        symbol = (symbol + 'USDT'),
                                        quantity = quantity,
                                    )
                                except:
                                    print('Binance market buy error')
                                cum_qty = order_resp['cummulativeQuoteQty']
                                if self.ISTWD == True:
                                    try:
                                        r = await self.ace.submit_order('USDT_TWD', "BUY", 0, cum_qty,type_ = 2)
                                    except:
                                        print("ace buy usdt error")
                        elif initial_balance < balance: # 幣變多, 用戶在ACE賣幣,我們在ACE少台幣, 我們在BINANCE賣幣獲得U, 在ACE賣U獲得台幣
                            diff = Decimal(str(balance - initial_balance))
                            print(balance,initial_balance,diff)
                            Notional = diff * Decimal(str(Ticker[symbol+'USDT']))
                            if diff < minQty:
                                print(datetime.now(),symbol + "diff "+str(diff)+" smaller than minQty")
                                continue
                            elif Notional < minNotional:
                                print(datetime.now(),symbol + "Notional "+str(Notional)+" smaller than minQty")
                                continue
                            else:
                                #多幣，幣安賣幣，ACE賣U拿台幣
                                quantity = diff.quantize(minQty, ROUND_DOWN)
                                Log['side'] = 'SELL'
                                Log['symbol_quantity'] = str(quantity)
                                print("binance market sell",quantity,diff,Notional)
                                try:
                                    order_resp = self.bm1.order_market_sell(
                                        symbol = (symbol + 'USDT'),
                                        quantity = quantity
                                    )
                                except:
                                    print('Binance market sell error')
                                cum_qty = order_resp['cummulativeQuoteQty']
                                if self.ISTWD == True:
                                    try:
                                        r = await self.ace.submit_order('USDT_TWD', "SELL", 0, cum_qty,type_ = 2)
                                    except:
                                        print("ace sell usdt error")

                await asyncio.sleep(0.1)  
            except Exception as e:
                print(e)
                pass

    async def hedging_trades(self):
        while True :
            try :
                try :
                    # ACE　Balance 
                    resp = await self.ace.account_balance(None)
                except :
                    raise ValueError("get ACE balance wrong")
                
                try :
                    # Binance Balance
                    binance_balance = {}
                    binance_resp = await self.bm1.get_account()
                    for re in binance_resp['balances']:
                        symbol = re['asset']
                        free = re['free']
                        binance_balance[symbol] = free
                except :
                    raise ValueError("get Binance balance wrong")
                
                if resp :
                    Logs = []
                    for re in resp:
                        symbol = re['currencyName']
                        if symbol not in self.balance_config:
                            continue
                        if (symbol == 'USDT') or (symbol == 'TWD'):
                            continue
                        Log = {}
                        Log['time'] = datetime.now()
                        Log['binance_symbol'] = symbol+'USDT'
                        Log['ace_symbol'] = symbol+'_TWD' if self.ISTWD == True else symbol+'_USDT'
                        ace_amount = re['amount']
                        binance_amount = binance_resp[symbol]
                        balance = ace_amount + binance_amount
                        initial_balance = self.balance_config[symbol]['Total']
                        minQty = self.balance_config[symbol]['minQty']
                        if initial_balance > balance:
                            if  (initial_balance - balance) > minQty:
                                #少幣，幣安買幣，ACE賣台幣拿U
                                diff = initial_balance - balance
                                quantity = (diff//minQty) * minQty
                                Log['side'] = 'BUY'
                                Log['symbol_quantity'] = str(quantity)
                                try:
                                    order_resp = self.bm1.order_market_buy(
                                        symbol = (symbol + 'USDT'),
                                        quantity = quantity
                                    )
                                except:
                                    print('Binance market buy error')
                                cum_volume = 0
                                cum_qty = 0
                                for fill_data in order_resp["fills"]:
                                    cum_volume += float(fill_data['price']) * float(fill_data['qty'])
                                    cum_qty += float(fill_data['qty'])
                                Log['USDT'] = str(cum_volume)
                                if self.ISTWD == True:
                                    try:
                                        r = await self.ace.submit_order('USDT_TWD', "BUY", 0, cum_volume,type_ = 2)
                                    except:
                                        print("ace buy usdt error")
                        elif initial_balance < balance:
                            if  (balance - initial_balance) > minQty:
                                #多幣，幣安賣幣，ACE賣U拿台幣
                                diff = balance - initial_balance
                                quantity = (diff//minQty) * minQty
                                Log['side'] = 'SELL'
                                Log['symbol_quantity'] = str(quantity)
                                try:
                                    order_resp = self.bm1.order_market_sell(
                                        symbol = (symbol + 'USDT'),
                                        quantity = quantity
                                    )
                                except:
                                    print('Binance market sell error')
                                cum_volume = 0
                                cum_qty = 0
                                for fill_data in order_resp["fills"]:
                                    cum_volume += float(fill_data['price']) * float(fill_data['qty'])
                                    cum_qty += float(fill_data['qty'])
                                Log['USDT'] = str(cum_volume)
                                if self.ISTWD == True:
                                    try:
                                        r = await self.ace.submit_order('USDT_TWD', "SELL", 0, cum_volume,type_ = 2)
                                    except:
                                        print("ace sell usdt error")
                        ob_resp = await self.ace.get_orderbook(Log['ace_symbol'])
                        Best_Price = ob_resp['attachment']['asks'][0][1] if Log['side']=='BUY' else ob_resp['attachment']['bids'][0][1]
                        Log['Best_Price'] = Best_Price
                        trades_history = await self.ace.get_trades_history(symbol='USDT_TWD')
                        if self.ISTWD == True:
                            for his in trades_history:
                                if his['orderNo'] == r['attachment']['orderNo']:
                                    break
                            Log['TWD'] = his['tradeAmount']
                            if Log['side']=='SELL':
                                Log['Profit'] = Log['TWD'] - (Log['Best_Price'] * Log['symbol_quantity'])
                            elif Log['side']=='BUY':
                                Log['Profit'] = (Log['Best_Price'] * Log['symbol_quantity']) - Log['TWD']
                        elif self.ISTWD == False:
                            if Log['side']=='SELL':
                                Log['Profit'] = Log['USDT'] - (Log['Best_Price'] * Log['symbol_quantity'])
                            elif Log['side']=='BUY':
                                Log['Profit'] = (Log['Best_Price'] * Log['symbol_quantity']) - Log['USDT']
                        self.log_to_db(Log)
                await asyncio.sleep(10)  
            except :
                   raise ValueError(traceback.format_exc())
    async def execute(self):
        while True:
            try:
                print("loggin")
                hedging_trades_task = asyncio.create_task(self.hedging_trades_test())
                await asyncio.gather(
                    hedging_trades_task, 
                )
                
            
            except Exception as e:
                print(traceback.format_exc())
                hedging_trades_task.cancel()
                #continue

