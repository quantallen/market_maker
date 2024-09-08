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
import pymysql  # MySQL connector
from binance.streams import BinanceSocketManager
import requests  # Import requests for sending notifications
from binance.client import AsyncClient, Client
from module.ACEREST_v2 import Oapi, Spot
from credentials import securityKey, uid, apiKey, phone, lineNotifyToken
from config import BinanceConfig
from prettytable import PrettyTable
from PIL import Image, ImageDraw, ImageFont
import io
import argparse
import configparser

HEDGE_MAPPING = {"BUY": "SELL", "SELL": "BUY"}


class MakerMonitor:
    orderbook = {}
    trades = {}
    data = None

    def __init__(self, bianceasyncapi, aceapi, config, mm_config, db_config, line_notify_token, line_notify_mention):
        self.bm1 = BinanceSocketManager(bianceasyncapi)
        self.aceapi = aceapi
        self.config = config
        self.mm_config = mm_config
        self.db_config = db_config
        self.line_notify_token = line_notify_token
        self.line_notify_mention = line_notify_mention
        self.spread_prices = None
        self.remember_quotos = None
        self.count = 0
        self.fast_del_list = []
        self.del_list = []
        self.first = True
        self.success = True
        self.change = False
        self.slow_ob_check = True
        # Ensure the database table exists
        self.ensure_table_exists()

    def connect_db(self):
        return pymysql.connect(**self.db_config)

    def ensure_table_exists(self):
        """Ensure that the crypto_spread_monitor table exists in the database."""
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS crypto_spread_monitor (
            id INT AUTO_INCREMENT PRIMARY KEY,
            time DATETIME,
            binance_symbol VARCHAR(10),
            ace_symbol VARCHAR(10),
            binance_bid1price DECIMAL(18, 8),
            binance_bid1size DECIMAL(18, 8),
            ACE_bid1price DECIMAL(18, 8),
            ACE_bid1size DECIMAL(18, 8),
            binance_ask1price DECIMAL(18, 8),
            binance_ask1size DECIMAL(18, 8),
            ACE_ask1price DECIMAL(18, 8),
            ACE_ask1size DECIMAL(18, 8),
            bid_diff DECIMAL(18, 8),
            ask_diff DECIMAL(18, 8)
        );
        """
        try:
            conn = self.connect_db()
            with conn.cursor() as cursor:
                cursor.execute(create_table_sql)
            conn.commit()
        finally:
            conn.close()

    def log_to_db(self, data):
        try:
            conn = self.connect_db()
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO crypto_spread_monitor (time, binance_symbol, ace_symbol, binance_bid1price, binance_bid1size, ACE_bid1price, ACE_bid1size, binance_ask1price, binance_ask1size, ACE_ask1price, ACE_ask1size, bid_diff, ask_diff)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(sql, (
                    data['time'], data['binance_symbol'], data['ace_symbol'],
                    data['binance_bid1price'], data['binance_bid1size'],
                    data['ace_bid1price'], data['ace_bid1size'],
                    data['binance_ask1price'], data['binance_ask1size'],
                    data['ace_ask1price'], data['ace_ask1size'],
                    data['bid_diff'], data['ask_diff']
                ))
            conn.commit()
        finally:
            conn.close()

    def send_line_notify(self, message):
        url = "https://notify-api.line.me/api/notify"
        headers = {
            "Authorization": f"Bearer {self.line_notify_token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "message": f"{message}",  # Including the mention
            # "notificationDisabled": False,
            # "stickerPackageId": 1,
            # "stickerId": 410
        }
        requests.post(url, headers=headers, data=data)

    async def check_price_difference(self,binancesymbol, acesymbol):
        binancebid1 = self.orderbook[binancesymbol]['bids'][0]
        binanceask1 = self.orderbook[binancesymbol]['asks'][0]
        ace_bid1 = self.orderbook[acesymbol]['bids'][0]
        ace_ask1 = self.orderbook[acesymbol]['asks'][0]
        bid_diff = round((binancebid1 - ace_bid1) / binancebid1,6)
        ask_diff = round((ace_ask1 - binanceask1) / binanceask1,6)
        print(binancebid1, ace_bid1, bid_diff)
        print(binanceask1, ace_ask1, ask_diff)
        if abs(bid_diff) > 0.01 or (ask_diff) > 0.01:
            data = {
                'time': datetime.now(),
                'binance_symbol': binancesymbol,
                'ace_symbol': acesymbol,
                'binance_bid1price': self.orderbook[binancesymbol]['bids'][0],
                'binance_bid1size': self.orderbook[binancesymbol]['bids'][1],
                'ace_bid1price': self.orderbook[acesymbol]['bids'][0],
                'ace_bid1size': self.orderbook[acesymbol]['bids'][1],
                'binance_ask1price': self.orderbook[binancesymbol]['asks'][0],
                'binance_ask1size': self.orderbook[binancesymbol]['asks'][1],
                'ace_ask1price': self.orderbook[acesymbol]['asks'][0],
                'ace_ask1size': self.orderbook[acesymbol]['asks'][1],
                'bid_diff': bid_diff,
                'ask_diff': ask_diff,
            }
            self.log_to_db(data)
        if abs(bid_diff) > 0.005 or (ask_diff) > 0.005:
            msg = f"幣安 : {binancesymbol} | ACE : {acesymbol} | 價差過大: BID: {bid_diff:.6f}, ASK: {ask_diff:.6f}"
            #self.send_line_notify(msg)

    async def Update_orderbook(self):
        socket_list = []
        for symbol in self.config.keys():
            socket_list.append(f'{symbol.lower()}@depth5')
        #print(socket_list)
        try:
            ws = self.bm1.multiplex_socket(socket_list)
            async with ws as wscm:
                while True:
                    resp = await wscm.recv()
                    #print(resp)
                    symbol = resp['stream'].split('@')[0].upper()
                    if 'bids' in resp['data'] and 'asks' in resp['data']:
                        binance_bid1price = Decimal(resp['data']['bids'][0][0])
                        binance_ask1price = Decimal(resp['data']['asks'][0][0])
                        binance_bid1size = Decimal(resp['data']['bids'][0][1])
                        binance_ask1size = Decimal(resp['data']['asks'][0][1])
                        _, _, twd_rate_bid, twd_rate_ask = await self.aceapi.optimal_exchange_rate()
                        twd_bid = Decimal(twd_rate_bid)
                        twd_ask = Decimal(twd_rate_ask)
                        ace_symbol = self.config[symbol]['ACE_SYMBOL'].replace('_', '')
                        self.orderbook[symbol] = {'bids': [binance_bid1price * twd_bid * Decimal(1 - float(self.mm_config[ace_symbol]['FEE'])), binance_bid1size], 'asks': [binance_ask1price * twd_ask * Decimal(1 + float(self.mm_config[ace_symbol]['FEE'])), binance_ask1size]}
                        ace_orderbook = await self.aceapi.oapi.get_original_orderbook(self.config[symbol]['ACE_SYMBOL'])
                        ace_bid1price = Decimal(float(ace_orderbook['attachment']['bids'][0][1]))
                        ace_bid1size = Decimal(float(ace_orderbook['attachment']['bids'][0][0]))
                        ace_ask1price = Decimal(float(ace_orderbook['attachment']['asks'][0][1]))
                        ace_ask1size = Decimal(float(ace_orderbook['attachment']['asks'][0][0]))
                        self.orderbook[ace_symbol] = {'bids': [ace_bid1price, ace_bid1size], 'asks': [ace_ask1price, ace_ask1size]}
                        print(self.orderbook)
                        if symbol in self.orderbook and ace_symbol in self.orderbook :
                            await self.check_price_difference(symbol, ace_symbol)
                    await asyncio.sleep(0.01)
        except Exception as e:
            print(traceback.format_exc())

    def draw_table(self, data, headers, cell_width=150, cell_height=50, padding=10):
        """
        Draws a table as an image using PIL.

        :param data: List of rows, where each row is a list of cell values.
        :param headers: List of column headers.
        :param cell_width: Width of each cell.
        :param cell_height: Height of each cell.
        :param padding: Padding around the text in each cell.
        :return: BytesIO object containing the image data.
        """
        # Load fonts: regular and bold
        try:
            font_regular = ImageFont.truetype("Arial", 14)  # Regular font for text
            font_bold = ImageFont.truetype("Arial Bold", 28)  # Bold font for numbers
        except IOError:
            font_regular = ImageFont.load_default()  # Fallback to default font if the specified font is not available
            font_bold = ImageFont.load_default()  # Fallback to default font for bold text as well

        # Calculate table size
        num_columns = len(headers)
        num_rows = len(data) + 1  # Include header row
        img_width = num_columns * cell_width
        img_height = num_rows * cell_height

        # Create a new image with a white background
        image = Image.new("RGB", (img_width, img_height), "white")
        draw = ImageDraw.Draw(image)

        # Draw headers
        for col_num, header in enumerate(headers):
            x = col_num * cell_width
            y = 0
            draw.rectangle([(x, y), (x + cell_width, y + cell_height)], outline="black", fill="lightgrey")
            # Calculate the size of the text using textbbox
            text_bbox = draw.textbbox((0, 0), header, font=font_regular)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]
            draw.text((x + (cell_width - text_width) / 2, y + (cell_height - text_height) / 2),
                      header, font=font_regular, fill="black")

        # Draw data rows
        for row_num, row in enumerate(data):
            for col_num, cell_value in enumerate(row):
                x = col_num * cell_width
                y = (row_num + 1) * cell_height
                draw.rectangle([(x, y), (x + cell_width, y + cell_height)], outline="black", fill="white")
                
                # Determine the text color and font based on the condition for BP values
                if col_num in [2, 3]:  # Assuming Spread BID (BP) and Spread ASK (BP) are at index 2 and 3
                    try:
                        value = float(cell_value)
                        text_color = "red" if value > 50 or value < -50 else "black"
                        font_to_use = font_bold  # Use bold font for numerical values
                    except ValueError:
                        text_color = "black"  # Fallback in case of non-numeric value
                        font_to_use = font_bold  # Use regular font for non-numerical values
                else:
                    text_color = "black"
                    font_to_use = font_bold

                # Calculate the size of the text using textbbox
                text_bbox = draw.textbbox((0, 0), str(cell_value), font=font_to_use)
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]
                draw.text((x + (cell_width - text_width) / 2, y + (cell_height - text_height) / 2),
                          str(cell_value), font=font_to_use, fill=text_color)

        # Save the image to a BytesIO object
        img_bytes = io.BytesIO()
        image.save(img_bytes, format="PNG")
        img_bytes.seek(0)

        return img_bytes

    def create_table_data(self):
        """
        Creates table data based on the order book information.

        :return: Headers and data for the table.
        """
        headers = ["BINANCE", "ACE", "Spread BID (BP)", "Spread ASK (BP)"]
        data = []

        # Add rows to the table (Example data; replace with actual data)
        for symbol in self.config.keys():
            ace_symbol = self.config[symbol]['ACE_SYMBOL'].replace('_', '')
            if symbol in self.orderbook and ace_symbol in self.orderbook:
                binance_bid1 = float(self.orderbook[symbol]['bids'][0])
                binance_ask1 = float(self.orderbook[symbol]['asks'][0])
                ace_bid1 = float(self.orderbook[ace_symbol]['bids'][0])
                ace_ask1 = float(self.orderbook[ace_symbol]['asks'][0])
                spread_bid = (binance_bid1 - ace_bid1) / binance_bid1 * 10000
                spread_ask = (ace_ask1 - binance_ask1) / binance_ask1 * 10000

                data.append([
                    symbol,
                    ace_symbol,
                    f"{spread_bid:.2f}",
                    f"{spread_ask:.2f}"
                ])

        return headers, data

    def send_line_notify_image(self, image_bytes, message=""):
        url = "https://notify-api.line.me/api/notify"
        headers = {
            "Authorization": "Bearer " + self.line_notify_token
        }
        payload = {"message": f"{message}"}
        files = {"imageFile": ("table.png", image_bytes, "image/png")}
        r = requests.post(url, headers=headers,data=payload, files=files)
        return r.status_code

    async def send_periodic_notify(self):
        while True:
            print("Checking market data...")
            headers, data = self.create_table_data()

            if len(data) > 0:
                img_bytes = self.draw_table(data, headers)
                self.send_line_notify_image(img_bytes, message="Current Market Data")

            await asyncio.sleep(900)  # Notify every 10 minutes

    async def execute(self):
        notify_task = asyncio.create_task(self.send_periodic_notify())
        update_orderbook_task = asyncio.create_task(self.Update_orderbook())
        await asyncio.gather(notify_task, update_orderbook_task)

async def main():
    try:
        bianceasyncapi = await AsyncClient.create()
        aceapi = Spot(key=apiKey, secret=securityKey, mode='production')
        configs = {
            "BTCUSDT": {"ACE_SYMBOL": "BTC_TWD"},  # Example symbol pair
            "ETHUSDT": {"ACE_SYMBOL": "ETH_TWD"},  # Add more symbols as needed
            "ADAUSDT": {"ACE_SYMBOL": "ADA_TWD"},
            "APEUSDT": {"ACE_SYMBOL": "APE_TWD"},
            "BNBUSDT": {"ACE_SYMBOL": "BNB_TWD"},
            "BONKUSDT": {"ACE_SYMBOL": "BONK_TWD"},
            "DOGEUSDT": {"ACE_SYMBOL": "DOGE_TWD"},
            "DOTUSDT": {"ACE_SYMBOL": "DOT_TWD"},
            "FTMUSDT": {"ACE_SYMBOL": "FTM_TWD"},
            "GALAUSDT": {"ACE_SYMBOL": "GALA_TWD"},
            "LTCUSDT": {"ACE_SYMBOL": "LTC_TWD"},
            "MATICUSDT": {"ACE_SYMBOL": "MATIC_TWD"},
            "SANDUSDT": {"ACE_SYMBOL": "SAND_TWD"},
            "SHIBUSDT": {"ACE_SYMBOL": "SHIB_TWD"},
            "SOLUSDT": {"ACE_SYMBOL": "SOL_TWD"},
            "SSVUSDT": {"ACE_SYMBOL": "SSV_TWD"},
            "TRXUSDT": {"ACE_SYMBOL": "TRX_TWD"},
            "WOOUSDT": {"ACE_SYMBOL": "WOO_TWD"},
            "XRPUSDT": {"ACE_SYMBOL": "XRP_TWD"},
        }
        mm_config = configparser.ConfigParser()
        mm_config.read('./mm_config.ini')
        db_config = {
            "host": "localhost",
            "user": "root",
            "password": "12345678",
            "database": "MarketMaker"
        }
        line_notify_token = "9AFIyrdh8PTNYt9eQLfDlunkrVfw4WAj0E9R5aLQl77"
        line_notify_mention = "郭瑋倫"  # Replace with the user's Line Notify ID

        mmaker = MakerMonitor(bianceasyncapi, aceapi, configs, mm_config, db_config, line_notify_token, line_notify_mention)
        await mmaker.execute()
    except Exception as e:
        error_message = f"Critical error in main execution:\n{traceback.format_exc()}\n @ {line_notify_mention} "
        mmaker.send_line_notify(error_message)

# Example configuration and execution
if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())