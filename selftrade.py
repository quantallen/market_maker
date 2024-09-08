import sys
import asyncio
from binance.client import Client, AsyncClient
import configparser
from module.ACEREST_v2 import Spot
from credentials import securityKey,uid ,apiKey,phone,lineErrorNotifyToken
from config import BinanceConfig
from module.selftrader import SelfTrader
import argparse
async def main(biancnesymbol,acesymbol):
    
    mm_config = configparser.ConfigParser()
    mm_config.read('./mm_config.ini')
    binance_socketclient = await AsyncClient.create()
    binance_client = Client()
    configs = BinanceConfig(binance_client,biancnesymbol,acesymbol)
    #ace = Spot(key=apiKey, secret=securityKey, UID = uid, phone = phone, mode = 'production')
    ace = Spot(key=apiKey, secret=securityKey, mode = 'testnet')
    maker = SelfTrader(binance_socketclient, binance_client, ace, configs,mm_config,lineErrorNotifyToken)
    await maker.execute()

if __name__ == '__main__':
     # Argument parsing for clearer input
    parser = argparse.ArgumentParser(description='Market making script for Binance and ACE.')
    parser.add_argument('-b', '--binance_symbol', type=str, required=True, help='Trading pair symbol on Binance')
    parser.add_argument('-a', '--ace_symbol', type=str, required=True, help='Trading pair symbol on ACE')
    args = parser.parse_args()

    # Run the main function with the parsed arguments
    asyncio.run(main(args.binance_symbol, args.ace_symbol))