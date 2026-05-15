"""
Universe of the top-100 most liquid US equities by market capitalisation
as of January 2016, held constant for the full 2016-2024 backtest window.

Source / methodology
--------------------
The S&P 100 (OEX) index as of January 2016 is used as a defensible proxy.
The OEX selects the 100 largest S&P 500 components with listed options,
which closely tracks "top-100 most liquid US equities by market cap" — the
criterion stated in DESIGN.md.  Point-in-time SPX membership data would be
more rigorous, but is not freely available; see DESIGN.md §Honest disclosures.

Ticker mapping
--------------
Two companies changed their ticker symbols after 2016 but continued trading
as the same economic entity.  We use the current Alpaca-compatible ticker so
the full 2016-2024 history is available under a single symbol:

  - META — traded as FB (Facebook) until October 2022.
  - BKNG — traded as PCLN (Priceline) until May 2018.

BRK.B (Berkshire Hathaway Class B) uses a period in its NYSE ticker; the
Alpaca API accepts this format.

Partial-history tickers
-----------------------
Several constituents were acquired or merged during the backtest window.
Their bars simply end at the event date; the engine treats missing bars as
"no position" for that symbol (no fill, no P&L).

  Ticker  Event                              Data through
  ------  ---------------------------------  ------------
  APC     Acquired by OXY, Aug 2019          Aug 2019
  CELG    Acquired by BMY, Nov 2019          Nov 2019
  DD      Merged into DowDuPont, Sep 2017;   Sep 2017 (gap until relisting 2019)
          relisted as new DuPont entity 2019
  DOW     Same merger as DD (Dow Chemical)   Sep 2017 (gap until relisting 2019)
  EMC     Acquired by Dell, Sep 2016         Sep 2016
  RTN     Merged into RTX, Apr 2020          Apr 2020
  TWX     Acquired by AT&T, Jun 2018         Jun 2018
  UTX     Merged into RTX, Apr 2020          Apr 2020
"""

UNIVERSE_2016: list[str] = [
    "AAPL", "ABBV", "ABT",   "ACN",   "AIG",
    "ALL",  "AMGN", "AMZN",  "APC",   "AXP",
    "BA",   "BAC",  "BIIB",  "BK",    "BLK",
    "BMY",  "BRK.B","C",     "CAT",   "CELG",
    "CI",   "CL",   "CMCSA", "COF",   "COP",
    "COST", "CSCO", "CVS",   "CVX",   "DD",
    "DE",   "DIS",  "DOW",   "DUK",   "EMC",
    "EMR",  "EXC",  "F",     "META",  "FDX",
    "GD",   "GE",   "GILD",  "GOOGL", "GS",
    "HAL",  "HD",   "HON",   "IBM",   "INTC",
    "JNJ",  "JPM",  "KHC",   "KO",    "LLY",
    "LMT",  "LOW",  "MA",    "MCD",   "MDLZ",
    "MDT",  "MET",  "MMM",   "MO",    "MRK",
    "MS",   "MSFT", "NKE",   "NOC",   "ORCL",
    "OXY",  "BKNG", "PEP",   "PFE",   "PG",
    "PM",   "PRU",  "QCOM",  "RTN",   "SBUX",
    "SLB",  "SO",   "SPG",   "SYK",   "T",
    "TGT",  "TWX",  "TXN",   "UNH",   "UNP",
    "UPS",  "USB",  "UTX",   "V",     "VZ",
    "WBA",  "WFC",  "WMT",   "XOM",   "AVGO",
]
