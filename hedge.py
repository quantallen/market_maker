import sys
import os 
os.chdir(sys.path[0])
sys.path.append('./module')
import asyncio
from binance.client import AsyncClient
from binance.client import Client
from module.ACEREST_v2 import Spot
from credentials import securityKey,uid ,apiKey,phone,binance_test_api_key,binance_test_api_secret
# from module.hedging_trade import Hedging
from module.hedgingAccountBalance import Hedging
# from balance_config import balance_config
import json 
f = open('balance_config.json')
balance_config = json.load(f)
db_config = {
    "host": "localhost",
    "user": "root",
    "password": "12345678",
    "database": "MarketMaker"
}
import requests
binance_exchangeInfo = requests.get('https://api.binance.com/api/v3/exchangeInfo')
binance_exchangeInfo = binance_exchangeInfo.json()
hedge_config = {}
for ss in binance_exchangeInfo['symbols']:
    if ss['quoteAsset'] == 'USDT':
        hedge_config[ss['baseAsset']] = {}
        for filters in ss['filters']:
            if filters['filterType'] == 'NOTIONAL':
                hedge_config[ss['baseAsset']]['minNotional'] = filters['minNotional']
            if filters['filterType'] == 'LOT_SIZE':
                hedge_config[ss['baseAsset']]['minQty'] = filters['minQty']

async def main():
    binance_client = await AsyncClient.create(api_key=binance_test_api_key,api_secret=binance_test_api_secret)
    ace = Spot(key=apiKey, secret=securityKey, mode = 'testnet')
    maker = Hedging(binance_client, ace, balance_config,db_config,hedge_config,ISTWD=True)
    await maker.execute()

if __name__ == '__main__':
    asyncio.run(main())