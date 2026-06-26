from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import Settings
from app.models.domain import ActionTag, MarketSnapshot, PositionState, SessionConfig, StreamSession, TradeIntent, TradeSide
from app.services.execution.risk import RiskEngine


def test_risk_engine_requires_stop_for_entry() -> None:
    engine = RiskEngine(Settings())
    session = StreamSession(config=SessionConfig(), market=MarketSnapshot(symbol="NQ", last_price=21240))
    intent = TradeIntent(
        session_id=session.id,
        tag=ActionTag.enter_long,
        side=TradeSide.long,
        entry_price=21241,
        evidence_text="I'm long here",
        confidence=0.95,
        created_at=datetime.now(UTC),
    )

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "Stop price is required for entries."


def test_risk_engine_rejects_old_entry_signal_from_stream_latency() -> None:
    engine = RiskEngine(Settings(max_entry_signal_age_ms=4_000))
    session = StreamSession(config=SessionConfig(), market=MarketSnapshot(symbol="NQ", last_price=21240))
    intent = TradeIntent(
        session_id=session.id,
        tag=ActionTag.enter_short,
        side=TradeSide.short,
        entry_price=21239,
        stop_price=21250,
        source_latency_ms=9_000,
        evidence_text="Putting a little piece on short versus 50s",
        confidence=0.95,
        created_at=datetime.now(UTC),
    )

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "Entry signal too old (9000 ms)."


def test_risk_engine_rejects_entry_when_context_guard_is_hit() -> None:
    engine = RiskEngine(Settings())
    session = StreamSession(config=SessionConfig(), market=MarketSnapshot(symbol="NQ", last_price=21240))
    intent = TradeIntent(
        session_id=session.id,
        tag=ActionTag.enter_short,
        side=TradeSide.short,
        entry_price=21239,
        stop_price=21250,
        guard_reason="recent management cue detected",
        source_latency_ms=500,
        evidence_text="Putting a little piece on short versus 50s",
        confidence=0.95,
        created_at=datetime.now(UTC),
    )

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "Entry blocked by context guard: recent management cue detected."


def test_risk_engine_allows_add_with_existing_position_stop() -> None:
    engine = RiskEngine(Settings())
    session = StreamSession(
        config=SessionConfig(),
        market=MarketSnapshot(symbol="NQ", last_price=21240),
        position=PositionState(side=TradeSide.long, quantity=1, average_price=21220, stop_price=21210),
    )
    intent = TradeIntent(
        session_id=session.id,
        tag=ActionTag.add,
        side=TradeSide.long,
        entry_price=21240,
        evidence_text="Got my add on there",
        confidence=0.95,
        created_at=datetime.now(UTC),
    )

    decision = engine.evaluate(session, intent)

    assert decision.approved is True


def _long_session(*, last_price: float = 21240, position: PositionState | None = None) -> StreamSession:
    return StreamSession(
        config=SessionConfig(),
        market=MarketSnapshot(symbol="NQ", last_price=last_price),
        position=position,
    )


def _entry(session: StreamSession, **overrides) -> TradeIntent:
    kwargs = dict(
        session_id=session.id,
        tag=ActionTag.enter_long,
        side=TradeSide.long,
        entry_price=21241,
        stop_price=21210,
        evidence_text="I'm long here",
        confidence=0.95,
        created_at=datetime.now(UTC),
    )
    kwargs.update(overrides)
    return TradeIntent(**kwargs)


def test_risk_engine_rejects_add_to_flat_position() -> None:
    engine = RiskEngine(Settings())
    session = _long_session()
    intent = _entry(session, tag=ActionTag.add, side=TradeSide.long, stop_price=None)

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "Cannot add to a flat position."


def test_risk_engine_rejects_add_with_conflicting_side() -> None:
    engine = RiskEngine(Settings())
    position = PositionState(side=TradeSide.long, quantity=1, average_price=21220, stop_price=21210)
    session = _long_session(position=position)
    intent = _entry(session, tag=ActionTag.add, side=TradeSide.short, entry_price=21240)

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "Add conflicts with open position side."


def test_risk_engine_rejects_entry_when_position_already_open() -> None:
    engine = RiskEngine(Settings())
    position = PositionState(side=TradeSide.long, quantity=1, average_price=21220, stop_price=21210)
    session = _long_session(position=position)
    intent = _entry(session, entry_price=21240)

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "Position already open."


def test_risk_engine_rejects_entry_that_chases_market() -> None:
    engine = RiskEngine(Settings())
    session = _long_session(last_price=21240)
    intent = _entry(session, entry_price=21260)  # 20 pts away; cap is min(12, 8) = 8

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "Entry too far from current market."


def test_risk_engine_rejects_low_confidence() -> None:
    engine = RiskEngine(Settings())
    session = _long_session()
    intent = _entry(session, confidence=0.5)

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "Confidence below threshold."


def test_risk_engine_rejects_stale_intent() -> None:
    engine = RiskEngine(Settings())
    session = _long_session()
    intent = _entry(session, created_at=datetime.now(UTC) - timedelta(seconds=10), stale_after_ms=5_000)

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "Intent is stale."


def test_risk_engine_rejects_entry_without_market_price() -> None:
    engine = RiskEngine(Settings())
    session = StreamSession(config=SessionConfig(), market=MarketSnapshot(symbol="NQ", last_price=None))
    intent = _entry(session)

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "No market price available."


def test_risk_engine_rejects_management_without_position() -> None:
    engine = RiskEngine(Settings())
    session = _long_session()
    intent = _entry(session, tag=ActionTag.trim, side=None, entry_price=None, stop_price=None, evidence_text="paying myself")

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "No open position to manage."


@pytest.mark.parametrize(
    ("starting_quantity", "approved"),
    [(3, True), (4, False)],  # default_contract_size=1, max_contract_size=4: 3+1==4 ok, 4+1>4 rejected
)
def test_risk_engine_enforces_size_cap_boundary(starting_quantity: int, approved: bool) -> None:
    engine = RiskEngine(Settings())
    position = PositionState(side=TradeSide.long, quantity=starting_quantity, average_price=21220, stop_price=21210)
    session = _long_session(position=position)
    intent = _entry(session, tag=ActionTag.add, side=TradeSide.long, entry_price=21240)

    decision = engine.evaluate(session, intent)

    assert decision.approved is approved
    if not approved:
        assert decision.reason == "Position would exceed max contract size."


def test_risk_engine_zero_entry_price_is_a_real_price_not_a_fallback() -> None:
    engine = RiskEngine(Settings())
    session = _long_session(last_price=21240)
    intent = _entry(session, entry_price=0.0)  # absurd but explicit -> should trip the chase guard, not fall back

    decision = engine.evaluate(session, intent)

    assert decision.approved is False
    assert decision.reason == "Entry too far from current market."
