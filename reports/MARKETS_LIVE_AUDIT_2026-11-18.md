# Markets live audit — 2026-11-18 16:09:30

Mode: in-process API handlers; direct fetches from nseindia.com and Yahoo (independent of jarvis.markets).

| Check | Served | Direct | Tolerance | Served as | Age | Result |
|---|---:|---:|---:|---|---:|---|
| NIFTY chain spot (NSE v3 underlying) | 25227.95 | 25227.95 | 0.15% | close nse:option-chain-v3@www.nseindia.in | 1756.8 | OK |
| NIFTY 25200 CE open interest | 88724 | 88724.0 | 2.0% | close nse:option-chain-v3@www.nseindia.in | 1756.8 | OK |
| NIFTY 25200 CE last price | 174.4 | 174.4 | 3.0% | close nse:option-chain-v3@www.nseindia.in | 1756.8 | OK |
| NIFTY 25200 PE open interest | 97165 | 97165.0 | 2.0% | close nse:option-chain-v3@www.nseindia.in | 1756.8 | OK |
| NIFTY 25200 PE last price | 150.5 | 150.5 | 3.0% | close nse:option-chain-v3@www.nseindia.in | 1756.8 | OK |
| India VIX (NSE allIndices) | 15.56 | 15.56 | 1.0% | close nse:allIndices@www.nseindia.in | 2356.9 | OK |
| NIFTY 50 (NSE allIndices) | 25227.95 | 25227.95 | 0.2% |   |  | OK |
| NIFTY BANK (NSE allIndices) | 62038.65 | 62038.65 | 0.2% |   |  | OK |
| DII net ₹cr 17-Nov-2026 (NSE) | 196.93 | 196.93 | 0.0% |   |  | OK |
| FII/FPI net ₹cr 17-Nov-2026 (NSE) | 4195.38 | 4195.38 | 0.0% |   |  | OK |
| RELIANCE price (Yahoo direct) | 1363.0 | 1363.0 | 0.3% | close yahoo:chart/RELIANCE.NS | 2429.6 | OK |
| HDFCBANK price (Yahoo direct) | 808.15 | 808.15 | 0.3% | close yahoo:chart/HDFCBANK.NS | 2430.4 | OK |
| AAPL price (Yahoo direct) | 351.91 | 351.91 | 0.3% | close yahoo:chart/AAPL | 49159.3 | OK |
| SENSEX price (Yahoo direct, cross-source) | 82031.81 | 82031.81 | 0.5% | close bse:ddlExpiry_IV@api.bseindia.com | 0.0 | OK |
| FII index futures long 2026-11-17 (NSCCL file) | 65568 | 65568 | 0.0% | eod nse:archive/nsccl/fao_participant_oi | 88764.5 | OK |
| FII index futures short 2026-11-17 (NSCCL file) | 130691 | 130691 | 0.0% | eod nse:archive/nsccl/fao_participant_oi | 88764.5 | OK |
| NIFTY 23-Nov-2026 future LTP (NSE live) | 25234.3 | 25234.3 | 0.3% | close nse:liveEquity-derivatives@www.nseindia.in | 1765.7 | OK |
| NIFTY 23-Nov-2026 future OI (NSE live) | 177593 | 177593.0 | 2.0% | close nse:liveEquity-derivatives@www.nseindia.in | 1765.7 | OK |
| Upcoming NSE events count (event-calendar) | 14 | 14 | 0.0% | eod nse:event-calendar@www.nseindia.in | 0.0 | OK |
| CFTC Euro FX non-commercial long 2026-11-10 (CFTC API) | 227478 | 227478.0 | 0.0% | eod cftc:publicreporting/6dca-aqww (Legacy COT, futures only) | 729567.7 | OK |
| CFTC Euro FX non-commercial short 2026-11-10 (CFTC API) | 363874 | 363874.0 | 0.0% | eod cftc:publicreporting/6dca-aqww (Legacy COT, futures only) | 729567.7 | OK |
| DXY (Yahoo direct) | 103.747 | 103.746 | 0.3% | stale yahoo:chart/DX-Y.NYB | 602.2 | OK |

**22 / 22 checks passed** in 17.0s. Tolerances allow for the seconds between the two fetches; FII/DII must match exactly.
