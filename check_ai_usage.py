# check_ai_usage.py
import json
import glob
import os

cache_files = glob.glob(".cache/results/*.json") or glob.glob("data/cache/*.json")
decisions = {}

if cache_files:
    print(f"Reading {len(cache_files)} cache files...")
    for fpath in cache_files:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
            decider = data.get("decided_by") or data.get("source") or "unknown"
            decisions[decider] = decisions.get(decider, 0) + 1
else:
    # Check your current submission.json or run log
    sub_path = "submission.json"
    if os.path.exists(sub_path):
        with open(sub_path, "r", encoding="utf-8") as f:
            sub = json.load(f)
            print(f"Loaded {len(sub)} items from {sub_path}")
            for eid, res in sub.items():
                decider = res.get("decided_by") or "in_submission"
                decisions[decider] = decisions.get(decider, 0) + 1

print("\n--- AI USAGE BREAKDOWN ---")
for src, count in decisions.items():
    pct = (count / max(sum(decisions.values()), 1)) * 100
    print(f"{src}: {count} ({pct:.1f}%)")
