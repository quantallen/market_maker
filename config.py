import configparser
from decimal import Decimal
from binance.client import Client

def string_length(precision):
    return '0.' + '0' * (precision-1) + '1'

def remove_zeros(string):
    num = float(string)
    result = str(num).rstrip('0')
    if result[-1] == '.':
        result = result[:-1]
    return result

class BinanceConfig:
    def __init__(self, binance_client, binacnesymbol , acesymbol):
        self._load_config()
        self._SYMBOL = binacnesymbol
        self.ACE_SYMBOL = acesymbol
        self._initialize_binance_data(binance_client,self._SYMBOL)
        self._set_precisions()
        self._set_factors()
        print(self.BINANCE_SIZE_PRECISION, self.BINANCE_PRICE_PRECISION)
        print(self.SPREAD_DIFF, self.FEE)
    def _load_config(self):
        self.mm_config = configparser.ConfigParser()
        self.mm_config.read('./mm_config.ini')
    
    def _initialize_binance_data(self, binance_client,symbol):
        if binance_client:
            symbol_info = binance_client.get_symbol_info(symbol)
            self.MAX = float(symbol_info['filters'][1]['maxQty'])
            self.binance_notional_value = float(symbol_info['filters'][6]['minNotional'])
            print("BINANCE 最小交易單位 : ",self.binance_notional_value)
            self.BINANCE_SIZE_PRECISION = Decimal(remove_zeros(symbol_info['filters'][1]['stepSize']))
            self.BINANCE_PRICE_PRECISION = Decimal(remove_zeros(symbol_info['filters'][0]['tickSize']))

    def _set_precisions(self):
        symbol_key = self.ACE_SYMBOL.replace('_','')
        self.size_precision = self.mm_config[symbol_key]['amount_precision']
        self.price_precision = self.mm_config[symbol_key]['price_precision']
        self.SIZE_PRECISION = Decimal(string_length(int(self.size_precision)))
        self.PRICE_PRECISION = Decimal(string_length(int(self.price_precision)))
        print(self.SIZE_PRECISION, self.PRICE_PRECISION)

    def _set_factors(self):
        self.DECLINE_FACTOR = 0.0001
        self.AMOUNT_RATIO = 0.000001
        self.SPREAD_DIFF = 0.000005
        self.FEE = 0.002


if __name__ == "__main__":
    binance_client = Client()
    binacnesymbol = "BTCUSDT"  # Example symbol, change as needed
    acesymbol = "BTC_TWD"
    config = BinanceConfig(binance_client, binacnesymbol,acesymbol)