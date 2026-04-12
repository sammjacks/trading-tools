# How to Work With the User

## Communication style they prefer

- **Direct and technical**. They know their domain deeply (quant trading,
  basket EAs, MT4/MT5) and don't need the basics explained.
- **Concrete, no fluff**. Skip preamble like "Great question!" or "I'd
  be happy to help with that". Get to the work.
- **Concise prose for explanations**. Bullet points are fine for
  enumerating options, but lean on prose for explanations and reasoning.
- **No emoji** unless they use them first. They don't.
- **Honest about uncertainty**. If you ship code you couldn't fully
  test, say "untested" explicitly. Don't claim things work when you
  can't verify them.

## How they work

- **Iterative**. They describe one feature, you build it, they run it
  and report results, you fix or extend. Don't try to anticipate 5
  features ahead.
- **They will push back**. If something doesn't work after you say it
  does, they will tell you and expect a real root-cause investigation,
  not symptom patches.
- **They send screenshots**. When something's wrong they upload a
  screenshot of the error or output. Look at it carefully — the answer
  is often visible.
- **They send their cmd files when there's an issue**. Read these
  carefully because the bug is sometimes in their config (typo in
  symbol, wrong file extension, comment header without REM) rather
  than in the Python code.
- **They want minimal config friction**. Each cmd file should make
  it as easy as possible to enable/disable strategies, change paths,
  tweak optimization parameters. They've explicitly asked for things
  like "don't make me set the same path 8 times" and "auto-derive
  bars file from symbol".

## Things to do well

### Investigate carefully before fixing
When they report a bug:
1. Read the screenshot/error carefully
2. Check if the bug could be in the user's input (cmd file typos,
   wrong file extensions, missing files) before assuming it's in the
   code
3. If it's in the code, write a small reproduction script and verify
   the bug exists before changing anything
4. Fix the root cause, not the symptom
5. Add a test or sanity check that would catch the same bug in
   the future

### Example: GBPUSD lot bug
The user reported "GBPUSD lot size is 0.03". Investigation:
1. Looked at the GBPUSD MT5 file
2. Ran a script that printed the lot size distribution: `0.01: 414
   trades (73%)`, `0.03: 98 trades (17%)`, etc.
3. First trade was 0.03, which my code was reading as base_lot
4. Fix: use `Counter.most_common(1)` to get the mode instead
5. Verified: GBPUSD now shows 0.01 like the user expected

### Example: Backtest dip invisible bug
The user reported "the backtest dip isn't shown on the chart" multiple
times across multiple turns. I tried several rendering tweaks (no
smoothing, dashed lines, point markers, color changes) without
success. Finally:
1. Rendered the data in matplotlib to confirm the dip was actually
   in the data
2. Looked at the user's uploaded HTML file vs the script output
3. Realized the user's HTML file only had 2 canvases but my script
   was generating 4 canvases — they were running an old version of
   my script
4. Confirmed by greping their uploaded file for canvas count
5. Real fix: add separate "Backtest equity (alone)" and "Live equity
   (alone)" panels so each curve is fully visible without overlap

### Example: dollar sign in cmd file
When generating cmd files for the user, watch for `%%` escaping in
batch comments. `10%%` shows as `10%` after batch processing but if
you put `10%` in a comment it can confuse cmd parsing. Use plain
text descriptions like "10 percent" instead of percent signs in
comments.

### Code quality expectations
- **Comments explain WHY, not what**. The user reads the code.
- **Use docstrings on functions**. They explain the logic.
- **Don't be clever**. Plain readable code beats compact code.
- **Handle the edge cases**. Empty lists, missing data, division
  by zero, etc.
- **Don't break working features when adding new ones**. Always
  verify existing functionality still works after a change.

## Things to avoid

- **Don't use emoji**. They never have.
- **Don't use sycophantic phrases**. "Great question!", "Absolutely!",
  "I'd be happy to help" — all unwelcome.
- **Don't make them ask twice**. If they tell you something needs to
  change, change it; don't argue or rationalize the existing behavior.
- **Don't ship without verifying**. If you can test it, test it. If
  you can't test it (e.g., needs Windows-only behavior), say so
  explicitly.
- **Don't overstate confidence**. "I'm pretty sure this works" is
  better than "this works" if you didn't test it.
- **Don't write essays**. Reports should be terse: what changed, why,
  any caveats. Skip the marketing.

## Tool usage notes

- The user runs Windows. Use Windows path separators (`\`) and `.cmd`
  files. Don't write bash scripts unless explicitly asked.
- Test files available in `/mnt/user-data/uploads/` for verification:
  - `Statement.htm` — MT4 live statement (EURUSD)
  - `StrategyTester.htm` — MT4 strategy tester report (EURUSD)
  - `Market_Master_EURUSD_H1.html` — MT5 strategy tester report
  - `Hexaflow8_settingsgbpusdh1.htm` — MT5 strategy tester report
  - `EURUSD_GMT_2_US-DST_M1.csv` — M1 bars
  - `EURUSD_GMT_0_NO-DST_1week.csv` — 1 week of tick data
- The xlsx skill is available at `/mnt/skills/public/xlsx/` and the
  recalc script at `/mnt/skills/public/xlsx/scripts/recalc.py` should
  always be run after generating xlsx files to confirm 0 formula errors.
- When making changes to existing files, use `str_replace` rather
  than rewriting the entire file. The user's files are large (~3000
  lines) and full rewrites are slow and error-prone.

## Project state markers

When the user says "checkpoint" or "checkpoint reminder", they mean:
they want to mark a logical pause in the work and return to it later.
At each pause point, summarize what's done, what's pending, and where
to pick up. The user appreciates being able to pause and resume
without losing context.

## Recent context notes

The most recent work was on Step 4 of the basket_analysis tool —
filter optimization. This is "stage 1" of a multi-stage filter
exploration project. Stage 2 will probably add basket SL and EOD
close to the filter grid, but isn't started yet. The user explicitly
said they wanted to do this in two stages.
