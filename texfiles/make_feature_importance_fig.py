"""Regenerate feature_importance.png, the thesis figure "Top TF-IDF features
by logistic-regression coefficient", from the precomputed analysis results
(run with matplotlib installed, e.g. `uv run --with matplotlib python
make_feature_importance_fig.py`).

Uses English decimal points on the x-axis (0.00, 1.00, ...).
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter

RESULTS = Path(__file__).resolve().parent.parent / "backend" / "data" / "analysis_results.json"
OUT = Path(__file__).resolve().parent / "feature_importance.png"

CLASSES = [("TRIM", "TRIM"), ("EXIT_ALL", "EXIT ALL"), ("MOVE_STOP", "MOVE STOP")]
TOP_K = 5

with open(RESULTS, encoding="utf-8") as f:
    importance = json.load(f)["feature_importance"]

fig, axes = plt.subplots(1, 3, figsize=(10.7, 4.45), dpi=200)
fig.suptitle("Top TF-IDF features by logistic-regression coefficient")

for ax, (key, title) in zip(axes, CLASSES):
    entries = importance[key][:TOP_K]
    features = [e["feature"] for e in entries][::-1]
    weights = [e["weight"] for e in entries][::-1]
    ax.barh(features, weights, color="steelblue")
    ax.set_title(title)
    ax.set_xlabel("Coefficient weight")
    ax.set_xlim(0, 6)
    ax.xaxis.set_major_formatter(FormatStrFormatter("%.2f"))
    ax.grid(axis="x", color="#dddddd", linewidth=0.8)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

fig.tight_layout(rect=(0, 0, 1, 0.93))
fig.savefig(OUT)
print(f"written: {OUT}")
