import sys
sys.path.insert(0, r"c:\Users\sammj\Projects\trading-tools\stage3_portfolio_tick_check")
import importlib, types

# Patch TICK_SAMPLE_EVERY and FILES before loading
import custom_dd_analysis as m

# Override to AUDUSD only with sampling
m.TICK_SAMPLE_EVERY = 20
m.FILES = ["AUDUSD_M15.htm"]

import math
result = m.analyze_one("AUDUSD_M15.htm")
r = result

print("\n=== AUDUSD PREVIEW RESULTS (TICK_SAMPLE_EVERY=20) ===")
print(f"Symbol:               {r['symbol']}")
print(f"Equity Source:        {r['equity_source']}")
print()
print("--- BASE (all baskets) ---")
print(f"  Total Profit:       ${r['base']['total_profit']:,.2f}")
print(f"  Max Equity DD:      ${r['base']['max_equity_dd']:,.2f}")
rd = r['base']['rd_ratio']
rd_txt = 'inf' if math.isinf(rd) else f"{rd:.2f}"
print(f"  R/D Ratio:          {rd_txt}")
print(f"  Dyn Basket SL pips: {r['dynamic_basket_sl_pips_required_original']:.2f}")
print(f"  Worst 3 baskets (IDs): {[b['basket_id'] for b in r['base']['basket_dds'][:3]]}")
for b in r['base']['basket_dds'][:3]:
    print(f"    Basket {b['basket_id']:3d}: DD=${b['max_drawdown']:,.2f}  adverse_pips={b.get('max_adverse_pips',0):.2f}")
print()
print("--- FILTERED (ignore worst 3 baskets) ---")
print(f"  Total Profit:       ${r['filtered_ignore_worst3']['total_profit']:,.2f}")
print(f"  Max Equity DD:      ${r['filtered_ignore_worst3']['max_equity_dd']:,.2f}")
rd2 = r['filtered_ignore_worst3']['rd_ratio']
rd2_txt = 'inf' if math.isinf(rd2) else f"{rd2:.2f}"
print(f"  R/D Ratio:          {rd2_txt}")
print(f"  Dyn Basket SL pips: {r['dynamic_basket_sl_pips_required_after_ignoring3']:.2f}")
print()
print("Done.")
