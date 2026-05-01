#!/usr/bin/env python3
import subprocess
import sys

# Run the bar analysis and capture output
result = subprocess.run(
    [sys.executable, r"c:\Users\sammj\Projects\trading-tools\stage3_portfolio_tick_check\eurusd_fix_bars.py"],
    capture_output=True,
    text=True,
    timeout=120
)

# Write output to file
with open(r"c:\Users\sammj\Projects\trading-tools\stage3_portfolio_tick_check\eurusd_bar_diagnostic_output.txt", "w") as f:
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\n\nSTDERR:\n")
    f.write(result.stderr)
    f.write(f"\n\nReturn code: {result.returncode}\n")

print("Done - output written to eurusd_bar_diagnostic_output.txt")
