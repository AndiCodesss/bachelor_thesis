"""Full-stream evaluation: replay complete held-out transcripts through the best model.

The five-fold benchmark (benchmark_models.py) measures performance only on the
curated, action-enriched set of labelled lines. This script answers the
complementary question the thesis raises in its limitations: what does the
classifier do when it sees EVERY line of a real session?

Procedure:
  1. Train TF-IDF + logistic regression (the benchmark's best model, identical
     hyperparameters) on the cleaned dataset EXCLUDING the five held-out test
     transcripts (the same transcripts shipped as examples in transcripts/).
  2. Replay each test transcript line by line with the same machinery that
     built the training prompts (ai_transcript_annotator.build_training_examples):
     the rule interpreter supplies the recent/analysis context windows, and the
     position state evolves by applying the labelled actions as they occur
     (oracle state, exactly as during dataset construction).
  3. Predict an action for every timestamped line.

Reported:
  - Detection recall on the labelled action lines of those transcripts.
  - The volume of action predictions ("fires") on unlabelled lines, per hour.
    Unlabelled lines have no ground truth (the dataset has incomplete action
    coverage), so these fires are exported to a Markdown review sheet for
    manual judgement instead of being auto-counted as false positives.

Run from backend/:  python -m app.services.interpretation.fullstream_eval
Outputs:            data/fullstream_eval.json, data/fullstream_review.md
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime
from pathlib import Path

from app.models.domain import ActionTag, MarketSnapshot, SessionConfig, StreamSession, TradeSide
from app.services.interpretation.ai_transcript_annotator import (
    AiAnnotation,
    _apply_annotation_state,
    _timestamped_lines,
)
from app.services.interpretation.benchmark_models import LABELS, _LABEL_TO_ID
from app.services.interpretation.intent_context import _clip
from app.services.interpretation.rule_engine import RuleBasedTradeInterpreter, _normalize
from app.services.interpretation.train_local_classifier import (
    _example_file_key,
    _load_examples,
    _rebalance_training_examples,
)

# The five held-out test transcripts (the deployed classifier's test split,
# committed to the repository as example transcripts).
TEST_BASENAMES = (
    "2025-10-07__LIVE-DAY-TRADING-Nasdaq-Futures-Scalping-NQ-Order-Flow-Price-Action-Oct-07__rilljaZdaww.txt",
    "2025-10-23__LIVE-DAY-TRADING-Nasdaq-Futures-Scalping-NQ-Order-Flow-Price-Action-Oct-23__nFvjz1D-Oas.txt",
    "2025-11-06__LIVE-DAY-TRADING-Nasdaq-Futures-Scalping-NQ-Order-Flow-Price-Action-Nov-06__Luatve1nc1M.txt",
    "2025-11-07__LIVE-DAY-TRADING-Nasdaq-Futures-Scalping-NQ-Order-Flow-Price-Action-Nov-07__KUhMYgRYfE8.txt",
    "2025-11-14__LIVE-DAY-TRADING-Nasdaq-Futures-Scalping-NQ-Order-Flow-Price-Action-Nov-14__PG2wjhIe-f4.txt",
)

_ACTION_LABELS = {label.value for label in LABELS if label is not ActionTag.no_action}
_SIDE_FROM_LABEL = {"ENTER_LONG": TradeSide.long, "ENTER_SHORT": TradeSide.short}


def _train_model(train_examples: list[dict]):
    """TF-IDF + logistic regression with the exact benchmark configuration.

    Mirrors benchmark_models.TfidfLogReg; built inline because the review sheet
    needs predict_proba, which the benchmark wrapper does not expose.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression

    vectorizer = TfidfVectorizer(max_features=20_000, ngram_range=(1, 2), sublinear_tf=True)
    classifier = LogisticRegression(max_iter=1000, class_weight="balanced", C=1.0)
    texts = [ex["prompt"] for ex in train_examples]
    labels = [_LABEL_TO_ID[ex["label"]] for ex in train_examples]
    classifier.fit(vectorizer.fit_transform(texts), labels)
    return vectorizer, classifier


def _annotation_from_example(example: dict) -> AiAnnotation:
    """Wrap a labelled dataset example so _apply_annotation_state can replay it."""
    label = ActionTag(example["label"])
    side = _SIDE_FROM_LABEL.get(example["label"])
    if side is None:
        side_token = str(example.get("position_side") or "").upper()
        side = TradeSide.long if side_token == "LONG" else TradeSide.short if side_token == "SHORT" else None
    return AiAnnotation(
        file=example.get("file", ""),
        line=int(example["line"]),
        timecode=str(example.get("timecode", "")),
        label=label,
        side=side,
        confidence=1.0,
        evidence_text="",
        reason=None,
        chunk_index=0,
        chunk_start_line=0,
        chunk_end_line=0,
        current_text=str(example.get("current_text", "")),
    )


def _render_prompt(*, symbol: str, position: str, last_side: str, recent: str | None, analysis: str, current_normalized: str, current_raw: str) -> str:
    """Render a prompt in the exact format of the cleaned training data.

    Matches IntentContextEnvelope.render() followed by the cleanup rebuild
    (cleanup_training_data._rebuild_prompt), which keeps only the recent,
    analysis, and current text fields.
    """
    lines = [f"symbol={symbol}", f"position={position}", f"last_side={last_side}"]
    if recent:
        lines.append(f"recent={_clip(recent)}")
    if analysis and analysis != current_normalized:
        lines.append(f"analysis={_clip(analysis)}")
    lines.append(f"current={_clip(current_raw)}")
    return "\n".join(lines)


def _side_token(value: object, *, default: str) -> str:
    """Side fields arrive as TradeSide enums or plain strings depending on the model layer."""
    if value is None:
        return default
    return str(getattr(value, "value", value)).upper()


def _replay_transcript(path: Path, truth_by_line: dict[int, dict], symbol: str) -> list[dict]:
    """Replay one transcript and return one record per timestamped line."""
    interpreter = RuleBasedTradeInterpreter()
    session = StreamSession(
        config=SessionConfig(symbol=symbol, enable_ai_fallback=False),
        market=MarketSnapshot(symbol=symbol, last_price=24_600.0),
    )
    rows = _timestamped_lines(path)
    records: list[dict] = []

    for row in rows:
        normalized = _normalize(row.text)
        state_before = interpreter._get_state(session.id, mutate_state=False)
        analysis_text = interpreter._analysis_text(state_before, text=normalized, received_at=row.received_at)

        position = _side_token(session.position.side, default="FLAT") if session.position is not None else "FLAT"
        last_side = _side_token(state_before.last_side, default="NONE")
        prompt = _render_prompt(
            symbol=symbol,
            position=position,
            last_side=last_side,
            recent=state_before.recent_text,
            analysis=analysis_text,
            current_normalized=normalized,
            current_raw=row.text,
        )
        records.append(
            {
                "line": row.line,
                "timecode": row.timecode,
                "text": row.text,
                "prompt": prompt,
                "truth": truth_by_line.get(row.line, {}).get("label"),
            }
        )

        state = interpreter._get_state(session.id, mutate_state=True)
        state.recent_text = normalized
        state.recent_text_at = row.received_at
        truth = truth_by_line.get(row.line)
        if truth is not None:
            _apply_annotation_state(
                session=session, state=state, annotation=_annotation_from_example(truth)
            )

    return records


def _duration_hours(records: list[dict]) -> float:
    if len(records) < 2:
        return 0.0
    def seconds(timecode: str) -> int:
        hh, mm, ss = (int(part) for part in timecode.split(":"))
        return hh * 3600 + mm * 60 + ss
    return max(0.0, (seconds(records[-1]["timecode"]) - seconds(records[0]["timecode"])) / 3600.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/training_data_clean.jsonl"))
    parser.add_argument("--transcripts-dir", type=Path, default=Path("../transcripts"))
    parser.add_argument("--out-json", type=Path, default=Path("data/fullstream_eval.json"))
    parser.add_argument("--out-review", type=Path, default=Path("data/fullstream_review.md"))
    parser.add_argument(
        "--review-sample",
        type=int,
        default=20,
        help="Fires sampled per transcript for the manual review sheet (seeded, reproducible).",
    )
    args = parser.parse_args()

    examples, deduplicated = _load_examples(args.dataset)
    train_examples = [ex for ex in examples if Path(_example_file_key(ex)).name not in TEST_BASENAMES]
    truth_examples = [ex for ex in examples if Path(_example_file_key(ex)).name in TEST_BASENAMES]
    symbol = str(truth_examples[0].get("symbol") or "MNQ 03-26") if truth_examples else "MNQ 03-26"

    train_examples, retained_no_action = _rebalance_training_examples(
        train_examples, no_action_ratio=2.5, max_no_action_examples=6_000
    )
    print(
        f"dataset: {len(examples)} examples ({deduplicated} collapsed at load); "
        f"train={len(train_examples)} after rebalance, truth lines on test transcripts={len(truth_examples)}"
    )
    vectorizer, classifier = _train_model(train_examples)

    truth_by_file: dict[str, dict[int, dict]] = {}
    for ex in truth_examples:
        truth_by_file.setdefault(Path(_example_file_key(ex)).name, {})[int(ex["line"])] = ex

    summary: dict = {"transcripts": {}, "totals": {}}
    review_lines: list[str] = [
        "# Full-stream review sheet",
        "",
        f"A seeded random sample of {args.review_sample} action predictions (\"fires\") per",
        "transcript, drawn from all fires of the TF-IDF logistic regression on",
        "UNLABELLED lines of the five held-out test transcripts. For each entry, tick",
        "the checkbox if the trader really performed a trade action at that moment",
        "(any action, even if the predicted type is wrong); leave it unticked if it",
        "is a false alarm. The ticked fraction estimates full-stream precision.",
        "",
    ]
    rng = random.Random(42)

    totals = {
        "lines": 0,
        "hours": 0.0,
        "labelled_actions": 0,
        "labelled_actions_detected": 0,
        "labelled_actions_exact": 0,
        "labelled_no_action": 0,
        "labelled_no_action_correct": 0,
        "unlabelled_fires": 0,
    }

    for basename in TEST_BASENAMES:
        path = args.transcripts_dir / basename
        truth_by_line = truth_by_file.get(basename, {})
        records = _replay_transcript(path, truth_by_line, symbol)
        prompts = [record["prompt"] for record in records]
        probabilities = classifier.predict_proba(vectorizer.transform(prompts))
        for record, row_probs in zip(records, probabilities, strict=True):
            best = int(row_probs.argmax())
            record["pred"] = LABELS[best].value
            record["confidence"] = round(float(row_probs[best]), 4)

        hours = _duration_hours(records)
        labelled_actions = [r for r in records if r["truth"] in _ACTION_LABELS]
        labelled_no_action = [r for r in records if r["truth"] == ActionTag.no_action.value]
        unlabelled_fires = [r for r in records if r["truth"] is None and r["pred"] in _ACTION_LABELS]

        # Replay-fidelity check: at the labelled lines, the replayed prompt should
        # reproduce the stored training prompt (same machinery, same oracle state).
        prompt_matches = sum(
            1
            for r in records
            if r["truth"] is not None
            and r["prompt"].strip() == str(truth_by_line[r["line"]].get("prompt", "")).strip()
        )

        stats = {
            "lines": len(records),
            "hours": round(hours, 2),
            "labelled_actions": len(labelled_actions),
            "labelled_actions_detected": sum(1 for r in labelled_actions if r["pred"] in _ACTION_LABELS),
            "labelled_actions_exact": sum(1 for r in labelled_actions if r["pred"] == r["truth"]),
            "labelled_no_action": len(labelled_no_action),
            "labelled_no_action_correct": sum(
                1 for r in labelled_no_action if r["pred"] == ActionTag.no_action.value
            ),
            "unlabelled_fires": len(unlabelled_fires),
            "fires_per_hour": round(len(unlabelled_fires) / hours, 1) if hours else None,
            "prompt_matches": f"{prompt_matches}/{len(truth_by_line)}",
            # Production only acts above its confidence gate (risk engine
            # min_confidence = 0.74), so fire counts at thresholds matter more
            # for deployment than the raw count.
            "fires_at_confidence": {
                "0.5": sum(1 for r in unlabelled_fires if r["confidence"] >= 0.5),
                "0.74": sum(1 for r in unlabelled_fires if r["confidence"] >= 0.74),
                "0.9": sum(1 for r in unlabelled_fires if r["confidence"] >= 0.9),
            },
            "fires_by_label": {},
            "fires": [
                {k: r[k] for k in ("line", "timecode", "text", "pred", "confidence")}
                for r in unlabelled_fires
            ],
            "labelled_detail": [
                {k: r[k] for k in ("line", "timecode", "text", "truth", "pred", "confidence")}
                for r in records
                if r["truth"] is not None
            ],
        }
        for r in unlabelled_fires:
            stats["fires_by_label"][r["pred"]] = stats["fires_by_label"].get(r["pred"], 0) + 1
        summary["transcripts"][basename] = stats

        for key in ("lines", "labelled_actions", "labelled_actions_detected", "labelled_actions_exact",
                    "labelled_no_action", "labelled_no_action_correct", "unlabelled_fires"):
            totals[key] += stats[key]
        totals["hours"] += hours

        print(
            f"{basename[:50]}...: {stats['lines']} lines / {stats['hours']} h | "
            f"labelled actions {stats['labelled_actions_detected']}/{stats['labelled_actions']} detected "
            f"({stats['labelled_actions_exact']} exact) | fires on unlabelled lines: "
            f"{stats['unlabelled_fires']} ({stats['fires_per_hour']}/h)"
        )

        review_lines.append(f"## {basename}")
        review_lines.append("")
        by_line = {r["line"]: r for r in records}
        sampled = sorted(
            rng.sample(unlabelled_fires, min(args.review_sample, len(unlabelled_fires))),
            key=lambda r: r["line"],
        )
        for fire in sampled:
            before = by_line.get(fire["line"] - 1, {}).get("text", "")
            after = by_line.get(fire["line"] + 1, {}).get("text", "")
            review_lines.append(
                f"- [ ] L{fire['line']} `{fire['timecode']}` **{fire['pred']}** "
                f"(p={fire['confidence']:.2f}): {before} | **{fire['text']}** | {after}"
            )
        review_lines.append("")

    totals["hours"] = round(totals["hours"], 2)
    totals["fires_per_hour"] = round(totals["unlabelled_fires"] / totals["hours"], 1) if totals["hours"] else None
    summary["totals"] = totals
    summary["generated"] = datetime.now().isoformat(timespec="seconds")
    summary["train_examples"] = len(train_examples)
    summary["retained_no_action"] = retained_no_action

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    args.out_review.write_text("\n".join(review_lines), encoding="utf-8")

    print(
        f"\nTOTAL: {totals['lines']} lines over {totals['hours']} h | "
        f"labelled actions detected {totals['labelled_actions_detected']}/{totals['labelled_actions']} "
        f"({totals['labelled_actions_exact']} exact label) | "
        f"fires on unlabelled lines {totals['unlabelled_fires']} ({totals['fires_per_hour']}/h)"
    )
    print(f"summary -> {args.out_json}\nreview sheet -> {args.out_review}")


if __name__ == "__main__":
    main()
