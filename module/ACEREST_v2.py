import asyncio
import aiohttp
import json
import hmac
import time
import logging
import hashlib
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import matplotlib.pyplot as plt
import numpy as np
import sys
import os 
import math
import random
import redis
import credentials
sys.path.append(os.getcwd())

redisss = redis.Redis(host='localhost', port=6379, db=0)

def readFile(filename):    
    with open(filename, "r") as config_file:
        return json.load(config_file)

def hex_sign_msg(data):
    signature = hashlib.md5()
    signature.update(data.encode("utf-8"))
    return signature.hexdigest()

def sha256hash(secret_key, sign_params):
    m = hashlib.sha256()
    current_time = int(round(time.time() * 1000))
    sign_params_dict0 = {**sign_params}
    data = "ACE_SIGN" + str(secret_key) + "".join([str(sign_params_dict0[i]) for i in sign_params_dict0])
    print(data)
    m.update(data.encode("utf-8"))
    h = m.hexdigest()
    return h, current_time

async def async_get(url, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, *args, **kwargs) as response:
            return await response.text()

async def async_request(method, url, *args, **kwargs):
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, *args, **kwargs) as response:
            return await response.text()

class Oapi:
    testnet_endpoint = 'pre.ace.io'
    production_endpoint = 'enterprise.ace.io'

    def __init__(self, mode='production'):
        self.url = self.production_endpoint if mode == 'production' else self.testnet_endpoint
        self.endpoint = f"https://{self.url}/polarisex/open/v2/public"
        self.TOKEN_TO_ID = readFile(f"{os.getcwd()}/currency_map_ace.txt")
        self.logger = logging.getLogger('ACEREST.Spot')
        self.logger.setLevel('INFO')
        self.order_cache = {}

    def _make_headers(self):
        return {"Content-Type": "application/x-www-form-urlencoded"}

    async def _request(self, method, path, params={}, data=None):
        headers = self._make_headers()
        if method in ['GET', 'DELETE']:
            resp = await async_request(method, self.endpoint + path, headers=headers, params=params)
        else:
            resp = await async_request(method, self.endpoint + path, headers=headers, data=data)
        try:
            return json.loads(resp)
        except json.decoder.JSONDecodeError:
            self.logger.error(f"{method} {self.endpoint + path}; Could not parse response '{resp}'")
            return resp

    async def get(self, path, params={}):
        return await self._request('GET', path, params=params)

    async def delete(self, path, params):
        return await self._request('POST', path, params=params)

    async def post(self, path, data):
        return await self._request('POST', path, data=data)

    async def put(self, path, data):
        return await self._request('PUT', path, data=data)

    async def get_market_pair(self):
        resp = await self.get('/marketPair')
        print("Market pair:", resp)
        return resp
    async def get_original_orderbook(self,symbol):
        pair, baseCurrency = symbol.upper().split("_")
        data = {
            "quoteCurrencyId": int(self.TOKEN_TO_ID[baseCurrency]),
            "baseCurrencyId": int(self.TOKEN_TO_ID[pair]),
            'depth' : 10
        }
        resp = await self.get('/getOrderBook/', params=data)
        return resp

    async def get_orderbooks(self, symbol):
        pair, baseCurrency = symbol.upper().split("_")
        data = {
            "quoteCurrencyId": int(self.TOKEN_TO_ID[baseCurrency]),
            "baseCurrencyId": int(self.TOKEN_TO_ID[pair]),
            'depth' : 10
        }
        resp = await self.get('/getOrderBook/', params=data)
        print(resp)
        best_bid = float(resp['attachment']['bids'][0][1])
        best_ask = float(resp['attachment']['asks'][0][1])
        return best_bid, best_ask
        #return self._parse_orderbooks(resp)
    # async def get_orderbook(self, symbol, depth = None):
    #     pair, baseCurrency = symbol.upper().split("_")
    #     quoteCurrencyId = int(self.TOKEN_TO_ID[baseCurrency])
    #     baseCurrencyId = int(self.TOKEN_TO_ID[pair])
    #     request_params = {
    #         'quoteCurrencyId': quoteCurrencyId,
    #         "baseCurrencyId": baseCurrencyId,
    #     }
    #     #data = self._get_sign(request_params)
    #     resp = await self.get('/public/getOrderBook', params= request_params)
    #     return resp
    def _parse_orderbooks(self, resp):
        count = 1
        cum_b_qty, cum_b_price = 0, 0
        cum_a_qty, cum_a_price = 0, 0
        for ob in resp['attachment']['bids']:
            cum_b_qty += float(ob[0])
            cum_b_price += float(ob[1])
            if cum_b_qty > 10000:
                cum_b_price /= count
                break
            count += 1
        count = 1
        for ob in resp['attachment']['asks']:
            cum_a_qty += float(ob[0])
            cum_a_price += float(ob[1])
            if cum_a_qty > 10000:
                cum_a_price /= count
                break
            count += 1
        best_bid = resp['attachment']['bids'][2][1]
        best_ask = resp['attachment']['asks'][2][1]
        print(cum_b_price, cum_a_price)
        return best_bid, best_ask

    async def get_orderbooks_total(self, symbol):
        pair, baseCurrency = symbol.upper().split("_")
        data = {
            "quoteCurrencyId": int(self.TOKEN_TO_ID[baseCurrency]),
            "baseCurrencyId": int(self.TOKEN_TO_ID[pair]),
        }
        return await self.get('/getOrderBook/', params=data)

class Spot:
    version = 'v2'
    testnet_endpoint = 'pre.ace.io'
    production_endpoint = 'enterprise.ace.io'

    def __init__(self, key=None, secret=None, mode='production'):
        self.key = key
        self.secret = secret
        self.url = self.production_endpoint if mode == 'production' else self.testnet_endpoint
        self.endpoint = f"https://{self.url}/polarisex/open/{self.version}"
        self.APIKEY = key
        self.SECURITYKEY = secret
        self.TOKEN_TO_ID = readFile(f"{os.getcwd()}/currency_map_ace.txt")
        self.oapi = Oapi('production')
        self.logger = logging.getLogger('ACEREST.Spot')
        self.logger.setLevel('INFO')
        self.order_cache = {}

    def _get_sign(self, request_params):
        sign_key_string = 'ACE_SIGN' + self.SECURITYKEY
        sorted_keys = sorted(request_params.keys())
        for key in sorted_keys:
            value = request_params.get(key)
            if value is not None:
                sign_key_string += str(value)
        sign_key = hashlib.sha256(sign_key_string.encode('utf-8')).hexdigest()
        request_params['signKey'] = sign_key
        return request_params

    def _make_headers(self):
        return {"Content-Type": "application/x-www-form-urlencoded"}

    async def _request(self, method, path, params={}, data=None):
        headers = self._make_headers()
        if method in ['GET', 'DELETE']:
            resp = await async_request(method, self.endpoint + path, headers=headers, params=params)
        else:
            resp = await async_request(method, self.endpoint + path, headers=headers, data=data)
        try:
            return json.loads(resp)
        except json.decoder.JSONDecodeError:
            self.logger.error(f"{method} {self.endpoint + path}; Could not parse response '{resp}'")
            return resp

    async def get(self, path, params={}):
        return await self._request('GET', path, params=params)

    async def delete(self, path, params):
        return await self._request('POST', path, params=params)

    async def post(self, path, data):
        return await self._request('POST', path, data=data)

    async def put(self, path, data):
        return await self._request('PUT', path, data=data)

    async def get_public(self, path, **kwargs):
        resp = await async_get(self.endpoint + path, **kwargs)
        return json.loads(resp)

    async def get_market_pair(self):
        resp = await self.get_public(f'/list/marketPair')
        print("Market pair:", resp)
        return resp

    async def get_wallet(self):
        return await self.get('/user/wallet')

    async def submit_order(self, symbol, side, price, amount, type_=1):
        pair, baseCurrency = symbol.upper().split("_")
        _side = 1 if side.upper() == "BUY" else 2
        quoteCurrencyId = int(self.TOKEN_TO_ID[baseCurrency])
        baseCurrencyId = int(self.TOKEN_TO_ID[pair])
        if type_ == 1:
            order_form = {
                "baseCurrencyId": baseCurrencyId,
                "quoteCurrencyId": quoteCurrencyId,
                "buyOrSell": int(_side),
                "price": price,
                "num": amount,
                "type": type_,
                "timeStamp": int(time.time_ns() / 1000000),
                'apiKey': self.APIKEY
            }
        elif type_==2:
            order_form = {
                "baseCurrencyId": baseCurrencyId,
                "quoteCurrencyId": quoteCurrencyId,
                "buyOrSell": int(_side),
                "num": amount,
                "type": type_,
                "timeStamp": int(time.time_ns() / 1000000),
                'apiKey': self.APIKEY
            }
        data = self._get_sign(order_form)
        resp = await self.post('/order/order', data=data)
        print(resp)
        return resp

    async def submit_batch_order(self, symbol, orderinfo, isMakerOnly=False):
        _order = []
        pair, baseCurrency = symbol.upper().split("_")
        quoteCurrencyId = int(self.TOKEN_TO_ID[baseCurrency])
        baseCurrencyId = int(self.TOKEN_TO_ID[pair])
        for order in orderinfo:
            _order.append({
                "buyOrSell": "1" if order[0].upper() == "BUY" else "2",
                "price": str(order[1]),
                "num": float(order[2]),
                "isMakerOnly": isMakerOnly
            })
        order_form = {
            "baseCurrencyId": baseCurrencyId,
            "quoteCurrencyId": quoteCurrencyId,
            "orderInfo": json.dumps(_order),
            "timeStamp": int(time.time_ns() / 1000000),
            'apiKey': self.APIKEY
        }
        data = self._get_sign(order_form)
        resp = await self.post('/order/batchAdd', data=data)
        return resp

    async def cancel_order(self, cl_order_id):
        request_params = {
            "orderNo": cl_order_id,
            "timeStamp": int(time.time_ns() / 1000000),
            'apiKey': self.APIKEY
        }
        data = self._get_sign(request_params)
        try:
            resp = await self.post('/order/cancel', data=data)
        except Exception as e:
            self.logger.error(f"Error canceling order: {e}")
            resp = None
        return resp

    async def cancel_batch_orders(self, cl_order_ids):
        if cl_order_ids:
            order_form = {
                "orderNoParams": json.dumps(cl_order_ids),
                "timeStamp": int(time.time_ns() / 1000000),
                'apiKey': self.APIKEY
            }
            data = self._get_sign(order_form)
            try:
                resp = await self.post('/order/batchCancel', data=data)
                return resp
            except Exception as e:
                self.logger.error(f"Error canceling batch orders: {e}")
                return None
        return None
    #https://ace.io/polarisex/open/v2/public/getOrderBook
    async def get_open_orders(self, symbol, size=500, start=1):
        pair, baseCurrency = symbol.upper().split("_")
        quoteCurrencyId = int(self.TOKEN_TO_ID[baseCurrency])
        baseCurrencyId = int(self.TOKEN_TO_ID[pair])
        request_params = {
            "quoteCurrencyId": quoteCurrencyId,
            "baseCurrencyId": baseCurrencyId,
            "size": size,
            "start": start,
            "timeStamp": int(time.time_ns() / 1000000),
            'apiKey': self.APIKEY
        }
        data = self._get_sign(request_params)
        resp = await self.post('/order/getOrderList', data=data)
        return resp
    
    async def account_balance(self,symbol):
        request_params = {
                "timeStamp" : int(time.time_ns() / 1000000),
                'apiKey' : self.APIKEY
               }
        data = self._get_sign(request_params)
        # print(symbol)

        resp = await self.post('/coin/customerAccount',data = data)
        if symbol==None:
            return resp['attachment']
        for s in resp['attachment']:
            print(s)
            if s['currencyName'] == symbol :
                return s

    async def get_order_history(self, orderid):
        request_params = {
            'orderId': orderid,
            "timeStamp": int(time.time_ns() / 1000000),
            'apiKey': self.APIKEY
        }
        data = self._get_sign(request_params)
        resp = await self.post('/order/showOrderHistory', data=data)
        return resp

    async def get_order_status(self, orderid):
        request_params = {
            'orderId': orderid,
            "timeStamp": int(time.time_ns() / 1000000),
            'apiKey': self.APIKEY
        }
        data = self._get_sign(request_params)
        resp = await self.post('/order/showOrderStatus', data=data)
        return resp

    async def get_trades_history(self, symbol, size=100, start=1):
        pair, baseCurrency = symbol.upper().split("_")
        quoteCurrencyId = int(self.TOKEN_TO_ID[baseCurrency])
        baseCurrencyId = int(self.TOKEN_TO_ID[pair])
        request_params = {
            "quoteCurrencyId": quoteCurrencyId,
            "baseCurrencyId": baseCurrencyId,
            "size": size,
            "start": start,
            "timeStamp": int(time.time_ns() / 1000000),
            'apiKey': self.APIKEY
        }
        data = self._get_sign(request_params)
        resp = await self.post('/order/getTradeList', data=data)
        return resp['attachment']

    async def cancel_all_order(self, symbol):
        while True:
            order_ids = []
            open_orders = await self.get_open_orders(symbol)
            print(open_orders)
            for trade in open_orders['attachment']:
                order_ids.append(trade['orderNo'])
            resp = await self.cancel_batch_orders(order_ids)
            if len(order_ids) == 0:
                break
    async def get_orderbook(self, symbol, depth = None):
        pair, baseCurrency = symbol.upper().split("_")
        quoteCurrencyId = int(self.TOKEN_TO_ID[baseCurrency])
        baseCurrencyId = int(self.TOKEN_TO_ID[pair])
        request_params = {
            'quoteCurrencyId': quoteCurrencyId,
            "baseCurrencyId": baseCurrencyId,
            "depth":depth
        }
        #data = self._get_sign(request_params)
        resp = await self.get('/public/getOrderBook', params= request_params)
        return resp
    async def optimal_exchange_rate(self):
        #taiwan_bank_rate_bid, taiwan_bank_rate_ask = self.get_sino_bank_rate()
        crypto_exchange_rate_bid, crypto_exchange_rate_ask = await self.oapi.get_orderbooks('USDT_TWD')
        #return taiwan_bank_rate_bid, taiwan_bank_rate_ask, crypto_exchange_rate_bid, crypto_exchange_rate_ask
        return 0, 0, crypto_exchange_rate_bid, crypto_exchange_rate_ask

    async def optimal_bid_rate(self):
        taiwan_bank_rate_bid, taiwan_bank_rate_ask = self.get_sino_bank_rate()
        crypto_exchange_rate_bid, crypto_exchange_rate_ask = await self.oapi.get_orderbooks('USDT_TWD')
        optimal_bid = min(float(taiwan_bank_rate_bid), float(crypto_exchange_rate_bid))
        redisss.set('optimal_bid', float(optimal_bid))
        print("OB:", redisss.get('optimal_bid'))
        return optimal_bid

    async def optimal_ask_rate(self):
        taiwan_bank_rate_bid, taiwan_bank_rate_ask = self.get_sino_bank_rate()
        _crypto_exchange_rate_bid, crypto_exchange_rate_ask = await self.oapi.get_orderbooks('USDT_TWD')
        optimal_ask = max(float(taiwan_bank_rate_ask), float(crypto_exchange_rate_ask))
        redisss.set('optimal_ask', float(optimal_ask))
        print("OA:", redisss.get('optimal_ask'))
        return optimal_ask

    def get_taiwan_bank_rate(self):
        url = "https://rate.bot.com.tw/xrt?Lang=zh-TW"
        resp = requests.get(url)
        resp.encoding = 'utf-8'
        html_soup = BeautifulSoup(resp.text, "lxml")
        rate_table = html_soup.find('table', attrs={'title': '牌告匯率'}).find('tbody').find_all('tr')
        sellout_rate = rate_table[0].find('td', attrs={'data-table': '本行現金賣出'}).text
        buyin_rate = rate_table[0].find('td', attrs={'data-table': '本行現金買入'}).text
        return float(sellout_rate), float(buyin_rate)

    def get_sino_bank_rate(self):
        header = {'User-Agent': 'Mozilla/5.0'}
        time_ = str(math.floor(time.time() * 1000))
        url = f"https://mma.sinopac.com/ws/share/rate/ws_exchange.ashx?exchangeType=REMIT&Cross=genREMITResult&{time_}&callback=genREMITResult&_={time_}"
        r = requests.get(url, headers=header)
        r.encoding = 'utf-8'
        soup = BeautifulSoup(r.text, 'html.parser')
        index = soup.text.find('USD.png')
        rb = soup.text[index + 23:index + 23 + 8]
        rs = soup.text[index + 23 + 8 + 16:index + 23 + 8 + 15 + 9]
        return float(rb), float(rs)

    async def manual_clean(self, symbol, side, price, amount):
        side = int(side)
        action = "BUY" if side == 1 else "SELL"
        return await self.submit_order(f'{symbol}_TWD', action, float(price), float(amount), type_=1)

