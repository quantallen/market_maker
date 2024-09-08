import subprocess
import sys

def tmux_exec(symbol_list):
    # 定義三個Python腳本的路徑
    script1_path = "/home/bitcoin/ace_maker/trade.py"
    script2_path = "/home/bitcoin/ace_maker/selftrade.py"
    #script3_path = "/home/bitcoin/ace_maker/hedge_binance.py"
    script_paths = [script1_path, script2_path]
    env_name = 'ace_maker'
    
    for base_symbol, alt_symbol in symbol_list:
        # 創建一個tmux窗口，每個symbol都有一個獨立的會話
        session_name = f"{base_symbol}_mmaker"
        subprocess.run(["tmux", "new-session", "-d", "-s", session_name])

        for i, script_path in enumerate(script_paths):
            if i == 0:
                # 第一個窗格，不需要拆分畫面
                subprocess.run(["tmux", "send-keys", "-t", session_name, f"conda activate {env_name}\n", "C-m"])
                subprocess.run(["tmux", "send-keys", "-t", session_name, f"python {script_path} -b {base_symbol} -a {alt_symbol}\n", "C-m"])
            else:
                # 拆分畫面，並進入新的窗格
                subprocess.run(["tmux", "split-window", "-h", "-t", session_name])
                subprocess.run(["tmux", "select-layout", "-t", session_name, "even-horizontal"])
                subprocess.run(["tmux", "send-keys", "-t", session_name, f"conda activate {env_name}\n", "C-m"])
                subprocess.run(["tmux", "send-keys", "-t", session_name, f"python {script_path} -b {base_symbol} -a {alt_symbol}\n", "C-m"])

        # 附加到會話
        #subprocess.run(["tmux", "attach-session", "-t", session_name])

if __name__ == "__main__":
    # if len(sys.argv) < 2:
    #     print("Usage: python script.py <symbol_list>")
    #     print("Example: python script.py BTCUSDT,BTC_TWD ETHUSDT,ETH_TWD")
    # else:
        # 將命令行的參數轉換為符號對的列表
        #symbol_list = [tuple(symbol.split(',')) for symbol in sys.argv[1:]]
        symbol_list = [
        ("ADAUSDT", "ADA_TWD"),
        #("APEUSDT", "APE_TWD"),
        # ("ARBUSDT", "ARB_TWD"),
          ("BTCUSDT", "BTC_TWD"),
        # ("BNBUSDT", "BNB_TWD"),
        # ("BONKUSDT", "BONK_TWD"),
        #  ("DOGEUSDT", "DOGE_TWD"),
        # ("DOTUSDT", "DOT_TWD"),
         ("ETHUSDT", "ETH_TWD"),
         ("FTMUSDT", "FTM_TWD"),
         ("GALAUSDT", "GALA_TWD"),
         ("LTCUSDT", "LTC_TWD"),
         ("MATICUSDT", "MATIC_TWD"),
         ("SANDUSDT", "SAND_TWD"),
         ("SHIBUSDT", "SHIB_TWD"),
         ("SOLUSDT", "SOL_TWD"),
         ("SSVUSDT", "SSV_TWD"),
         ("TRXUSDT", "TRX_TWD"),
         ("WOOUSDT", "WOO_TWD"),
         #("XRPUSDT", "XRP_TWD"),
    ]
        tmux_exec(symbol_list)