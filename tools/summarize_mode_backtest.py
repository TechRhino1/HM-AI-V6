import json
from pathlib import Path

rep_dir = Path("reports/mode_backtest")
symbols = ["XAUUSD", "BTCUSD", "ETHUSD", "SOLUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCAD"]
styles = ["SWING", "DAY_TRADING", "SCALP"]

rows = []
for sym in symbols:
    for st in styles:
        p = rep_dir / f"{sym}__{st}.json"
        if p.exists():
            d = json.load(open(p, encoding="utf-8"))
            m = d.get("metrics", {})
            rows.append({
                "symbol": sym,
                "style": st,
                "bars": d.get("primary_bars", 0),
                "days": d.get("window_days", 0),
                "trades": d.get("n_trades", 0),
                "wr": float(m.get("win_rate_pct", 0.0) or 0.0),
                "exp_r": float(m.get("expectancy_r", 0.0) or 0.0),
                "total_r": float(m.get("total_r", 0.0) or 0.0),
                "pf": float(m.get("profit_factor", 0.0) or 0.0),
                "net_pnl": float(m.get("net_profit", 0.0) or 0.0),
                "max_dd_pct": float(m.get("max_drawdown_pct", 0.0) or 0.0),
            })

print(f"{'Symbol':8s} {'Style':12s} {'Trades':6s} {'WinRate':8s} {'Exp_R':8s} {'Total_R':9s} {'PF':6s} {'Net_USD':11s} {'MaxDD%':8s}")
print("-" * 82)
for r in rows:
    print(f"{r['symbol']:8s} {r['style']:12s} {r['trades']:6d} {r['wr']:6.1f}%  {r['exp_r']:+7.3f}R {r['total_r']:+8.2f}R {r['pf']:5.2f}  {r['net_pnl']:+10.2f}$ {r['max_dd_pct']:5.2f}%")

print("=" * 82)
# Style summaries
for st in styles:
    st_rows = [r for r in rows if r["style"] == st]
    tot_trades = sum(r["trades"] for r in st_rows)
    tot_r = sum(r["total_r"] for r in st_rows)
    avg_exp = tot_r / tot_trades if tot_trades else 0.0
    tot_pnl = sum(r["net_pnl"] for r in st_rows)
    avg_wr = sum(r["wr"] * r["trades"] for r in st_rows) / tot_trades if tot_trades else 0.0
    print(f"STYLE TOTAL {st:12s}: Trades={tot_trades:5d}  AvgWR={avg_wr:5.1f}%  TotalR={tot_r:+8.2f}R  AvgExpR={avg_exp:+6.3f}R  NetUSD={tot_pnl:+10.2f}$")

# Grand total
tot_trades = sum(r["trades"] for r in rows)
tot_r = sum(r["total_r"] for r in rows)
avg_exp = tot_r / tot_trades if tot_trades else 0.0
tot_pnl = sum(r["net_pnl"] for r in rows)
avg_wr = sum(r["wr"] * r["trades"] for r in rows) / tot_trades if tot_trades else 0.0
print(f"GRAND TOTAL OVERALL    : Trades={tot_trades:5d}  AvgWR={avg_wr:5.1f}%  TotalR={tot_r:+8.2f}R  AvgExpR={avg_exp:+6.3f}R  NetUSD={tot_pnl:+10.2f}$")
