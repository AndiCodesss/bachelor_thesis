"""Regenerate frozen_encoder.png, the thesis figure "From text to prediction
with a frozen encoder", as a simple flow diagram (run with matplotlib installed)."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

fig, ax = plt.subplots(figsize=(11, 3.0), dpi=200)
ax.set_xlim(0, 11)
ax.set_ylim(0, 3)
ax.axis("off")

boxes = [
    (0.1, "Prompt text", '"position=LONG\n... take a\npartial"', "#f0f0f0", "#666666"),
    (2.3, "Tokenizer", "split text\ninto tokens", "#dce9f7", "#3a6ea5"),
    (4.5, "Frozen encoder", "768 numbers\nper token\n(not trained)", "#dce9f7", "#3a6ea5"),
    (6.7, "Average", "one summary\nvector of\n768 numbers", "#dce9f7", "#3a6ea5"),
    (8.9, "Trained head", "7 scores,\nhighest wins\n(trained)", "#fde3c8", "#c46a1b"),
]

W, H, Y = 1.9, 1.9, 0.45
for x, title, sub, fc, ec in boxes:
    ax.add_patch(FancyBboxPatch((x, Y), W, H, boxstyle="round,pad=0.06",
                                facecolor=fc, edgecolor=ec, linewidth=1.6))
    ax.text(x + W / 2, Y + H - 0.32, title, ha="center", va="center",
            fontsize=11.5, fontweight="bold", color="#222222")
    ax.text(x + W / 2, Y + H / 2 - 0.30, sub, ha="center", va="center",
            fontsize=9.5, color="#444444", linespacing=1.4)

for i in range(len(boxes) - 1):
    x0 = boxes[i][0] + W + 0.07
    x1 = boxes[i + 1][0] - 0.07
    ax.add_patch(FancyArrowPatch((x0, Y + H / 2), (x1, Y + H / 2),
                                 arrowstyle="-|>", mutation_scale=18,
                                 linewidth=1.6, color="#555555"))

ax.text(boxes[4][0] + W + 0.12, Y + H / 2, "label:\nTRIM", ha="left", va="center",
        fontsize=10.5, fontweight="bold", color="#c46a1b", linespacing=1.4)

fig.savefig("frozen_encoder.png", bbox_inches="tight", facecolor="white")
print("written frozen_encoder.png")
