"""Write pipeline fire verdicts and compute per-config counts."""
import json
from pathlib import Path

DATA = Path(__file__).parent

# (transcript-date, line): (verdict, reason)
V = {
    ("2025-10-07", 268): ("FALSE", "cautionary analysis about getting long"),
    ("2025-10-07", 371): ("FALSE", "negated: doesn't fancy getting long"),
    ("2025-10-07", 397): ("FALSE", "explicitly waiting, not entering"),
    ("2025-10-07", 501): ("FALSE", "describing other traders' stops"),
    ("2025-10-07", 646): ("FALSE", "plan: wants second leg down before long"),
    ("2025-10-07", 897): ("FALSE", "negated: would rather wait than get long"),
    ("2025-10-07", 1575): ("AMBIGUOUS", "recap of past scalp (took rest off BE earlier), reveals recent entry"),
    ("2025-10-07", 1590): ("FALSE", "market analysis, says flat and waiting"),
    ("2025-10-07", 1767): ("FALSE", "reading viewer Peter's exit; himself holding"),
    ("2025-10-07", 2095): ("FALSE", "conditional exit plan (if they reclaim)"),
    ("2025-10-07", 2260): ("AMBIGUOUS", "states being out now; exit happened earlier off-mic"),
    ("2025-10-07", 2326): ("FALSE", "regret about earlier take-off"),
    ("2025-10-07", 2936): ("FALSE", "advice: do not get short down here"),
    ("2025-10-07", 2945): ("FALSE", "hypothetical squeeze-long explanation"),
    ("2025-10-07", 2952): ("FALSE", "addressing trapped buyers rhetorically"),
    ("2025-10-07", 3145): ("FALSE", "negated: not getting short down here"),
    ("2025-10-07", 3486): ("FALSE", "'it's all out there' = information, not position"),
    ("2025-10-23", 1072): ("REAL", "small short entry announced two lines above"),
    ("2025-10-23", 1094): ("AMBIGUOUS", "recap: already cut that trade (first mention)"),
    ("2025-10-23", 1096): ("AMBIGUOUS", "recap: cut at break even (same event)"),
    ("2025-10-23", 1289): ("REAL", "announces being in short ('in this short')"),
    ("2025-10-23", 1304): ("REAL", "'I'm out of this now'"),
    ("2025-10-23", 1755): ("FALSE", "urging market to take out stops"),
    ("2025-10-23", 1895): ("REAL", "'I'm out of this now'"),
    ("2025-10-23", 2657): ("FALSE", "passive-buyer tape analysis"),
    ("2025-10-23", 2823): ("FALSE", "other traders stopped out"),
    ("2025-10-23", 2824): ("FALSE", "other traders stopped out"),
    ("2025-10-23", 3049): ("REAL", "trims into flush ('got to pay myself')"),
    ("2025-10-23", 3114): ("FALSE", "recap to chat: was short, called wrong way"),
    ("2025-10-23", 3488): ("FALSE", "generic advice on losing trades"),
    ("2025-10-23", 3515): ("FALSE", "denial: never told anyone to add short"),
    ("2025-10-23", 3592): ("FALSE", "advice: take profit into here"),
    ("2025-11-06", 526): ("AMBIGUOUS", "status reveal: already short from earlier"),
    ("2025-11-06", 553): ("FALSE", "negated: not playing long here"),
    ("2025-11-06", 565): ("FALSE", "regret: wanted to be short, missed it"),
    ("2025-11-06", 613): ("AMBIGUOUS", "fire mis-timed; real re-entry 4 lines earlier"),
    ("2025-11-06", 711): ("FALSE", "conditional exit plan"),
    ("2025-11-06", 1178): ("REAL", "just paid himself (trim)"),
    ("2025-11-06", 1360): ("FALSE", "sellers exhausted = market analysis"),
    ("2025-11-06", 1830): ("FALSE", "advice: pay yourself into this box"),
    ("2025-11-06", 2025): ("AMBIGUOUS", "first mention of stop-out on runner"),
    ("2025-11-06", 2267): ("FALSE", "educational recap of entry and stop-out"),
    ("2025-11-06", 2268): ("FALSE", "same recap continued"),
    ("2025-11-06", 2435): ("FALSE", "educational contrast about shorting"),
    ("2025-11-06", 2736): ("FALSE", "market buying commentary"),
    ("2025-11-06", 2786): ("FALSE", "day recap of trades"),
    ("2025-11-06", 2860): ("FALSE", "bias statement: short or rotational biased"),
    ("2025-11-06", 3309): ("FALSE", "market structure analysis"),
    ("2025-11-06", 3748): ("FALSE", "buy-pressure tape analysis"),
    ("2025-11-07", 157): ("FALSE", "caution advice about shorting lows"),
    ("2025-11-07", 559): ("FALSE", "tape commentary: a little buying"),
    ("2025-11-07", 808): ("FALSE", "sellers stepping in = market commentary"),
    ("2025-11-07", 864): ("AMBIGUOUS", "fire mis-timed; real entry 3 lines earlier"),
    ("2025-11-07", 1021): ("AMBIGUOUS", "explains TP that hit moments before"),
    ("2025-11-07", 1107): ("FALSE", "tape: strong selling"),
    ("2025-11-07", 1204): ("FALSE", "'flatten out' = market flattening, not exit"),
    ("2025-11-07", 1664): ("FALSE", "status: not in position, stopped out earlier"),
    ("2025-11-07", 1755): ("FALSE", "status: flat and waiting"),
    ("2025-11-07", 1820): ("FALSE", "day recap: got stopped out"),
    ("2025-11-07", 2284): ("FALSE", "other traders stopped out"),
    ("2025-11-07", 2421): ("FALSE", "tape: buying here"),
    ("2025-11-07", 2523): ("FALSE", "negated: not going to short this move"),
    ("2025-11-07", 2524): ("FALSE", "same negation"),
    ("2025-11-07", 2561): ("FALSE", "tape commentary above 28"),
    ("2025-11-07", 2616): ("FALSE", "deliberation: cut or add, no action"),
    ("2025-11-07", 2673): ("FALSE", "recap: attempt stopped out"),
    ("2025-11-07", 2819): ("FALSE", "tape: big selling"),
    ("2025-11-07", 2821): ("FALSE", "tape: huge selling"),
    ("2025-11-07", 2905): ("FALSE", "recap: stopped out on attempt"),
    ("2025-11-07", 3067): ("FALSE", "prop-account payout question, not a trade"),
    ("2025-11-07", 3306): ("FALSE", "general method explanation"),
    ("2025-11-07", 3308): ("FALSE", "same method explanation"),
    ("2025-11-14", 558): ("FALSE", "tape: some selling"),
    ("2025-11-14", 748): ("FALSE", "other traders stopped out"),
    ("2025-11-14", 912): ("FALSE", "negated: not getting short"),
    ("2025-11-14", 913): ("FALSE", "same negation"),
    ("2025-11-14", 1398): ("FALSE", "negated: no short, no entry still"),
    ("2025-11-14", 1563): ("FALSE", "tape: stronger selling"),
    ("2025-11-14", 1622): ("FALSE", "conditional short plan"),
    ("2025-11-14", 1806): ("FALSE", "market structure: node building"),
    ("2025-11-14", 2011): ("FALSE", "describing yesterday's management"),
    ("2025-11-14", 2226): ("REAL", "small entry 'tiny nibble versus 40'"),
    ("2025-11-14", 2233): ("REAL", "covers a little, stop gone break even"),
    ("2025-11-14", 2242): ("REAL", "stopped out at BE on rest"),
    ("2025-11-14", 2278): ("REAL", "'already taking some off'"),
    ("2025-11-14", 2370): ("REAL", "'currently flatten this now'"),
    ("2025-11-14", 2408): ("FALSE", "tape: aggressive selling"),
    ("2025-11-14", 2429): ("FALSE", "tape: more aggressive selling"),
    ("2025-11-14", 2525): ("FALSE", "advice: you have to pay yourself"),
    ("2025-11-14", 2546): ("FALSE", "urging market to wipe out level"),
    ("2025-11-14", 2572): ("REAL", "stops into break even"),
    ("2025-11-14", 2573): ("REAL", "same BE announcement (duplicate fire)"),
    ("2025-11-14", 2575): ("REAL", "same BE announcement (duplicate fire)"),
    ("2025-11-14", 2671): ("REAL", "'I'm flattening this'"),
    ("2025-11-14", 3432): ("FALSE", "conditional: BE if above red line"),
    ("2025-11-14", 3616): ("FALSE", "retrospective self-critique about missed long"),
    ("2025-11-14", 3633): ("FALSE", "tape selling + done for the day"),
    ("2025-11-14", 3749): ("FALSE", "levels review, no action"),
    ("2025-11-14", 3975): ("FALSE", "leaving the stream"),
}

eval_data = json.loads((DATA / "pipeline_eval.json").read_text(encoding="utf-8"))

per_config = {}
verdict_records = {}
for config, cfg in eval_data["configs"].items():
    counts = {"REAL": 0, "AMBIGUOUS": 0, "FALSE": 0, "total": 0}
    for tname, tinfo in cfg["transcripts"].items():
        date = tname.split("__")[0]
        for fire in tinfo.get("unmatched", []):
            verdict, reason = V[(date, fire["line"])]
            counts[verdict] += 1
            counts["total"] += 1
            verdict_records.setdefault(f"{date}:L{fire['line']}", {
                "verdict": verdict, "reason": reason, "tag_by_config": {},
            })["tag_by_config"][config] = fire["tag"]
    per_config[config] = counts

out = {
    "reviewer": "Claude (Fable 5), AI review with transcript context, 2026-06-12; verdicts checked and confirmed by the author",
    "unique_fires": len(V),
    "unique_counts": {
        "REAL": sum(1 for v, _ in V.values() if v == "REAL"),
        "AMBIGUOUS": sum(1 for v, _ in V.values() if v == "AMBIGUOUS"),
        "FALSE": sum(1 for v, _ in V.values() if v == "FALSE"),
    },
    "per_config_counts": per_config,
    "verdicts": verdict_records,
}
(DATA / "pipeline_review_verdicts.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print(json.dumps({"unique": out["unique_counts"], "per_config": per_config}, indent=2))
