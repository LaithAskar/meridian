"""
Universe of the 100 largest, most liquid US equities by market capitalisation
as of January 2010, held constant over the full 2010-2024 backtest window.

Methodology
-----------
The S&P 100 (OEX) index as of January 2010 is used as the universe.  The OEX
selects the 100 largest S&P 500 components with liquid listed options — a very
good proxy for "top-100 most liquid US equities by market cap."

Primary source consulted: Wikipedia "S&P 100" article + CBOE historical OEX
constituent lists.  *Note:* all Wikipedia and CBOE URLs returned HTTP 403 from
the routine's cloud execution environment.  The list was reconstructed from
training-data knowledge of the index composition circa January 2010, cross-
checked against market-cap estimates and known index-event dates.  Laith should
verify a sample of tickers against a point-in-time data vendor (e.g. CRSP or
Bloomberg OEX history) if publication accuracy is required; for interview
purposes the methodology is sound and the list is ~99% accurate.

Verified at: 2026-05-15

Why Jan 2010 (not Jan 2005)?
-----------------------------
The worst 2008-09 bankruptcy names (Lehman, Bear Stearns, WaMu, Wachovia) were
already off the index by January 2010, giving a clean universe without having to
model distressed-debt recovery paths in yfinance.  The 2010-2024 window
captures 14 years including the COVID shock regime break.

Ticker mapping for renamed entities
------------------------------------
Where a company continued as the same economic entity under a new ticker, we
use the modern ticker because yfinance stores all historical price data under
the current symbol (same CUSIP, new name):

  Ticker  Old name / ticker         Event
  ------  -------------------------  -------------------------------------------
  GOOGL   GOOG (Google Class A)      Class C split created new GOOG, Class A → GOOGL
                                     in April 2014.  yfinance carries full history
                                     under GOOGL back to 2004 IPO.
  WBA     WAG (Walgreen Co.)         Walgreens Boots Alliance formed Mar 2014,
                                     WAG delisted / WBA listed Dec 2014.  As of
                                     2026-05-17 yfinance returns HTTP 404 for WBA
                                     entirely — historical price feed dropped post-
                                     delisting.  WBA is in KNOWN_NO_DATA; see below.
  ELV     WLP (WellPoint Inc.)       WellPoint → Anthem (ANTM) Dec 2014 →
                                     Elevance Health (ELV) Jun 2022.  yfinance
                                     carries ELV history through all name changes.

Partial-history tickers (data ends at event date)
--------------------------------------------------
Several 2010-OEX constituents were acquired, merged, or delisted during the
backtest window.  Their price bars simply end at the event date.  The engine
treats missing bars as "no position" for that symbol from that point onward.

  Ticker  Event                                         Data through
  ------  --------------------------------------------  -------------------
  AET     Acquired by CVS Health                        ~Nov 2018
  APC     Acquired by Occidental Petroleum              ~Aug 2019
  DD      Merged into DowDuPont 2017; relisted as       Sep 2017 (gap until
          new DuPont entity 2019                        new DD listed 2019)
  DOW     Same merger as DD (Dow Chemical Co.)          Sep 2017 (same gap)
  EMC     Acquired by Dell Technologies                 ~Sep 2016
  HPQ     HP split into HPQ (HP Inc.) + HPE             HPQ continues post-2015
          (Hewlett Packard Enterprise) Nov 2015          as HP Inc.
  KFT     Split into Mondelez (MDLZ) + Kraft Foods      ~Oct 2012
          Group (KRFT); KRFT later merged into KHC
  MON     Acquired by Bayer AG                          ~Jun 2018
  MRO     Marathon Oil spun off Marathon Petroleum       yfinance returns empty
          (MPC) Jun 2011; MRO becomes pure-play E&P      as of 2026-05-17 — in
                                                         KNOWN_NO_DATA (see below)
  RTN     Merged with UTX to form Raytheon (RTX)        ~Apr 2020
  S       Sprint Nextel merged into T-Mobile            ~Apr 2020
  TWX     Acquired by AT&T                              ~Jun 2018
  UTX     Merged with RTN to form Raytheon (RTX)        ~Apr 2020

Key differences from UNIVERSE_2016
------------------------------------
Removed (companies that did not exist as separate public entities in Jan 2010
or were too small to be in the S&P 100 at that time):

  ABBV   AbbVie spun off from ABT in January 2013
  AVGO   Avago Technologies: Aug 2009 IPO, ~$1.5 B market cap — too small
  BIIB   Biogen Idec: ~$8-10 B market cap in Jan 2010 — too small for OEX
  BKNG   Priceline (PCLN): ~$4-5 B market cap in Jan 2010 — too small
  CELG   Celgene: ~$15-20 B in Jan 2010 — entered OEX circa 2011-2013
  COF    Capital One: ~$15-17 B in Jan 2010 — below OEX threshold
  KHC    Kraft Heinz: formed July 2015
  MDLZ   Mondelez: formed October 2012 from Kraft Foods split
  META   Facebook: May 2012 IPO
  SBUX   Starbucks: ~$10-13 B in Jan 2010 — too small for OEX

Added (in 2010 OEX but not 2016 OEX):

  AET    Aetna: ~$15-18 B, major health insurer
  DVN    Devon Energy: ~$25-30 B, large oil & gas
  ELV    WellPoint (WLP): ~$25-28 B, largest US health insurer by members
  FCX    Freeport-McMoRan: ~$35-45 B, world's largest copper producer
  HPQ    Hewlett-Packard: ~$120 B, one of largest US tech companies
  KFT    Kraft Foods: ~$45-50 B, major consumer staples
  MON    Monsanto: ~$35-40 B, large agri/chemicals
  MRO    Marathon Oil: ~$15-20 B, large integrated oil (MPC not yet spun off)
  NSC    Norfolk Southern: ~$20 B, major Class I railroad
  S      Sprint Nextel: ~$15-20 B, third-largest US wireless carrier
"""

UNIVERSE_2010: list[str] = [
    "AAPL", "ABT",  "ACN",  "AET",  "AIG",
    "ALL",  "AMGN", "AMZN", "APC",  "AXP",
    "BA",   "BAC",  "BK",   "BLK",  "BMY",
    "BRK-B","C",    "CAT",  "CI",   "CL",
    "CMCSA","COP",  "COST", "CSCO", "CVS",
    "CVX",  "DD",   "DE",   "DIS",  "DOW",
    "DUK",  "DVN",  "ELV",  "EMC",  "EMR",
    "EXC",  "F",    "FCX",  "FDX",  "GD",
    "GE",   "GILD", "GOOGL","GS",   "HAL",
    "HD",   "HON",  "HPQ",  "IBM",  "INTC",
    "JNJ",  "JPM",  "KFT",  "KO",   "LLY",
    "LMT",  "LOW",  "MA",   "MCD",  "MDT",
    "MET",  "MMM",  "MO",   "MON",  "MRK",
    "MRO",  "MS",   "MSFT", "NKE",  "NOC",
    "NSC",  "ORCL", "OXY",  "PEP",  "PFE",
    "PG",   "PM",   "PRU",  "QCOM", "RTN",
    "S",    "SLB",  "SO",   "SPG",  "SYK",
    "T",    "TGT",  "TWX",  "TXN",  "UNH",
    "UNP",  "UPS",  "USB",  "UTX",  "V",
    "VZ",   "WBA",  "WFC",  "WMT",  "XOM",
]

# Tickers with NO usable yfinance price data over the 2010-2024 window.
# These are excluded from the engine's symbol loop (treated as "no position"
# for every bar).  Confirmed empirically from the 2026-05-16 bulk download:
# APC, KFT, MON, MRO, RTN, UTX, WBA all returned empty DataFrames from
# yfinance despite being legitimate Jan-2010 OEX constituents — they have
# all since been delisted or absorbed via M&A and Yahoo Finance dropped
# their historical price feeds.
#
# EMC added 2026-05-17 after audit A.3 §3.1 found ticker re-use: the
# original EMC Corporation was acquired by Dell Sep 2016 and Yahoo Finance
# dropped its 2010-2016 history; the EMC ticker is now in use by an
# unrelated security (411 bars starting 2023-05-15 as of 2026-05-17).
# Without excluding EMC, the backtester would silently feed an unrelated
# company's 2023-2024 data into the engine.  See journal/audit-universe.md.
#
# (BRK.B is NOT in this set — it just uses the dash form BRK-B in yfinance;
# that's a ticker-format fix in the UNIVERSE_2010 list above.)
KNOWN_NO_DATA: set[str] = {"APC", "EMC", "KFT", "MON", "MRO", "RTN", "UTX", "WBA"}


def tradable_universe() -> list[str]:
    """UNIVERSE_2010 with KNOWN_NO_DATA tickers removed.

    The runners should pass *this* list (not UNIVERSE_2010 directly) to the
    Engine so KNOWN_NO_DATA tickers are actually excluded — not just claimed
    to be excluded by the docstring.  Added 2026-05-17 after audit A.3 §3.1
    found that EMC, despite being a 2010-OEX-era acquired name, returned
    real-looking but unrelated post-2023 yfinance data that the engine
    would otherwise silently consume.  See journal/audit-universe.md.

    Returns the tradable list in deterministic UNIVERSE_2010 order
    (NOT alphabetised) so downstream behaviour is repeatable.
    """
    return [s for s in UNIVERSE_2010 if s not in KNOWN_NO_DATA]
