# trading_tools_deribit
It turns out finding a profitable trading strategy in a market with close to zero barriers to entry is pretty hard. Therefore, I've turned to develop some custom tools to improve and automate trade execution, and plan to work my way up from there. 

This project aims to be the groundwork for an (semi-)automated trading system specific to Deribit Exchange (deribit.com). It is designed to allow for a variety of additional modules to be implemented on top of and integrated into this infrastructure, e.g. automated delta1 or options trading. Secondly, the project serves as a means for myself to enhance my programming skills, and learn a bit about fast live data processing. It is work in progress, there are lots of improvements to be implemented, particularly in terms of error handling and code documentation..

So far, it establishes a connection to the Deribit API and streams loads of data, which is then processed. 
It streams all options contracts order book information, some BTC-Perpetual Futures market data and user account data if API credentials are provided. 
Every minute, it takes a snapshot of all options contracts best bid and best offer, and stores these to a local PostgreSQL database. Additionally, it uses this data to create a linearly interpolated volatility surface for specific log moneyness and maturity values. This leads to comparable volatility estimates over time, albeit at debatable accuracy due to the simplistic method of linear interpolation (to be improved..).
The tool can furthermore gamma-hedge any options position in the users account dynamically via the Perpetual Futures contract, to be switched on and off with user CLI inputs.

Future additions (work in progress) are:
- full trading support for futures and options via CLI inputs
- algorithmic execution of desired options positions across different contracts
- fully automatic vega, theta, vanna hedging

Slightly further down the line:
- execution of automated D1 market making strategies
- ...

# Requirements:
- PostgreSQL v9+

Apart from numerous relatively standard Python packages, the project uses PostgreSQL in some modules. It is not vital as of now since most data is stored locally in memory for now, however there probably will be a few more modules depending on PostgreSQL in the near future. 
Currently, the saving of options best bid and offer, and the volatility index module depend on PostgreSQL. Any version 9+ will do.

# How to run:

1. Install PostgreSQL (+ set up a Database, schema and tables are created automatically when running the program)
2. Open an account on deribit.com
3. Create a pair of API keys on deribit.com
4. Store API key information and PostgreSQL database information in the settings.txt file
5. python3 -m venv [environment_name]
6. source [environment_name]/bin/activate
7. python3 run.py
