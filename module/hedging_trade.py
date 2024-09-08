import asyncio
import time
import logging
import sys
from datetime import timedelta, datetime, date
from decimal import Decimal
import traceback
import os
import json

from binance.streams import BinanceSocketManager
import telegram
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from requests import Session
from prettytable import PrettyTable
import redis
import pymongo

from cumberland.functions_cumberland import get_cumberland_price, accept_cumberland_order


class Sheet:
    def __init__(self):
        self.sheet = None

    def sheet_connection(self):
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        credentials = ServiceAccountCredentials.from_json_keyfile_name(
            f"{os.path.abspath(os.getcwd())}/twdhedge.json", scope)
        client = gspread.authorize(credentials)
        self.sheet = client.open_by_key("1o45L1XJ45UXm1KHJcO9KcNmVTcIn-6hxtGPNRgQb3nw")

    def write_to_sheet(self, ref, target, data):
        worksheet = self.sheet.worksheets()
        check_list = [t.title for t in worksheet]
        title = f"{date.today()}-{ref}-{target}-Hedging Details"
        if title not in check_list:
            self.sheet.add_worksheet(title=title, rows=5000, cols=30)
            worksheet = self.sheet.worksheet(title)
            dataTitle = [
                "DateTime", "ACE_SYMBOL", "AVG_PRICE", "SIZE", "SIDE", "ACE_VOLUME", "BINANCE_SYMBOL",
                "AVG_PRICE", "SIZE", "SIDE", "BSC_VOLUME", "DIRECTION_OF_TWD", "EXCHANGE", "AVG_PRICE",
                "SIZE", "VOLUME", "PROFIT", "TWD_USDT_RATE"
            ]
            worksheet.append_row(dataTitle, table_range="A1")
        worksheet = self.sheet.worksheet(title)
        worksheet.append_row(data, table_range="A1")


def pretty_table(dct):
    table = PrettyTable(['Title', 'Information'])
    for key, val in dct.items():
        table.add_row([key, val])
    return table


def round_price(x, PRECISION_PRICE):
    return float(Decimal(x).quantize(PRECISION_PRICE))


def trunc_amount(x, PRECISION_AMOUNT):
    return float(Decimal(x).quantize(PRECISION_AMOUNT))


def initial_body(symbol):
    return [{
        "ace_uid": 59590,
        "symbol": symbol,
        "token_amount": None,
        "profit": None,
        "base_currency": "TWD",
        "timestamp": int(time.time() * 1000),
        "order_detail": [
            {"exchange": "ACE", "quoteCurrency": symbol.split('_')[0], "baseCurrency": symbol.split('_')[1],
             "side": None, "price": None, "amount": None, "tradeType": "local"},
            {"exchange": "Binance", "quoteCurrency": symbol.split('_')[0], "baseCurrency": "USDT",
             "side": None, "price": None, "amount": None, "tradeType": "hedge"}
        ]
    }]


class Hedging:
    chat_id = '-895379671'
    bot = telegram.Bot(token='5806778171:AAFBuCBsa46wgdhwAwmAlIQbHiaiHGQaj7U')
    chat_id_2 = '-965834955'
    bot2 = telegram.Bot(token='6234196428:AAEdQrKd_B6cuoDnajZpw1StRXDq7GnHatI')

    def __init__(self, bapi, bapi2, api2, config):
        self.bm1 = bapi
        self.bm2 = BinanceSocketManager(bapi2)
        self.order_api = bapi2
        self.ace = api2
        self.config = config
        self.log = logging.getLogger(f"{date.today()}_ACE_{self.config.ACE_SYMBOL}_HEDGE")
        self.lock = asyncio.Lock()
        self.sheet = Sheet()
        self.sheet_data = []
        self.redis = redis.Redis(host='localhost', port=6379, db=0)
        self.ace_cum_qty = 0
        self.total_amount = 0
        self.avg_price = 0
        self.myclient = pymongo.MongoClient("mongodb://localhost:27017/")
        self.Ace_MM = self.myclient["ACE_Allen_Maker_Hedge"]
        self.session = Session()
        self.trade_info_endpoint = "https://35.74.175.214/sendtrade_detail"
        self.record_trade_ids = []

    async def hedging_trades(self):
        while True:
            try:
                self.redis.set('maker_hedge', 1, ex=60)
                twd_rate_ask = float(self.redis.get('optimal_ask'))
                twd_rate_bid = float(self.redis.get('optimal_bid'))
                resp = await self.ace.get_trades_history(self.config.ACE_SYMBOL)

                table_maker = self.Ace_MM[f"{self.config.ACE_SYMBOL}_Maker"]
                cursor = table_maker.find({})
                data = [d for d in cursor]
                tradeNo_list = [x['tradeNo'] for x in data]

                if resp:
                    for re in reversed(resp):
                        trade_time = datetime.strptime(re["tradeTime"], "%Y-%m-%d %H:%M:%S")
                        if trade_time + timedelta(minutes=10) >= datetime.now() and re['tradeNo'] not in tradeNo_list and re['tradeNo'] not in self.record_trade_ids and not re['isSelf']:
                            table_maker.insert_one(re)
                            self.record_trade_ids.append(re["tradeNo"])
                            if re["buyOrSell"] == 1:
                                self.total_amount += float(re["tradeAmount"])
                                self.ace_cum_qty += float(re["tradeNum"])
                            elif re["buyOrSell"] == 2:
                                self.total_amount -= float(re["tradeAmount"])
                                self.ace_cum_qty -= float(re["tradeNum"])
                    if abs(self.ace_cum_qty) > 0:
                        self.avg_price = self.total_amount / self.ace_cum_qty

                    check_bid_ask = twd_rate_bid if self.total_amount >= 0 else twd_rate_ask
                    if abs(self.ace_cum_qty) * abs(self.avg_price) / check_bid_ask > self.config.binance_notional_value:
                        await self._execute_hedge(twd_rate_ask, twd_rate_bid)

                await asyncio.sleep(10)
            except Exception as e:
                self.log.error(traceback.format_exc())
                self.bot.send_message(chat_id=self.chat_id_2, text="DB can not read !!!! Alert")

    async def _execute_hedge(self, twd_rate_ask, twd_rate_bid):
        start = time.time()
        test_body = initial_body(self.config.ACE_SYMBOL)
        side, quantity = ("SELL", abs(self.ace_cum_qty)) if self.ace_cum_qty > 0 else ("BUY", abs(self.ace_cum_qty))
        self.sheet_data.extend([str(datetime.now()), self.config.ACE_SYMBOL, abs(self.avg_price), abs(self.ace_cum_qty), side, abs(self.total_amount)])

        test_body[0]['token_amount'] = abs(self.ace_cum_qty)
        test_body[0]['order_detail'][0]['amount'] = abs(self.ace_cum_qty)
        test_body[0]['order_detail'][0]['price'] = abs(self.avg_price)
        test_body[0]['order_detail'][0]['side'] = side

        orderbook_price = self.bm1.get_order_book(symbol=self.config._SYMBOL)
        price = orderbook_price['asks'][0][0] if side == "BUY" else orderbook_price['bids'][0][0]
        new_price = float(price) * (1 + self.config.buy_price_ratio) if side == "BUY" else float(price) * (1 - self.config.sell_price_ratio)

        try:
            resp_binance = await self.order_api.create_order(
                symbol=self.config._SYMBOL,
                side=side,
                price=round_price(new_price, self.config.BINANCE_PRICE_PRECISION),
                quantity=trunc_amount(quantity, self.config.BINANCE_SIZE_PRECISION),
                type='LIMIT', timeInForce='GTC')
        except Exception as e:
            self.log.error(traceback.format_exc())
            self.bot2.send_message(chat_id=self.chat_id_2, text=f'Error placing order: {str(e)}')
            return

        cum_volume = sum(float(fill['price']) * float(fill['qty']) for fill in resp_binance["fills"])
        cum_qty = sum(float(fill['qty']) for fill in resp_binance["fills"])
        avg_price = cum_volume / cum_qty

        self.sheet_data.extend([resp_binance['symbol'], avg_price, float(resp_binance["executedQty"]), resp_binance['side'], cum_volume])
        await self._execute_hedge_follow_up(resp_binance, side, avg_price, cum_volume, quantity, twd_rate_ask, twd_rate_bid)

        end = time.time()
        self.log.info(f'Total hedge time: {end - start} secs')
        self.sheet.write_to_sheet(self.config._SYMBOL, self.config.ACE_SYMBOL, self.sheet_data)
        self.sheet_data = []
        self.ace_cum_qty = 0
        self.avg_price = 0
        self.total_amount = 0

    async def _execute_hedge_follow_up(self, resp_binance, side, avg_price, cum_volume, quantity, twd_rate_ask, twd_rate_bid):
        if resp_binance['side'] == "BUY":
            await self._handle_buy_hedge(avg_price, cum_volume, twd_rate_ask, quantity)
        elif resp_binance['side'] == "SELL":
            await self._handle_sell_hedge(avg_price, cum_volume, twd_rate_bid, quantity)

    async def _handle_buy_hedge(self, avg_price, cum_volume, twd_rate_ask, quantity):
        to_buy_usdt = cum_volume
        cumber_bid, cumber_ask = float(self.redis.get('cbl_bid')), float(self.redis.get('cbl_ask'))

        tb, ta, ab, aa = await self.ace.optimal_exchange_rate()
        if cumber_ask * float(ta) >= float(aa):
            r = await self.ace.submit_order('USDT_TWD', "BUY", float(aa), to_buy_usdt, type_=2)
            hedge_avg_price = float(aa)
            hedge_qty = to_buy_usdt
            self.sheet_data.extend(["TWD->USDT", "ACE", hedge_avg_price, hedge_qty, to_buy_usdt])
        elif cumber_ask * float(ta) < float(aa):
            resp_cbl = await accept_cumberland_order('USDT', 'BUY', to_buy_usdt, base_currency='USD')
            hedge_avg_price = float(ta) * float(resp_cbl['unitPrice']['price'])
            hedge_qty = float(resp_cbl['quantity']['quantity'])
            self.sheet_data.extend(["TWD->USDT", "CBL", hedge_avg_price, hedge_qty, to_buy_usdt])

        profit = float(abs(self.avg_price)) * float(abs(self.ace_cum_qty)) - hedge_qty * hedge_avg_price
        self.sheet_data.extend([profit, hedge_avg_price])
        self.log.info(f"Profit: {profit} TWD")

    async def _handle_sell_hedge(self, avg_price, cum_volume, twd_rate_bid, quantity):
        to_sell_usdt = cum_volume
        cumber_bid, cumber_ask = float(self.redis.get('cbl_bid')), float(self.redis.get('cbl_ask'))

        tb, ta, ab, aa = await self.ace.optimal_exchange_rate()
        if cumber_bid * float(tb) <= float(ab):
            r = await self.ace.submit_order('USDT_TWD', "SELL", float(ab), to_sell_usdt, type_=2)
            hedge_avg_price = float(ab)
            hedge_qty = to_sell_usdt
            self.sheet_data.extend(["USDT->TWD", "ACE", hedge_avg_price, hedge_qty, to_sell_usdt])
        elif cumber_bid * float(tb) > float(ab):
            resp_cbl = await accept_cumberland_order('USDT', 'SELL', to_sell_usdt, base_currency='USD')
            hedge_avg_price = float(tb) * float(resp_cbl['unitPrice']['price'])
            hedge_qty = float(resp_cbl['quantity']['quantity'])
            self.sheet_data.extend(["USDT->TWD", "CBL", hedge_avg_price, hedge_qty, to_sell_usdt])

        profit = hedge_qty * hedge_avg_price - float(abs(self.avg_price)) * float(abs(self.ace_cum_qty))
        self.sheet_data.extend([profit, hedge_avg_price])
        self.log.info(f"Profit: {profit} TWD")

    async def execute(self):
        while True:
            try:
                self.sheet.sheet_connection()
                await self.hedging_trades()
            except Exception as e:
                self.bot.send_message(chat_id=self.chat_id, text=str(traceback.format_exc()))
                self.log.error(traceback.format_exc())