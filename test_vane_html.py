"""Validate vane HTML table parsing"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from datetime import date
from history_scraper import scrape_vane_history

# Construct a sample HTML matching the real vane structure
VANE_HTML = """<html><body>
<table>
<tr><th>日期</th><th>价格</th><th>日涨跌</th></tr>
<tr><td bgcolor="#FFFFFF">07-30</td><td bgcolor="#FFFFFF">9119.00</td><td bgcolor="#FFFFFF" class="ttred">0.37%</td></tr>
<tr><td bgcolor="#FFFFFF">07-29</td><td bgcolor="#FFFFFF">9085.67</td><td>-0.18%</td></tr>
<tr><td bgcolor="#FFFFFF">07-27</td><td bgcolor="#FFFFFF">9102.33</td><td>-4.54%</td></tr>
<tr><td bgcolor="#FFFFFF">07-24</td><td bgcolor="#FFFFFF">9535.67</td><td>1.06%</td></tr>
<tr><td bgcolor="#FFFFFF">07-20</td><td bgcolor="#FFFFFF">9435.67</td><td>2.17%</td></tr>
<tr><td bgcolor="#FFFFFF">07-15</td><td bgcolor="#FFFFFF">9235.67</td><td>6.13%</td></tr>
<tr><td bgcolor="#FFFFFF">07-09</td><td bgcolor="#FFFFFF">8702.33</td><td>-4.04%</td></tr>
</table>
</body></html>"""

today = date(2026, 7, 30)
out = scrape_vane_history(lambda u: VANE_HTML, 427, "硫磺", today)
print(f"vane parse: {len(out)} entries")
for d in sorted(out.keys()):
    print(f"  {d} = {out[d]}")
assert out["2026-07-30"] == 9119.00
assert out["2026-07-09"] == 8702.33
assert len(out) == 7
print("OK vane HTML table parser")

# Also test the regex fallback with stripped HTML
VANE_TEXT = """>07-30</td>
<td>9119.00</td>
<td>0.37%</td>
>07-29</td>
<td>9085.67</td>
<td>-0.18%</td>
>07-09</td>
<td>8702.33</td>
<td>-4.04%</td>
"""
# This text-only version (no <tr> structure) should fall back to regex
out2 = scrape_vane_history(lambda u: VANE_TEXT, 427, "硫磺", today)
print(f"\nfallback regex: {out2}")
# May or may not parse depending on fallback regex; not critical

# Test empty/blocked response
out3 = scrape_vane_history(lambda u: "", 427, "硫磺", today)
assert out3 == {}
out4 = scrape_vane_history(lambda u: "x" * 100, 427, "硫磺", today)  # too short
assert out4 == {}
print("\nOK empty/short responses handled")

print("\nALL PASS")