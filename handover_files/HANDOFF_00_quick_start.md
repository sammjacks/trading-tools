# Quick Start — Paste this into the new chat

I'm continuing work on my trading analysis tools project. I have several
handoff documents and source files I'm uploading from the previous session:

**Documents:**
- `HANDOFF_01_project_overview.md` — what the project is and where it's at
- `HANDOFF_02_technical_reference.md` — architecture and key functions of both tools
- `HANDOFF_03_conversation_history.md` — chronological log of decisions and bug fixes
- `HANDOFF_04_working_with_user.md` — how I prefer to work and communicate

**Source files:**
- `basket_analysis.py` — single-strategy analysis tool (~2800 lines)
- `portfolio_backtest.py` — multi-strategy portfolio combining (~1700 lines)
- `run_basket_analysis_1_compare.cmd` through `_4_filter.cmd` — workflow steps
- `run_combine.cmd` — multi-pair combining
- `run_portfolio_backtest.cmd` — portfolio tool driver

Please read all four handoff documents first before responding so you
understand:
1. What the tools do and the architecture
2. The decisions and fixes already made (so we don't relitigate them)
3. How I prefer to work (terse, direct, no fluff, no emoji)

Then I'll tell you what I want to work on next. Most likely: continuing
the filter optimization work — stage 2 will add basket SL and EOD close
to the filter grid. But I might also have bug reports or refinements
based on running the latest version locally.
