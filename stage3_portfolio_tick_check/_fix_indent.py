content = open('custom_dd_analysis.py', 'r', encoding='utf-8').read()

# The broken block (append inside except, print/return inside for loop)
old_marker = '            except Exception:\n                continue\n                ts_arr.append(ts)\n                bid_arr.append(bid_val)\n                ask_arr.append(ask_val)\n'
new_marker = '            except Exception:\n                continue\n            ts_arr.append(ts)\n            bid_arr.append(bid_val)\n            ask_arr.append(ask_val)\n'

if old_marker in content:
    content = content.replace(old_marker, new_marker, 1)
    print('Fixed append indentation OK')
else:
    print('append marker not found')

# The print/return are inside the for loop (12 spaces) but should be at function body level (4 spaces)
old_ret = '            print(f"    tick load done: scanned={scanned:,} kept={len(ts_arr):,}  (~{len(ts_arr)*24//1024//1024} MB)", flush=True)\n            return (ts_arr, bid_arr, ask_arr)\n'
new_ret = '    print(f"    tick load done: scanned={scanned:,} kept={len(ts_arr):,}  (~{len(ts_arr)*24//1024//1024} MB)", flush=True)\n    return (ts_arr, bid_arr, ask_arr)\n'

if old_ret in content:
    content = content.replace(old_ret, new_ret, 1)
    print('Fixed print/return indentation OK')
else:
    print('print/return marker not found')
    # Show what we have around load done
    idx = content.find('tick load done')
    print(repr(content[idx-50:idx+150]))

open('custom_dd_analysis.py', 'w', encoding='utf-8').write(content)
print('Written.')
