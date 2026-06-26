"""Pre-execution risk validation for trade intents.

Every trade intent passes through the RiskEngine before it reaches the broker.
The engine runs a series of checks (staleness, confidence, position limits, etc.)
and returns a RiskDecision that either approves or rejects the trade with a
human-readable reason. No actual orders are placed here -- this module only
decides whether it is safe to proceed.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import Settings
from app.models.domain import ENTRY_ACTIONS, ActionTag, RiskDecision, StreamSession, TradeIntent


# Actions that modify or close an existing position (as opposed to opening one)
MANAGE_ACTIONS = {ActionTag.trim, ActionTag.exit_all, ActionTag.move_stop, ActionTag.move_to_breakeven}


class RiskEngine:
    """Stateless gate-keeper that approves or rejects trade intents.

    Each check returns early with a rejection if a rule is violated.
    If all checks pass, the intent is approved at the end.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def evaluate(
        self,
        session: StreamSession,
        intent: TradeIntent,
        *,
        contract_size: int | None = None,
    ) -> RiskDecision:
        """Run all risk checks against a trade intent and return a decision.

        ``contract_size`` overrides the per-session default when sizing the
        position-cap check (used by manual trades, which carry their own size);
        when ``None`` the session's configured default is used.
        """
        now = datetime.now(UTC)
        age_ms = (now - intent.created_at).total_seconds() * 1000

        # -- Staleness check: reject intents that have been sitting too long --
        if age_ms > min(intent.stale_after_ms, self._settings.stale_intent_ms):
            return RiskDecision(approved=False, reason="Intent is stale.", intent=intent)

        # -- Confidence check: the classifier must be confident enough --
        if intent.confidence < self._settings.min_confidence:
            return RiskDecision(approved=False, reason="Confidence below threshold.", intent=intent)

        # -- Entry-specific checks (only for new-position / add-to-position actions) --
        if intent.tag in ENTRY_ACTIONS:
            # Account for both intent age and upstream processing latency
            effective_signal_age_ms = age_ms + max(0, intent.source_latency_ms)
            if effective_signal_age_ms > self._settings.max_entry_signal_age_ms:
                return RiskDecision(
                    approved=False,
                    reason=f"Entry signal too old ({int(effective_signal_age_ms)} ms).",
                    intent=intent,
                )
            # A context guard is an upstream veto (e.g., conflicting signals)
            if intent.guard_reason:
                return RiskDecision(
                    approved=False,
                    reason=f"Entry blocked by context guard: {intent.guard_reason}.",
                    intent=intent,
                )
            if session.market.last_price is None:
                return RiskDecision(approved=False, reason="No market price available.", intent=intent)
            if intent.tag == ActionTag.add:
                # "add" scales into an existing position and must match its side.
                if session.position is None:
                    return RiskDecision(approved=False, reason="Cannot add to a flat position.", intent=intent)
                if intent.side is not None and intent.side != session.position.side:
                    return RiskDecision(approved=False, reason="Add conflicts with open position side.", intent=intent)
            elif session.position is not None:
                # A fresh entry must not stack on top of an existing position.
                return RiskDecision(approved=False, reason="Position already open.", intent=intent)
            # Every entry must have a stop -- either from the intent or the position
            if intent.stop_price is None and (session.position is None or session.position.stop_price is None):
                return RiskDecision(approved=False, reason="Stop price is required for entries.", intent=intent)
            # Prevent chasing: reject entries where market has moved too far.
            # A literal 0.0 is still a real price, so only fall back when entry_price is unset.
            entry_price = intent.entry_price if intent.entry_price is not None else session.market.last_price
            max_distance_points = min(self._settings.max_entry_distance_points, self._settings.max_entry_chase_points)
            if abs(entry_price - session.market.last_price) > max_distance_points:
                return RiskDecision(approved=False, reason="Entry too far from current market.", intent=intent)
            # Position size cap: do not exceed the configured maximum contracts
            size_increment = contract_size if contract_size is not None else session.config.default_contract_size
            current_quantity = session.position.quantity if session.position is not None else 0
            proposed_quantity = current_quantity + size_increment
            if proposed_quantity > self._settings.max_contract_size:
                return RiskDecision(approved=False, reason="Position would exceed max contract size.", intent=intent)

        # -- Management checks: can only manage if a position exists --
        if intent.tag in MANAGE_ACTIONS:
            if session.position is None:
                return RiskDecision(approved=False, reason="No open position to manage.", intent=intent)

        return RiskDecision(approved=True, reason="Approved.", intent=intent)
