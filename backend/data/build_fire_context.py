"""Build a review sheet with transcript context for every unique pipeline fire."""
import json
from pathlib import Path

DATA = Path(__file__).parent
TRANSCRIPTS = DATA.parent.parent / "transcripts"

eval_data = json.loads((DATA / "pipeline_eval.json").read_text(encoding="utf-8"))

# union of fires keyed by (transcript, line); remember which configs fired it
fires = {}
for config, cfg in eval_data["configs"].items():
    for tname, tinfo in cfg["transcripts"].items():
        for fire in tinfo.get("unmatched", []):
            key = (tname, fire["line"])
            entry = fires.setdefault(key, {"tags": {}, "configs": [], "text": fire["text"], "timecode": fire["timecode"]})
            entry["configs"].append(config)
            entry["tags"][config] = fire["tag"]

# load transcripts
cache = {}
def get_lines(tname):
    if tname not in cache:
        cache[tname] = (TRANSCRIPTS / tname).read_text(encoding="utf-8").splitlines()
    return cache[tname]

out = []
total = 0
for (tname, line), entry in sorted(fires.items()):
    lines = get_lines(tname)
    i = line - 1  # eval line numbers are 1-based
    lo, hi = max(0, i - 6), min(len(lines), i + 7)
    total += 1
    short = tname.split("__")[0]
    cfgs = ",".join(sorted(set(entry["configs"])))
    tags = "/".join(sorted(set(entry["tags"].values())))
    out.append(f"### FIRE {total}: {short} L{line} [{entry['timecode']}] tag={tags} configs={cfgs}")
    for j in range(lo, hi):
        marker = ">>>" if j == i else "   "
        out.append(f"{marker} L{j+1}: {lines[j]}")
    out.append("")

(DATA / "fire_context_sheet.md").write_text("\n".join(out), encoding="utf-8")
print(f"unique fires: {total}")
per_cfg = {}
for entry in fires.values():
    for c in set(entry["configs"]):
        per_cfg[c] = per_cfg.get(c, 0) + 1
print("per config:", per_cfg)
