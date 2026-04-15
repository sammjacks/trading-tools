# Overlay Research Resume Notes

## Where we left off
This project is paused at the new overlay-trade research stage under the basket analysis workflow.

Main files:
- basket_analysis/basket_overlay_research.py
- basket_analysis/run_basket_analysis_5_overlay.cmd

## What is already done
- Step 4 Stage 2 filter optimization is implemented and working.
- Step 5 overlay research workflow was built for standalone add-on trades triggered by large baskets plus consolidation.
- The HTML report generator now shows separate bar-based and tick-verified equity charts.

## Best result so far
Best realistic result found so far was the EURUSD continuation-style overlay using full tick replay over 5 years.

Rule family:
- direction_mode: with_move
- entry_mode: next_open after consolidation
- min_positions: 8
- min_adverse_pips: 15
- consolidation_bars: 3
- consolidation_ratio: 0.30
- stop_mode: fixed
- stop_value: 20 pips
- take profit: 1.5R
- overlay lot used in research: 0.01

Verified 5-year EURUSD tick result:
- trades: 236
- wins: 81
- losses: 155
- win rate: 34.3%
- profit factor: 1.25
- net profit: +$41.23
- max equity drawdown: $17.46
- return / drawdown: 2.36

Report path:
- basket_analysis/OverlayResearch_EURUSD_5Y_Continuation/overlay_research.html

## Important finding
Bar-only optimisation can look much better than the spread-aware tick replay. The basket-side breakout retracement ideas looked strong on bars across EURUSD, USDCAD, and USDCHF, but much of that edge disappeared after full tick verification.

## User's current train of thought for next session
1. Optimise using ticks first, since the tick results differ a lot from bar results.
2. Use a smaller training sample, likely around 1 year, then test afterwards out-of-sample.
3. Search for higher win-rate systems in the same style, possibly by widening the stop loss.
4. Explore the same strategy idea on more markets.
5. Later build the Telegram / EA execution tools so the signal can actually be traded.

## Best next actions when resuming
1. Add a tick-first optimisation mode to the overlay research tool.
2. Split research into train/test windows, starting with about 1 year training plus later validation.
3. Run a wider-stop / higher-win-rate sweep on EURUSD first.
4. Repeat on more symbols and compare cross-market robustness.
5. Once a stable rule survives tick validation, define the execution spec for the Telegram bot / copier EA.

## Quick prompt to resume
If resuming later, ask:
"Right, remind me where we left off on the overlay research."
