import credentials
import asyncio
import time
import random
from module.ACEREST_v2 import Spot, Oapi
async def submit_unit_test(apiKey,securityKey):
    ace = Spot(key=apiKey, secret=securityKey, mode='testnet')
    for i in range(1):
        side = "BUY" if random.randint(1, 100) % 2 == 0 else "SELL"
        side = "SELL"
        price = 0.00043820
        amount = 100000
        await ace.submit_order(symbol='SHIB_TWD', side=side, price=price, amount=amount, type_=1)
        time.sleep(2)

import random
async def test_order(apiKey, securityKey):
    ace = Spot(key=apiKey, secret=securityKey, mode='testnet')
    start = time.time()
    for i in range(1, 10000, 100):
        r = await ace.get_trades_history('AXS_USDT', size=100, start=i)
        if r[0]['currencyNameEn'] == 'AXS':
            print(r)
            print("------------")

async def get_account_balance(symbol, apiKey, securityKey):
    ace = Spot(key=apiKey, secret=securityKey, mode='testnet')
    r = await ace.account_balance(symbol)
    print(r)

async def cancel_all_orders(symbol,apiKey, securityKey):
    ace = Spot(key=apiKey, secret=securityKey, mode='testnet')
    await ace.cancel_all_order(symbol)

async def get_orders(symbol,apiKey, securityKey):
    ace = Spot(key=apiKey, secret=securityKey, mode='testnet')
    open_orders = await ace.get_open_orders(symbol)
    print("open orders:", open_orders)

async def get_orderbooks(symbol,apiKey, securityKey):
    ace = Spot(key=apiKey, secret=securityKey, mode='testnet')
    orderbook = await ace.get_orderbook(symbol)
    print("orderbook:", orderbook)

async def get_market_pairs(apiKey,securityKey):
    ace = Spot(key=apiKey, secret=securityKey, mode='production')
    mp = await ace.get_market_pair()
    print(mp)
def print_menu():
    print("Select a function to run:")
    print("1. Submit Unit Test")
    print("2. Test Order")
    print("3. Get Account Balance")
    print("4. Cancel All Orders")
    print("5. Get Orders")

async def main():
    apiKey, securityKey = credentials.apiKey, credentials.securityKey
    
    print_menu()
    choice = int(input("Enter choice (1-5): "))
    symbol = input("Enter symbol (e.g., DOGE_TWD): ") if choice in [3, 4, 5, 6] else None
    
    if choice == 1:
        await submit_unit_test(apiKey,securityKey)
    elif choice == 2:
        await test_order(apiKey,securityKey)
    elif choice == 3:
        await get_account_balance(symbol,apiKey,securityKey)
    elif choice == 4:
        await cancel_all_orders(symbol,apiKey,securityKey)
    elif choice == 5:
        await get_orders(symbol,apiKey,securityKey)
    elif choice == 6 :
        await get_orderbooks(symbol,apiKey,securityKey)
    elif choice == 7 :
        await get_market_pairs(apiKey,securityKey)
    else:
        print("Invalid choice. Please select a number between 1 and 5.")

if __name__ == "__main__":
    asyncio.run(main())