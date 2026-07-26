"""Full-stream evaluation of the ACTUAL production pipeline on held-out transcripts.

fullstream_eval.py measures what the standalone ML classifier does on every
line of a real session (answer: it fires constantly). This script asks the
question that matters for deployment: what does the real interpretation
pipeline do on the same sessions? It replays the five held-out test
transcripts through RuleBasedTradeInterpreter, the exact component that runs
in production (rule engine plus classifier veto/recovery), in three
configurations:

  1. rules-only          - the rule engine without any ML classifier
  2. rules + ModernBERT  - the production configuration (deployed artifacts)
  3. rules + TF-IDF      - the benchmark's best model (logistic regression)
                           plugged into the classifier slot instead

For each configuration it reports how many of the labelled actions in those
transcripts are detected (an action intent within +/-2 lines of the labelled
line) and how many additional intents fire per hour. Position state evolves
from the pipeline's own intents, as it would in live trading; the cloud LLM
fallback stays disabled.

Run from backend/:  python -m app.services.interpretation.pipeline_fullstream_eval
Outputs:            data/pipeline_eval.json, data/pipeline_review.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.models.domain import ActionTag, MarketSnapshot, PositionState, SessionConfig, StreamSession, TranscriptSegment
from app.services.interpretation.ai_transcript_annotator import _timestamped_lines
from app.services.interpretation.benchmark_models import LABELS
from app.services.interpretation.fullstream_eval import (
    TEST_BASENAMES,
    _render_prompt,
    _side_token,
    _train_model,
)
from app.services.interpretation.local_classifier import IntentClassifierPrediction, ModernBertIntentClassifier
from app.services.interpretation.rule_engine import RuleBasedTradeInterpreter
from app.services.interpretation.train_local_classifier import _example_file_key, _load_examples, _rebalance_training_examples

_ACTION_TAG_VALUES = {
    ActionTag.enter_long.value,
    ActionTag.enter_short.value,
    ActionTag.add.value,
    ActionTag.trim.value,
    ActionTag.exit_all.value,
    ActionTag.move_stop.value,
    ActionTag.move_to_breakeven.value,
}
_MATCH_WINDOW_LINES = 2


def _tag_value(tag: ActionTag | str) -> str:
    """Intent tags arrive as ActionTag enums or plain strings depending on the model layer."""
    return tag.value if isinstance(tag, ActionTag) else str(tag)


class TfidfVetoClassifier:
    """Duck-typed stand-in for ModernBertIntentClassifier backed by TF-IDF logreg.

    Renders the envelope in the cleaned-training-data prompt format (the format
    the logreg was trained on) and exposes the same prediction object the rule
    engine consumes for its veto/recovery decisions.
    """

    def __init__(self, vectorizer, classifier) -> None:
        self._vectorizer = vectorizer
        self._classifier = classifier

    def is_available(self) -> bool:
        return True

    def load_error(self) -> str | None:
        return None

    def runtime_info(self) -> dict[str, object]:
        return {"model_name": "tfidf-logreg"}

    def classify(self, envelope) -> IntentClassifierPrediction:
        prompt = _render_prompt(
            symbol=envelope.symbol,
            position=_side_token(envelope.position_side, default="FLAT"),
            last_side=_side_token(envelope.last_side, default="NONE"),
            recent=envelope.recent_text,
            analysis=envelope.analysis_text,
            current_normalized=envelope.current_normalized,
            current_raw=envelope.current_text,
        )
        probabilities = self._classifier.predict_proba(self._vectorizer.transform([prompt]))[0]
        probability_map = {LABELS[i]: round(float(p), 6) for i, p in enumerate(probabilities)}
        best = max(probability_map, key=probability_map.get)
        return IntentClassifierPrediction(
            tag=best,
            confidence=probability_map[best],
            probabilities=probability_map,
            thresholds={},
            model_name="tfidf-logreg",
        )

    def close(self) -> None:
        return None


async def _replay(path: Path, *, interpreter: RuleBasedTradeInterpreter, symbol: str) -> tuple[list[dict], float]:
    """Replay one transcript through the interpreter, simulating position state
    from the pipeline's own intents (same approach as transcript_batch_report)."""
    session = StreamSession(
        config=SessionConfig(symbol=symbol, enable_ai_fallback=False),
        market=MarketSnapshot(symbol=symbol, last_price=24_600.0),
    )
    rows = _timestamped_lines(path)
    intents: list[dict] = []

    for row in rows:
        segment = TranscriptSegment(session_id=session.id, text=row.text, received_at=row.received_at)
        intent = await interpreter.interpret(session, segment)
        if intent is None:
            continue
        tag = _tag_value(intent.tag)
        if tag not in _ACTION_TAG_VALUES:
            continue
        intents.append(
            {
                "line": row.line,
                "timecode": row.timecode,
                "tag": tag,
                "confidence": round(float(intent.confidence), 4),
                "text": row.text,
            }
        )

        # Simulate fills so management intents see realistic position context
        # (same approach as transcript_batch_report).
        if tag in {ActionTag.enter_long.value, ActionTag.enter_short.value} and intent.side is not None:
            session.position = PositionState(
                side=intent.side,
                quantity=1,
                average_price=intent.entry_price or session.market.last_price or 0.0,
                stop_price=intent.stop_price,
                target_price=intent.target_price,
            )
        elif tag == ActionTag.add.value and session.position is None and intent.side is not None:
            session.position = PositionState(
                side=intent.side,
                quantity=1,
                average_price=intent.entry_price or session.market.last_price or 0.0,
                stop_price=intent.stop_price,
                target_price=intent.target_price,
            )
        elif tag == ActionTag.exit_all.value:
            session.position = None
        elif tag == ActionTag.move_stop.value and session.position is not None and intent.stop_price is not None:
            session.position.stop_price = intent.stop_price
        elif tag == ActionTag.move_to_breakeven.value and session.position is not None:
            session.position.stop_price = session.position.average_price

    if len(rows) >= 2:
        def seconds(timecode: str) -> int:
            hh, mm, ss = (int(part) for part in timecode.split(":"))
            return hh * 3600 + mm * 60 + ss
        hours = max(0.0, (seconds(rows[-1].timecode) - seconds(rows[0].timecode)) / 3600.0)
    else:
        hours = 0.0
    return intents, hours


def _match_intents(intents: list[dict], truths: list[dict]) -> tuple[int, int, list[dict]]:
    """Greedy nearest-line matching of fired intents to labelled actions.

    Returns (detected, exact_label, unmatched_intents). A labelled action counts
    as detected when any action intent fires within +/-2 lines; an entry-side
    ADD intent counts as an exact match for an entry label.
    """
    remaining = list(intents)
    detected = 0
    exact = 0
    for truth in truths:
        line = int(truth["line"])
        candidates = [i for i in remaining if abs(i["line"] - line) <= _MATCH_WINDOW_LINES]
        if not candidates:
            continue
        best = min(candidates, key=lambda i: abs(i["line"] - line))
        remaining.remove(best)
        detected += 1
        truth_label = str(truth["label"])
        if best["tag"] == truth_label or (best["tag"] == ActionTag.add.value and truth_label.startswith("ENTER_")):
            exact += 1
    return detected, exact, remaining


async def _run_config(name: str, interpreter: RuleBasedTradeInterpreter, *, transcripts_dir: Path, truth_by_file: dict[str, list[dict]], symbol: str) -> dict:
    config_stats: dict = {"transcripts": {}, "totals": {}}
    totals = {"hours": 0.0, "intents": 0, "labelled_actions": 0, "detected": 0, "exact": 0, "unmatched_fires": 0}
    all_unmatched: list[tuple[str, dict]] = []

    for basename in TEST_BASENAMES:
        truths = [t for t in truth_by_file.get(basename, []) if t["label"] != ActionTag.no_action.value]
        intents, hours = await _replay(transcripts_dir / basename, interpreter=interpreter, symbol=symbol)
        detected, exact, unmatched = _match_intents(intents, truths)

        by_tag: dict[str, int] = {}
        for intent in intents:
            by_tag[intent["tag"]] = by_tag.get(intent["tag"], 0) + 1

        config_stats["transcripts"][basename] = {
            "hours": round(hours, 2),
            "intents": len(intents),
            "intents_by_tag": by_tag,
            "labelled_actions": len(truths),
            "detected": detected,
            "exact": exact,
            "unmatched_fires": len(unmatched),
            "fires_per_hour": round(len(unmatched) / hours, 1) if hours else None,
            "unmatched": unmatched,
        }
        totals["hours"] += hours
        totals["intents"] += len(intents)
        totals["labelled_actions"] += len(truths)
        totals["detected"] += detected
        totals["exact"] += exact
        totals["unmatched_fires"] += len(unmatched)
        all_unmatched.extend((basename, intent) for intent in unmatched)

    totals["hours"] = round(totals["hours"], 2)
    totals["fires_per_hour"] = round(totals["unmatched_fires"] / totals["hours"], 1) if totals["hours"] else None
    config_stats["totals"] = totals

    print(
        f"[{name}] intents={totals['intents']} | labelled actions detected "
        f"{totals['detected']}/{totals['labelled_actions']} ({totals['exact']} exact) | "
        f"unmatched fires {totals['unmatched_fires']} ({totals['fires_per_hour']}/h)"
    )
    config_stats["unmatched_flat"] = [
        {"file": basename, **intent} for basename, intent in all_unmatched
    ]
    return config_stats


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/training_data_clean.jsonl"))
    parser.add_argument("--transcripts-dir", type=Path, default=Path("../transcripts"))
    parser.add_argument("--out-json", type=Path, default=Path("data/pipeline_eval.json"))
    parser.add_argument("--out-review", type=Path, default=Path("data/pipeline_review.md"))
    parser.add_argument(
        "--configs",
        default="rules,modernbert,tfidf",
        help="Comma-separated subset of: rules, modernbert, tfidf.",
    )
    args = parser.parse_args()

    examples, _ = _load_examples(args.dataset)
    truth_by_file: dict[str, list[dict]] = {}
    for ex in examples:
        name = Path(_example_file_key(ex)).name
        if name in TEST_BASENAMES:
            truth_by_file.setdefault(name, []).append(ex)
    symbol = "MNQ 03-26"

    requested = [token.strip() for token in args.configs.split(",") if token.strip()]
    results: dict[str, dict] = {}

    for config in requested:
        if config == "rules":
            interpreter = RuleBasedTradeInterpreter()
        elif config == "modernbert":
            classifier = ModernBertIntentClassifier(get_settings())
            classifier.load()
            if not classifier.is_available():
                print(f"[modernbert] classifier unavailable: {classifier.load_error()}; skipping")
                continue
            interpreter = RuleBasedTradeInterpreter(local_classifier=classifier)
        elif config == "tfidf":
            train_examples = [
                ex for ex in examples if Path(_example_file_key(ex)).name not in TEST_BASENAMES
            ]
            train_examples, _ = _rebalance_training_examples(
                train_examples, no_action_ratio=2.5, max_no_action_examples=6_000
            )
            vectorizer, logreg = _train_model(train_examples)
            interpreter = RuleBasedTradeInterpreter(local_classifier=TfidfVetoClassifier(vectorizer, logreg))
        else:
            print(f"unknown config '{config}', skipping")
            continue
        results[config] = await _run_config(
            config, interpreter, transcripts_dir=args.transcripts_dir, truth_by_file=truth_by_file, symbol=symbol
        )

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(
        json.dumps({"generated": datetime.now().isoformat(timespec="seconds"), "configs": results}, indent=2),
        encoding="utf-8",
    )

    review_lines = [
        "# Pipeline full-stream review sheet",
        "",
        "Every intent the interpretation pipeline fired on the five held-out test",
        "transcripts that does NOT correspond to a labelled action (no label within",
        "two lines). Tick the checkbox if the trader really performed a trade action",
        "at that moment; leave unticked if it is a false alarm.",
        "",
    ]
    for config, stats in results.items():
        review_lines.append(f"## Configuration: {config}")
        review_lines.append("")
        for fire in stats["unmatched_flat"]:
            review_lines.append(
                f"- [ ] {Path(fire['file']).name[:60]} L{fire['line']} `{fire['timecode']}` "
                f"**{fire['tag']}** (conf={fire['confidence']:.2f}): {fire['text']}"
            )
        review_lines.append("")
    args.out_review.write_text("\n".join(review_lines), encoding="utf-8")
    print(f"summary -> {args.out_json}\nreview sheet -> {args.out_review}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
