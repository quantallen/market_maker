import sys
import os 
import asyncio
from binance.client import AsyncClient,Client
import configparser
import argparse
from module.ACEREST_v2 import Spot
from credentials import securityKey,apiKey,lineNotifyToken,lineErrorNotifyToken
from config import BinanceConfig
from module.mmaker_v2 import MMaker
from maker_config import TokenConfig
import requests
import traceback

os.chdir(sys.path[0])
sys.path.append('./module')
def send_line_notify(token, message):
        url = "https://notify-api.line.me/api/notify"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        data = {
            "message": message
        }
        requests.post(url, headers=headers, data=data)


async def deleAceMaker(aceapi,acesymbol):
    del_resp = await aceapi.get_open_orders(acesymbol)
    print(del_resp)
    del_list = []
    if len(del_resp['attachment']) != 0 :
        for d in del_resp['attachment']:
            if d['status'] == 0 or d['status'] == 1 or d['status'] == 2 or d['status'] == 3 or d['status'] == 4:
                del_list.append(d['orderNo'])
        print(del_list)
        r = await aceapi.cancel_batch_orders(del_list)
        print(r)
        if r['status'] != 200 :
            for d in del_list :
                resp = await aceapi.cancel_order(d)
                print(resp)
async def main(biancnesymbol,acesymbol):
    mm_config = configparser.ConfigParser()
    mm_config.read('./mm_config.ini')
    while True:
        try :
            binance_client = await AsyncClient.create()
            binance_client= Client()
            configs = BinanceConfig(binance_client,biancnesymbol,acesymbol)
            ace = Spot(key=apiKey, secret=securityKey, mode = 'testnet')
            await deleAceMaker(ace,acesymbol) # 造市前先刪除未成交的單
            maker = MMaker(binance_client, ace, configs,mm_config, lineErrorNotifyToken) #造市初始化
            await maker.execute() #造市開始
        except Exception as e:
            print(traceback.print_exc())
            send_line_notify(lineErrorNotifyToken, f"{acesymbol} MAKER ERROR : {str(e)}") # 造市異常時通知
            await binance_client.close_connection()
            await deleAceMaker(maker,ace) # 造市異常時刪除未成交的單
            continue
        except KeyboardInterrupt :
            await binance_client.close_connection()
            await deleAceMaker(maker,ace) # 造市異常時刪除未成交的單
if __name__ == '__main__':
     # Argument parsing for clearer input
    parser = argparse.ArgumentParser(description='Market making script for Binance and ACE.')
    parser.add_argument('-b', '--binance_symbol', type=str, required=True, help='Trading pair symbol on Binance')
    parser.add_argument('-a', '--ace_symbol', type=str, required=True, help='Trading pair symbol on ACE')
    args = parser.parse_args()

    # Run the main function with the parsed arguments
    asyncio.run(main(args.binance_symbol, args.ace_symbol))