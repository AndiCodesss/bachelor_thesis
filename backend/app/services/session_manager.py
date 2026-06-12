"""
Session Manager -- central orchestrator for the Stream Copier backend.

This module ties together every major subsystem: transcription (speech-to-text),
intent interpretation (rule engine, ML classifier, Gemini fallback), risk checks,
order execution via NinjaTrader, and real-time event broadcasting over WebSockets.

Each trading session gets its own lifecycle managed here. When audio arrives it is
transcribed, the transcript is interpreted into a trade intent (buy/sell/exit),
the intent passes through a risk engine, and -- if approved -- an order is sent
to the broker. Every step emits a timeline event so the frontend can display it.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.config import Settings
from app.models.domain import (
    ENTRY_ACTIONS,
    ActionTag,
    CreateSessionRequest,
    EventType,
    ExecutionResult,
    MarketSnapshot,
    ManualTradeAction,
    ManualTradeRequest,
    PositionState,
    SegmentStatus,
    SessionPatch,
    StreamSession,
    TextSegmentRequest,
    TimelineEvent,
    TradeIntent,
    TradeSide,
    TranscriptSegment,
    UpdateSessionConfigRequest,
    utc_now,
)
from app.services.event_hub import EventHub
from app.services.execution.ninjatrader import (
    BridgeUnavailableError,
    NinjaTraderBridgeClient,
    NinjaTraderExecutor,
)
from app.services.execution.risk import RiskEngine
from app.services.interpretation.gemini_fallback import GeminiFallbackInterpreter
from app.services.interpretation.local_classifier import ModernBertIntentClassifier
from app.services.interpretation.rule_engine import RuleBasedTradeInterpreter
from app.services.storage.event_store import EventLogStore
from app.services.storage.session_store import SessionStore
from app.services.transcription.base import BaseTranscriber
from app.services.transcription.mock import NoopTranscriber
from app.services.transcription.local_whisper import LocalWhisperTranscriber

_SESSION_SAVE_DEBOUNCE_S = 1.0
_BROKER_STATE_CACHE_TTL_S = 0.5
# When the bridge is unreachable, cache that "unavailable" result for longer so a
# missing bridge doesn't make every broker sync re-pay the connection timeout (which
# would stall the live pipeline). Re-probes then happen at most once per interval.
_BROKER_UNAVAILABLE_TTL_S = 4.0
_LOGGER = logging.getLogger(__name__)


def _tag_value(tag: ActionTag | ManualTradeAction | str) -> str:
    """Return the string value of an enum tag, handling both enum instances and plain strings."""
    return tag.value if hasattr(tag, "value") else str(tag)


@dataclass
class PendingPreviewExecution:
    intent: TradeIntent
    executed_at: datetime
    uncertain: bool = False


@dataclass
class CachedBrokerState:
    state: dict[str, Any]
    fetched_monotonic: float


class SessionManager:
    """Central orchestrator that owns every trading session's lifecycle.

    Coordinates transcription, intent interpretation, risk evaluation,
    order execution, broker synchronisation, and real-time event
    broadcasting. All public methods are called by the HTTP/WebSocket
    API layer; private methods handle the internal pipeline stages.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._sessions: dict[str, StreamSession] = {}
        self._event_hub = EventHub()
        self._store = EventLogStore(settings.events_dir)
        self._session_store = SessionStore(settings.sessions_dir)
        self._sessions = {session.id: session for session in self._session_store.load_all()}
        fallback = GeminiFallbackInterpreter(settings) if settings.interpreter_mode != "rule_only" else None
        local_classifier = ModernBertIntentClassifier(settings)
        if local_classifier.is_available():
            self._classifier_notice = (
                EventType.system,
                "Local intent classifier ready",
                self._format_classifier_ready_message(local_classifier.runtime_info()),
                local_classifier.runtime_info(),
            )
        else:
            classifier_runtime = local_classifier.runtime_info()
            self._classifier_notice = (
                EventType.warning,
                "Local intent classifier unavailable",
                str(classifier_runtime.get("error", "local intent classifier unavailable")),
                classifier_runtime,
            )
        self._interpreter = RuleBasedTradeInterpreter(
            fallback=fallback,
            local_classifier=local_classifier,
            classifier_min_probability=settings.local_intent_classifier_min_probability,
            classifier_block_probability=settings.local_intent_classifier_block_probability,
            classifier_recovery_probability=settings.local_intent_classifier_recovery_probability,
            candidate_window_ms=settings.candidate_window_ms,
            candidate_preroll_ms=settings.candidate_preroll_ms,
            candidate_max_fragments=settings.candidate_max_fragments,
            candidate_open_probability=settings.candidate_open_probability,
            candidate_keep_probability=settings.candidate_keep_probability,
            entry_context_window_ms=settings.entry_context_window_ms,
            entry_guard_window_ms=settings.entry_guard_window_ms,
            fallback_confirmation_timeout_ms=settings.gemini_confirmation_timeout_ms,
        )
        self._risk_engine = RiskEngine(settings)
        self._bridge_client = NinjaTraderBridgeClient(settings)
        self._executor = NinjaTraderExecutor(settings, bridge_client=self._bridge_client)
        self._transcribers: dict[str, BaseTranscriber] = {}
        # Tracks preview entries awaiting confirmation by the final transcript.
        self._pending_preview_executions: dict[str, PendingPreviewExecution] = {}
        self._preview_confirmation_window = timedelta(
            milliseconds=max(1, settings.preview_entry_confirmation_window_ms)
        )
        # Serialises the interpret -> risk -> execute pipeline per session so
        # concurrent final/preview/manual flows cannot both act on the same
        # (shared) position state across await boundaries.
        self._session_locks: dict[str, asyncio.Lock] = {}
        # Debounce: at most one pending save task per session.
        self._pending_save_tasks: dict[str, asyncio.Task[None]] = {}
        # Sessions with unsaved mutations, drained by the debounced save task.
        self._dirty_sessions: set[str] = set()
        self._event_write_tasks: set[asyncio.Task[None]] = set()
        # Per-session lock so event log writes for the same session are serialised.
        self._event_write_locks: dict[str, asyncio.Lock] = {}
        self._pending_event_writes: dict[str, int] = {}
        self._pending_event_waiters: dict[str, asyncio.Event] = {}
        self._transcriber_ready_tasks: dict[str, asyncio.Task[None]] = {}
        # Short-lived cache to avoid hitting the broker bridge on every call.
        self._broker_state_cache: dict[tuple[str, str | None, str | None], CachedBrokerState] = {}
        # De-duplicates concurrent in-flight broker requests for the same key.
        self._broker_state_requests: dict[
            tuple[str, str | None, str | None],
            asyncio.Task[dict[str, Any]],
        ] = {}
        # Whether the bridge is currently reachable; lets us log the down/up
        # transition once instead of on every failed sync.
        self._bridge_reachable: bool | None = None

    @property
    def event_hub(self) -> EventHub:
        return self._event_hub

    @property
    def settings(self) -> Settings:
        return self._settings

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Return the per-session pipeline lock, creating it on first use."""
        lock = self._session_locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session_id] = lock
        return lock

    async def get_broker_state(
        self,
        session_id: str,
        *,
        account: str | None = None,
        symbol: str | None = None,
    ) -> dict:
        """Fetch the current broker position/market state for a session.

        Uses a short TTL cache to avoid flooding the broker bridge with
        duplicate requests. Returns an error dict if the bridge is unreachable.
        """
        session = self.get_session(session_id)
        resolved_account, resolved_symbol = self._resolve_broker_query(
            session,
            account=account,
            symbol=symbol,
        )

        try:
            return await self._fetch_broker_state(
                session.id,
                account=resolved_account,
                symbol=resolved_symbol,
            )
        except Exception as error:
            # Any failure here (an unreachable bridge, or an unexpected error)
            # degrades to a structured "unavailable" state instead of a 500, so the
            # dashboard stays responsive and the app keeps running without trades.
            return self._bridge_unavailable_state(resolved_account, resolved_symbol, error)

    def list_sessions(self) -> list[StreamSession]:
        sessions = sorted(self._sessions.values(), key=lambda session: session.created_at, reverse=True)
        return [session.model_copy(deep=True) for session in sessions]

    def get_session(self, session_id: str) -> StreamSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        return session

    async def delete_session(self, session_id: str) -> None:
        """Tear down a session: cancel pending work, close the transcriber,
        then remove persisted session and event data from disk.
        """
        session = self._sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        self._interpreter.clear_session(session_id)
        self._pending_preview_executions.pop(session_id, None)
        self._clear_broker_state_cache(session_id)
        await self._wait_for_pending_event_writes(session_id)
        await self._cancel_transcriber_ready_task(session_id)

        # Cancel any pending debounced save for this session.
        task = self._pending_save_tasks.pop(session_id, None)
        if task is not None:
            task.cancel()
        self._dirty_sessions.discard(session_id)
        self._session_locks.pop(session_id, None)

        transcriber = self._transcribers.pop(session_id, None)
        if transcriber is not None:
            await transcriber.close()

        # Remove from _sessions last so in-flight callbacks (e.g. a
        # transcriber flush emitting one final segment) can still look it up.
        self._sessions.pop(session_id, None)
        self._session_store.delete(session_id)
        self._store.delete(session_id)

    async def create_session(self, request: CreateSessionRequest) -> StreamSession:
        """Create a new trading session, apply backend defaults, persist it,
        and emit the initial system events (session created, classifier status).
        """
        config = request.config.model_copy(deep=True)
        requested_symbol = _clean_optional(config.symbol)
        default_symbol = _clean_optional(self._settings.default_symbol)
        # If caller kept the legacy default symbol, respect configured backend default.
        if default_symbol is not None and (requested_symbol is None or requested_symbol.upper() == "NQ"):
            config.symbol = default_symbol
        if config.default_contract_size == 1 and self._settings.default_contract_size != 1:
            config.default_contract_size = max(1, min(10, self._settings.default_contract_size))

        session = StreamSession(config=config)
        session.market = MarketSnapshot(symbol=config.symbol)
        self._sessions[session.id] = session
        await self._emit(
            session.id,
            EventType.system,
            "Session created",
            f"Session started for {session.config.source_name}.",
            {"config": session.config.model_dump(mode="json")},
            persist_session=False,  # saved explicitly below
        )
        classifier_notice = getattr(self, "_classifier_notice", None)
        if classifier_notice is not None:
            await self._emit(
                session.id,
                classifier_notice[0],
                classifier_notice[1],
                classifier_notice[2],
                classifier_notice[3],
                persist_session=False,
            )
        # Save immediately on creation (not debounced) to persist the new session.
        self._session_store.save(session)
        return session.model_copy(deep=True)

    async def manual_trade(self, session_id: str, request: ManualTradeRequest) -> StreamSession:
        """Execute a manual buy/sell/close requested by the user via the UI.

        For a reversal (e.g. buying while short), this generates two intents:
        first an exit_all to flatten, then a new entry in the opposite direction.
        """
        session = self.get_session(session_id)
        async with self._get_session_lock(session_id):
            self._apply_broker_overrides_from_request(session, request)
            await self._sync_session_from_broker(session)

            action = _tag_value(request.action)
            if action == ManualTradeAction.close.value:
                intents = [
                    self._build_manual_intent(
                        session=session,
                        tag=ActionTag.exit_all,
                        side=session.position.side if session.position is not None else None,
                    )
                ]
            elif action == ManualTradeAction.buy.value:
                if session.position is None:
                    intents = [self._build_manual_intent(session=session, tag=ActionTag.enter_long, side=TradeSide.long)]
                elif session.position.side == TradeSide.long:
                    intents = [self._build_manual_intent(session=session, tag=ActionTag.add, side=TradeSide.long)]
                else:
                    intents = [
                        self._build_manual_intent(session=session, tag=ActionTag.exit_all, side=session.position.side),
                        self._build_manual_intent(session=session, tag=ActionTag.enter_long, side=TradeSide.long),
                    ]
            else:  # SELL
                if session.position is None:
                    intents = [self._build_manual_intent(session=session, tag=ActionTag.enter_short, side=TradeSide.short)]
                elif session.position.side == TradeSide.short:
                    intents = [self._build_manual_intent(session=session, tag=ActionTag.add, side=TradeSide.short)]
                else:
                    intents = [
                        self._build_manual_intent(session=session, tag=ActionTag.exit_all, side=session.position.side),
                        self._build_manual_intent(session=session, tag=ActionTag.enter_short, side=TradeSide.short),
                    ]

            for intent in intents:
                self._apply_wide_brackets(intent, session)
                session.last_intent = intent
                await self._emit(
                    session.id,
                    EventType.intent,
                    "Manual trade",
                    _tag_value(intent.tag),
                    intent.model_dump(mode="json"),
                    patch=SessionPatch(last_intent=intent),
                )

                # Manual trades go through the same risk gate as automated ones
                # (size cap, stop-required, chase guard, etc.); they are never
                # a privileged bypass.
                decision = self._risk_engine.evaluate(session, intent, contract_size=request.contract_size)
                await self._emit(
                    session.id,
                    EventType.risk,
                    "Risk check",
                    decision.reason,
                    {"approved": decision.approved, "intent": intent.model_dump(mode="json"), "manual": True},
                )
                if not decision.approved:
                    # Abort a multi-leg reversal if its flattening leg is blocked.
                    if len(intents) > 1:
                        break
                    continue

                result = await self._executor.execute(session, intent, contract_size=request.contract_size)
                # Reconcile from the broker on success AND on an uncertain
                # outcome -- never assume the position is unchanged when the
                # order's fate is unknown.
                if result.approved or result.uncertain:
                    await self._sync_session_from_broker(session, force_refresh=True)
                    self._refresh_execution_result(session, result)
                await self._emit_execution(session.id, result)
                if not result.approved and len(intents) > 1:
                    break

        return session.model_copy(deep=True)

    async def update_session_config(self, session_id: str, request: UpdateSessionConfigRequest) -> StreamSession:
        """Apply partial config updates to a live session (e.g. toggle features,
        switch transcription model, change broker overrides).
        """
        session = self.get_session(session_id)
        changes: list[str] = []
        restart_transcriber = False

        if (
            "enable_partial_intent_detection" in request.model_fields_set
            and request.enable_partial_intent_detection is not None
            and request.enable_partial_intent_detection != session.config.enable_partial_intent_detection
        ):
            session.config.enable_partial_intent_detection = request.enable_partial_intent_detection
            if not request.enable_partial_intent_detection:
                session.latest_candidate_intent = None
            state = "enabled" if request.enable_partial_intent_detection else "disabled"
            changes.append(f"partial intent {state}")

        if (
            "enable_ai_fallback" in request.model_fields_set
            and request.enable_ai_fallback is not None
            and request.enable_ai_fallback != session.config.enable_ai_fallback
        ):
            session.config.enable_ai_fallback = bool(request.enable_ai_fallback)
            state = "enabled" if session.config.enable_ai_fallback else "disabled"
            changes.append(f"gemini entry confirm {state}")

        if (
            "enable_early_preview_entries" in request.model_fields_set
            and request.enable_early_preview_entries is not None
            and request.enable_early_preview_entries != session.config.enable_early_preview_entries
        ):
            session.config.enable_early_preview_entries = bool(request.enable_early_preview_entries)
            if not session.config.enable_early_preview_entries:
                self._pending_preview_executions.pop(session_id, None)
            state = "enabled" if session.config.enable_early_preview_entries else "disabled"
            changes.append(f"early preview entry {state}")

        if (
            "transcription_model" in request.model_fields_set
            and request.transcription_model
            and request.transcription_model != session.config.transcription_model
        ):
            session.config.transcription_model = request.transcription_model
            session.latest_partial_text = ""
            session.latest_partial_metrics = None
            session.latest_candidate_intent = None
            restart_transcriber = True
            changes.append(f"model {request.transcription_model}")

        if "broker_account_override" in request.model_fields_set:
            broker_account_override = _clean_optional(request.broker_account_override)
            if broker_account_override != session.config.broker_account_override:
                session.config.broker_account_override = broker_account_override
                self._clear_broker_state_cache(session_id)
                changes.append(
                    f"broker account {broker_account_override}" if broker_account_override else "broker account cleared"
                )

        if "broker_symbol_override" in request.model_fields_set:
            broker_symbol_override = _clean_optional(request.broker_symbol_override)
            if broker_symbol_override != session.config.broker_symbol_override:
                session.config.broker_symbol_override = broker_symbol_override
                self._clear_broker_state_cache(session_id)
                changes.append(
                    f"broker symbol {broker_symbol_override}" if broker_symbol_override else "broker symbol cleared"
                )

        if restart_transcriber:
            await self._cancel_transcriber_ready_task(session_id)
            transcriber = self._transcribers.pop(session_id, None)
            if transcriber is not None:
                await transcriber.close()

        if changes:
            await self._emit(
                session.id,
                EventType.system,
                "Session config updated",
                ", ".join(changes),
                {"config": session.config.model_dump(mode="json")},
            )

        return session.model_copy(deep=True)

    async def ingest_segment(self, session_id: str, request: TextSegmentRequest) -> StreamSession:
        """Accept a text transcript segment from an external source (e.g. the
        REST API) and run it through the normal interpretation pipeline.
        """
        session = self.get_session(session_id)
        segment = TranscriptSegment(
            session_id=session_id,
            text=request.text,
            status=request.status,
            source=request.source,
            item_id=request.item_id,
            confidence=request.confidence,
        )
        await self._process_segment(session, segment)
        return session.model_copy(deep=True)

    async def handle_live_segment(self, segment: TranscriptSegment) -> None:
        """Callback invoked by the live transcriber when a new segment
        (partial or final) is produced from the audio stream.
        """
        session = self.get_session(segment.session_id)
        await self._process_segment(session, segment)

    async def push_audio(self, session_id: str, data: bytes, sample_rate: int) -> None:
        """Feed raw audio bytes into the session's transcriber for
        real-time speech-to-text processing.
        """
        transcriber = await self.ensure_transcriber(session_id)
        try:
            await transcriber.push_audio(data, sample_rate)
        except Exception as error:
            await self._emit(
                session_id,
                EventType.warning,
                "Audio ingest error",
                str(error),
                {"stage": "stream"},
            )
            raise

    async def ensure_transcriber(self, session_id: str) -> BaseTranscriber:
        session = self.get_session(session_id)
        transcriber = self._transcribers.get(session_id)
        if transcriber is None:
            try:
                transcriber = await self._build_transcriber(session)
            except Exception as error:
                await self._emit(
                    session_id,
                    EventType.warning,
                    "Transcriber error",
                    str(error),
                    {"stage": "startup"},
                )
                raise
            self._transcribers[session_id] = transcriber
        return transcriber

    async def close(self) -> None:
        transcriber_ready_tasks = list(self._transcriber_ready_tasks.values())
        for task in transcriber_ready_tasks:
            task.cancel()
        if transcriber_ready_tasks:
            await asyncio.gather(*transcriber_ready_tasks, return_exceptions=True)
        self._transcriber_ready_tasks.clear()
        for transcriber in self._transcribers.values():
            await transcriber.close()
        await self._interpreter.close()
        # Cancel debounced save tasks and WAIT for them to unwind before the
        # final synchronous flush, so a background write cannot race it. The
        # per-session lock in SessionStore guards against any straggler thread.
        pending_saves = list(self._pending_save_tasks.values())
        for task in pending_saves:
            task.cancel()
        if pending_saves:
            await asyncio.gather(*pending_saves, return_exceptions=True)
        self._pending_save_tasks.clear()
        self._dirty_sessions.clear()
        for session in self._sessions.values():
            self._session_store.save(session)
        if self._event_write_tasks:
            await asyncio.gather(*list(self._event_write_tasks), return_exceptions=True)
        await self._bridge_client.close()

    async def _process_segment(self, session: StreamSession, segment: TranscriptSegment) -> None:
        """Route a transcript segment through the pipeline under the per-session
        lock so final/preview/manual flows cannot interleave on shared state.
        """
        async with self._get_session_lock(session.id):
            await self._process_segment_locked(session, segment)

    async def _process_segment_locked(self, session: StreamSession, segment: TranscriptSegment) -> None:
        """Core pipeline: route a transcript segment through interpretation,
        risk checking, and execution. Partial segments only update the UI and
        optionally trigger preview entries; final segments drive real trades.

        Must be called while holding ``_get_session_lock(session.id)``.
        """
        if segment.status == SegmentStatus.partial:
            session.latest_partial_text = segment.text
            session.latest_partial_metrics = segment.metrics
            session.latest_candidate_intent = None
            if session.config.enable_partial_intent_detection and segment.text.strip():
                session.latest_candidate_intent = self._interpreter.interpret_partial(session, segment)
            await self._emit(
                session.id,
                EventType.transcript,
                "Transcript",
                segment.text,
                segment.model_dump(mode="json"),
                patch=SessionPatch(
                    latest_partial_text=session.latest_partial_text,
                    latest_partial_metrics=session.latest_partial_metrics,
                    latest_candidate_intent=session.latest_candidate_intent,
                ),
                persist_session=False,
                persist_event=False,
                append_to_session=False,
            )
            # Preview entries let us act on partial speech before the speaker
            # finishes, then confirm or roll back once the final text arrives.
            if session.config.enable_early_preview_entries and segment.text.strip():
                await self._maybe_execute_preview_entry(session, segment)
            return

        # Final segment -- speaker has finished; this text is authoritative.
        session.latest_partial_text = ""
        session.latest_partial_metrics = None
        session.latest_candidate_intent = None
        session.latest_final_metrics = segment.metrics
        session.transcripts.append(segment)
        del session.transcripts[: -self._settings.max_transcript_segments]

        await self._emit(
            session.id,
            EventType.transcript,
            "Transcript",
            segment.text,
            segment.model_dump(mode="json"),
            patch=SessionPatch(
                latest_partial_text="",
                latest_partial_metrics=None,
                latest_candidate_intent=None,
                latest_final_metrics=segment.metrics,
                new_transcript=segment,
            ),
        )

        if not segment.text.strip():
            return

        # If a preview entry was executed earlier from partial text, the final
        # transcript must confirm it. If it does not, the position is flattened.
        pending_preview = self._get_pending_preview_execution(session.id)
        if pending_preview is not None:
            preview_confirmed = self._interpreter.confirm_preview_entry(
                session,
                segment,
                pending_intent=pending_preview.intent,
            )
            if preview_confirmed:
                if pending_preview.uncertain:
                    synced = await self._sync_session_from_broker(session, force_refresh=True)
                    if not synced:
                        await self._emit(
                            session.id,
                            EventType.warning,
                            "Preview entry unresolved",
                            "Final transcript confirmed the preview entry, but broker state could not be reconciled.",
                            {
                                "intent": pending_preview.intent.model_dump(mode="json"),
                                "segment_id": segment.id,
                            },
                        )
                        return
                    if session.position is None:
                        self._pending_preview_executions.pop(session.id, None)
                        await self._emit(
                            session.id,
                            EventType.warning,
                            "Preview entry not found",
                            "Final transcript confirmed the preview entry, but the broker is flat. Processing the final signal.",
                            {
                                "intent": pending_preview.intent.model_dump(mode="json"),
                                "segment_id": segment.id,
                            },
                        )
                    elif pending_preview.intent.side is None or session.position.side == pending_preview.intent.side:
                        self._pending_preview_executions.pop(session.id, None)
                        await self._emit(
                            session.id,
                            EventType.system,
                            "Preview entry confirmed",
                            "Final transcript confirmed the early preview entry.",
                            {
                                "intent": pending_preview.intent.model_dump(mode="json"),
                                "segment_id": segment.id,
                            },
                        )
                        return
                    else:
                        self._pending_preview_executions.pop(session.id, None)
                        await self._emit(
                            session.id,
                            EventType.warning,
                            "Preview entry mismatch",
                            "Final transcript confirmed the preview entry, but broker position side does not match.",
                            {
                                "intent": pending_preview.intent.model_dump(mode="json"),
                                "segment_id": segment.id,
                            },
                        )
                else:
                    self._pending_preview_executions.pop(session.id, None)
                    await self._emit(
                        session.id,
                        EventType.system,
                        "Preview entry confirmed",
                        "Final transcript confirmed the early preview entry.",
                        {
                            "intent": pending_preview.intent.model_dump(mode="json"),
                            "segment_id": segment.id,
                        },
                    )
                    return

            if not preview_confirmed:
                self._pending_preview_executions.pop(session.id, None)
                await self._emit(
                    session.id,
                    EventType.warning,
                    "Preview entry rejected",
                    "Final transcript did not confirm the early preview entry. Flattening position.",
                    {
                        "intent": pending_preview.intent.model_dump(mode="json"),
                        "segment_id": segment.id,
                    },
                )
                await self._flatten_preview_entry(session, pending_preview)
                # Fall through to normal interpretation -- the final segment may
                # contain its own valid trading signal that should not be lost.

        await self._sync_session_from_broker(session)

        intent = await self._interpreter.interpret(session, segment)
        diagnostic = self._interpreter.consume_diagnostic(session.id)
        if diagnostic is not None:
            await self._emit(
                session.id,
                diagnostic.event_type,
                diagnostic.title,
                diagnostic.message,
                diagnostic.data,
            )
        if intent is None:
            return

        self._apply_wide_brackets(intent, session)

        session.last_intent = intent
        intent_tag = _tag_value(intent.tag)
        await self._emit(
            session.id,
            EventType.intent,
            "Intent detected",
            intent_tag,
            intent.model_dump(mode="json"),
            patch=SessionPatch(last_intent=intent),
        )

        decision = self._risk_engine.evaluate(session, intent)
        await self._emit(
            session.id,
            EventType.risk,
            "Risk check",
            decision.reason,
            {"approved": decision.approved, "intent": intent.model_dump(mode="json")},
        )

        if not decision.approved:
            return

        result = await self._executor.execute(session, intent)
        if result.approved or result.uncertain:
            await self._sync_session_from_broker(session, force_refresh=True)
            self._refresh_execution_result(session, result)
        await self._emit_execution(session.id, result)

    def _build_manual_intent(
        self,
        *,
        session: StreamSession,
        tag: ActionTag,
        side: TradeSide | None,
    ) -> TradeIntent:
        """Construct a TradeIntent for a manual (user-initiated) trade.

        Uses current market/position prices as reference and sets confidence
        to 1.0 since manual trades are explicitly requested by the user.
        """
        configured_symbol = _clean_optional(session.config.broker_symbol_override) or _clean_optional(
            self._settings.ninjatrader_symbol
        )
        entry_reference = session.market.last_price
        if entry_reference is None and session.position is not None:
            entry_reference = session.position.average_price
        return TradeIntent(
            session_id=session.id,
            tag=tag,
            symbol=configured_symbol or session.market.symbol,
            side=side,
            entry_price=entry_reference,
            evidence_text=f"manual_{tag.value.lower()}",
            confidence=1.0,
            source_latency_ms=0,
            stale_after_ms=max(self._settings.stale_intent_ms, 60_000),
            created_at=utc_now(),
        )

    def _get_pending_preview_execution(self, session_id: str) -> PendingPreviewExecution | None:
        pending = self._pending_preview_executions.get(session_id)
        if pending is None:
            return None
        if datetime.now(UTC) - pending.executed_at <= self._preview_confirmation_window:
            return pending
        self._pending_preview_executions.pop(session_id, None)
        return None

    async def _maybe_execute_preview_entry(self, session: StreamSession, segment: TranscriptSegment) -> None:
        """Attempt an early entry based on partial (incomplete) speech.

        If the interpreter detects a high-confidence entry signal in the
        partial text, the order is executed immediately. The trade is then
        held in a pending state until the final transcript either confirms
        or rejects it (see _flatten_preview_entry for the rejection path).
        """
        if self._get_pending_preview_execution(session.id) is not None:
            return

        await self._sync_session_from_broker(session)
        preview_intent = self._interpreter.interpret_preview_entry(session, segment)
        if preview_intent is None:
            return

        # Keep an unmodified copy for confirmation checking later; the
        # original will have brackets/prices mutated before execution.
        confirmation_intent = preview_intent.model_copy(deep=True)
        self._apply_wide_brackets(preview_intent, session)
        session.last_intent = preview_intent
        await self._emit(
            session.id,
            EventType.intent,
            "Early preview entry",
            _tag_value(preview_intent.tag),
            {"preview_entry": True, "intent": preview_intent.model_dump(mode="json")},
            patch=SessionPatch(last_intent=preview_intent),
        )

        decision = self._risk_engine.evaluate(session, preview_intent)
        await self._emit(
            session.id,
            EventType.risk,
            "Risk check",
            decision.reason,
            {"approved": decision.approved, "intent": preview_intent.model_dump(mode="json"), "preview_entry": True},
        )
        if not decision.approved:
            return

        # Register the pending marker *before* awaiting the executor so a final
        # segment processed right afterwards cannot miss it and fire a duplicate
        # entry. Roll it back if the order is not accepted.
        pending = PendingPreviewExecution(
            intent=confirmation_intent,
            executed_at=datetime.now(UTC),
        )
        self._pending_preview_executions[session.id] = pending
        result = await self._executor.execute(session, preview_intent)
        pending.uncertain = result.uncertain
        if result.approved or result.uncertain:
            await self._sync_session_from_broker(session, force_refresh=True)
            self._refresh_execution_result(session, result)
        if not result.approved and not result.uncertain:
            # Definitive rejection: nothing was placed, so drop the marker.
            # On an uncertain outcome we keep it so the final transcript still
            # confirms-or-flattens any position that may have opened.
            self._pending_preview_executions.pop(session.id, None)
        await self._emit_execution(session.id, result)
        if not result.approved:
            return

        await self._emit(
            session.id,
            EventType.system,
            "Preview entry awaiting final",
            "Early preview entry executed. Waiting for the final transcript to confirm it.",
            {"intent": confirmation_intent.model_dump(mode="json")},
        )

    async def _flatten_preview_entry(self, session: StreamSession, pending: PendingPreviewExecution) -> None:
        """Close a position that was opened by a preview entry whose final
        transcript did not confirm the trade. This is the safety net that
        prevents the system from holding an unconfirmed position.
        """
        exit_intent = TradeIntent(
            session_id=session.id,
            tag=ActionTag.exit_all,
            symbol=pending.intent.symbol,
            side=pending.intent.side,
            confidence=1.0,
            evidence_text=f"preview_flatten_{pending.intent.id}",
            source_latency_ms=0,
            stale_after_ms=max(self._settings.stale_intent_ms, 60_000),
            created_at=utc_now(),
        )
        session.last_intent = exit_intent
        await self._emit(
            session.id,
            EventType.intent,
            "Preview flatten",
            _tag_value(exit_intent.tag),
            {"preview_flatten": True, "intent": exit_intent.model_dump(mode="json")},
            patch=SessionPatch(last_intent=exit_intent),
        )
        result = await self._executor.execute(session, exit_intent)
        if result.approved or result.uncertain:
            await self._sync_session_from_broker(session, force_refresh=True)
            self._refresh_execution_result(session, result)
        await self._emit(
            session.id,
            EventType.risk,
            "Risk check",
            "Preview confirmation failed. Flattening the early entry.",
            {"approved": result.approved, "intent": exit_intent.model_dump(mode="json"), "preview_flatten": True},
        )
        await self._emit_execution(session.id, result)

    def _apply_wide_brackets(self, intent: TradeIntent, session: StreamSession) -> None:
        """Attach wide stop-loss and take-profit prices to entry intents.

        Only runs when force_wide_brackets is enabled in settings. The
        offsets are calculated from the current market or position price.
        """
        if not self._settings.force_wide_brackets:
            return
        if intent.tag not in ENTRY_ACTIONS:
            return

        # Infer side from the action tag when the intent does not carry one.
        side = intent.side
        if side is None:
            if intent.tag == ActionTag.enter_long:
                side = TradeSide.long
            elif intent.tag == ActionTag.enter_short:
                side = TradeSide.short
            elif intent.tag == ActionTag.add and session.position is not None:
                side = session.position.side
        if side is None:
            return

        reference_price = intent.entry_price if intent.entry_price is not None else session.market.last_price
        if reference_price is None and session.position is not None:
            reference_price = session.position.average_price
        if reference_price is None:
            return

        stop_offset = max(1.0, float(self._settings.wide_stop_points))
        target_offset = max(stop_offset, float(self._settings.wide_target_points))
        if side == TradeSide.long:
            intent.stop_price = reference_price - stop_offset
            intent.target_price = reference_price + target_offset
        else:
            intent.stop_price = reference_price + stop_offset
            intent.target_price = reference_price - target_offset

    async def _sync_session_from_broker(self, session: StreamSession, *, force_refresh: bool = False) -> bool:
        """Pull the latest position and market data from the broker bridge
        and update the session's in-memory state. Silently returns on failure
        so that the pipeline can continue with stale data rather than crash.
        """
        try:
            configured_account, resolved_symbol = self._resolve_broker_query(session)
            state = await self._fetch_broker_state(
                session.id,
                account=configured_account,
                symbol=resolved_symbol,
                force_refresh=force_refresh,
            )
        except Exception:
            _LOGGER.warning("Broker sync failed for session %s", session.id, exc_info=True)
            return False

        if not isinstance(state, dict) or not state.get("ok"):
            return False

        symbol_from_state = _clean_optional(
            state["symbol"] if isinstance(state.get("symbol"), str) else None
        )
        last = _as_optional_float(state.get("last_price"))
        bid = _as_optional_float(state.get("bid_price"))
        ask = _as_optional_float(state.get("ask_price"))

        if symbol_from_state or resolved_symbol or last is not None or bid is not None or ask is not None:
            session.market = MarketSnapshot(
                symbol=symbol_from_state or resolved_symbol,
                last_price=last if last is not None else session.market.last_price,
                bid_price=bid if bid is not None else session.market.bid_price,
                ask_price=ask if ask is not None else session.market.ask_price,
                received_at=utc_now(),
            )

        # Reconcile position: update or clear based on what the broker reports.
        market_position = str(state.get("market_position", "")).upper()
        quantity = int(_as_optional_float(state.get("quantity")) or 0)
        average_price = _as_optional_float(state.get("average_price"))
        stop_price = _as_optional_float(state.get("stop_price"))
        target_price = _as_optional_float(state.get("target_price"))

        if market_position in {"LONG", "SHORT"} and quantity > 0 and average_price is not None:
            side = TradeSide.long if market_position == "LONG" else TradeSide.short
            previous = session.position
            same_side = previous is not None and previous.side == side
            opened_at = previous.opened_at if same_side else utc_now()
            realized_pnl = previous.realized_pnl if previous is not None else 0.0
            session.position = PositionState(
                side=side,
                quantity=quantity,
                average_price=average_price,
                stop_price=stop_price,
                target_price=target_price,
                opened_at=opened_at,
                realized_pnl=realized_pnl,
            )
        elif market_position == "FLAT":
            session.position = None

        realized = _as_optional_float(state.get("account_realized_pnl"))
        if realized is not None:
            session.realized_pnl = realized
        return True

    async def _fetch_broker_state(
        self,
        session_id: str,
        *,
        account: str | None,
        symbol: str | None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        cache_key = (session_id, account, symbol)

        # Serve from cache when fresh. A successful state is cached only briefly
        # (live data must stay current), but an "unavailable" result is held longer
        # and honored even on a forced refresh -- otherwise a missing bridge would
        # make every sync re-pay the connection timeout and stall the pipeline.
        cached = self._broker_state_cache.get(cache_key)
        if cached is not None:
            unavailable = cached.state.get("code") == "bridge_unavailable"
            ttl = _BROKER_UNAVAILABLE_TTL_S if unavailable else _BROKER_STATE_CACHE_TTL_S
            if (time.monotonic() - cached.fetched_monotonic) <= ttl and (unavailable or not force_refresh):
                return cached.state

        if not force_refresh:
            # Reuse an in-flight request to avoid duplicate network calls.
            in_flight = self._broker_state_requests.get(cache_key)
            if in_flight is not None:
                try:
                    return await asyncio.shield(in_flight)
                except BridgeUnavailableError as error:
                    return self._bridge_unavailable_state(account, symbol, error)

        task = asyncio.create_task(self._bridge_client.fetch_state(account=account, symbol=symbol))
        self._broker_state_requests[cache_key] = task
        try:
            state = await asyncio.shield(task)
        except BridgeUnavailableError as error:
            # The bridge is not connected. Degrade gracefully: report it as an
            # "unavailable" state (no exception) so the live pipeline keeps running
            # and we simply do not copy trades.
            state = self._bridge_unavailable_state(account, symbol, error)
        finally:
            if self._broker_state_requests.get(cache_key) is task:
                self._broker_state_requests.pop(cache_key, None)

        self._note_bridge_reachability(state)
        if isinstance(state, dict):
            self._broker_state_cache[cache_key] = CachedBrokerState(
                state=state,
                fetched_monotonic=time.monotonic(),
            )
        return state

    def _bridge_unavailable_state(
        self,
        account: str | None,
        symbol: str | None,
        error: Exception | None = None,
    ) -> dict[str, Any]:
        """Build the structured 'bridge not connected' state returned when the
        NinjaTrader bridge cannot be reached, so callers degrade instead of crash."""
        message = "NinjaTrader bridge not connected; trades will not be copied."
        if error is not None:
            message = f"{message} ({error})"
        return {
            "ok": False,
            "code": "bridge_unavailable",
            "message": message,
            "timestamp_utc": utc_now().isoformat(),
            "account": account,
            "symbol": symbol,
        }

    def _note_bridge_reachability(self, state: Any) -> None:
        """Log a single message when the bridge goes down or comes back, instead
        of logging every failed sync (which would flood the console)."""
        unavailable = isinstance(state, dict) and state.get("code") == "bridge_unavailable"
        if unavailable:
            if self._bridge_reachable is not False:
                self._bridge_reachable = False
                _LOGGER.info(
                    "NinjaTrader bridge not reachable -- continuing without trade "
                    "copying until it is connected."
                )
        else:
            if self._bridge_reachable is False:
                _LOGGER.info("NinjaTrader bridge reconnected -- trade copying resumed.")
            self._bridge_reachable = True

    def _clear_broker_state_cache(self, session_id: str) -> None:
        for cache_key in [key for key in self._broker_state_cache if key[0] == session_id]:
            self._broker_state_cache.pop(cache_key, None)
        for request_key in [key for key in self._broker_state_requests if key[0] == session_id]:
            self._broker_state_requests.pop(request_key, None)

    def _apply_broker_overrides_from_request(self, session: StreamSession, request: ManualTradeRequest) -> None:
        if "account" in request.model_fields_set:
            account = _clean_optional(request.account)
            if account != session.config.broker_account_override:
                session.config.broker_account_override = account
                self._clear_broker_state_cache(session.id)
        if "symbol" in request.model_fields_set:
            symbol = _clean_optional(request.symbol)
            if symbol != session.config.broker_symbol_override:
                session.config.broker_symbol_override = symbol
                self._clear_broker_state_cache(session.id)

    def _resolve_broker_query(
        self,
        session: StreamSession,
        *,
        account: str | None = None,
        symbol: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Resolve the (account, symbol) pair to query the broker bridge with.

        Precedence: request override -> session override -> a session
        symbol already shaped like a NinjaTrader contract -> configured
        default. The contract-shaped session symbol is preferred over the
        configured default because, once the broker has reported a concrete
        front-month contract (e.g. "NQ 06-26"), that is what is actually
        tradeable right now; the configured default is often a bare root
        ("NQ") that would not route. The _looks_like_ninjatrader_contract
        gate ensures we only trust the session symbol when it carries that
        explicit month-year suffix, never a raw placeholder.
        """
        session_account = _clean_optional(session.config.broker_account_override)
        session_symbol_override = _clean_optional(session.config.broker_symbol_override)
        resolved_account = _clean_optional(account) or session_account or _clean_optional(self._settings.ninjatrader_account)
        resolved_symbol = _clean_optional(symbol)
        configured_symbol = _clean_optional(self._settings.ninjatrader_symbol)

        if resolved_symbol is None:
            session_symbol = _clean_optional(session.market.symbol)
            if session_symbol_override is not None:
                resolved_symbol = session_symbol_override
            elif _looks_like_ninjatrader_contract(session_symbol):
                resolved_symbol = session_symbol
            else:
                resolved_symbol = configured_symbol

        return resolved_account, resolved_symbol

    async def _build_transcriber(self, session: StreamSession) -> BaseTranscriber:
        if not session.config.enable_audio_capture:
            return NoopTranscriber()

        if self._settings.transcription_backend != "local_whisper":
            return NoopTranscriber()

        transcriber = LocalWhisperTranscriber(
            settings=self._settings,
            session_id=session.id,
            model_name=session.config.transcription_model,
            prompt=self._settings.audio_prompt,
            on_segment=self.handle_live_segment,
        )
        await transcriber.start()
        runtime = transcriber.runtime_info()
        await self._emit(
            session.id,
            EventType.system,
            "Transcriber starting",
            f"{runtime['model']} {runtime.get('engine', 'segment')} preview pipeline booting on {runtime['device']}",
            runtime,
        )
        if self._settings.transcription_require_cuda:
            ready_runtime = await transcriber.wait_until_ready()
            if ready_runtime:
                await self._emit_transcriber_runtime(session.id, ready_runtime)
        else:
            self._schedule_transcriber_ready_task(session.id, transcriber)
        return transcriber

    def _schedule_transcriber_ready_task(self, session_id: str, transcriber: BaseTranscriber) -> None:
        existing = self._transcriber_ready_tasks.get(session_id)
        if existing is not None and not existing.done():
            return

        task = asyncio.create_task(self._observe_transcriber_runtime(session_id, transcriber))
        self._transcriber_ready_tasks[session_id] = task

        def _cleanup(done_task: asyncio.Task[None]) -> None:
            current = self._transcriber_ready_tasks.get(session_id)
            if current is done_task:
                self._transcriber_ready_tasks.pop(session_id, None)

        task.add_done_callback(_cleanup)

    async def _cancel_transcriber_ready_task(self, session_id: str) -> None:
        task = self._transcriber_ready_tasks.pop(session_id, None)
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _observe_transcriber_runtime(self, session_id: str, transcriber: BaseTranscriber) -> None:
        try:
            runtime = await transcriber.wait_until_ready()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if session_id in self._sessions:
                await self._emit(
                    session_id,
                    EventType.warning,
                    "Transcriber error",
                    str(error),
                    {"stage": "runtime"},
                )
            return

        if runtime is None or session_id not in self._sessions:
            return
        await self._emit_transcriber_runtime(session_id, runtime)

    async def _emit_transcriber_runtime(self, session_id: str, runtime: dict[str, object]) -> None:
        if session_id not in self._sessions:
            return

        await self._emit(
            session_id,
            EventType.system,
            "Transcriber ready",
            self._format_transcriber_ready_message(runtime),
            runtime,
        )

        warning_message = self._transcriber_runtime_warning(runtime)
        if warning_message is None:
            return
        await self._emit(
            session_id,
            EventType.warning,
            "Transcriber degraded",
            warning_message,
            runtime,
        )

    def _format_transcriber_ready_message(self, runtime: dict[str, object]) -> str:
        model = str(runtime.get("model", "transcriber"))
        preview_model = str(runtime.get("preview_model", model))
        device = str(runtime.get("device", "unknown"))
        preview_device = str(runtime.get("preview_device", device))
        segmenter_backend = str(runtime.get("segmenter_backend", "unknown"))
        engine = str(runtime.get("engine", "segment"))

        if preview_model == model and preview_device == device:
            return f"{model} ready on {device} with {segmenter_backend} VAD and {engine} preview"
        return (
            f"{model} ready on {device}; preview {preview_model} ready on {preview_device} "
            f"with {segmenter_backend} VAD and {engine} preview"
        )

    def _transcriber_runtime_warning(self, runtime: dict[str, object]) -> str | None:
        if not self._settings.transcription_warn_on_cpu_fallback:
            return None

        resolved_device = str(runtime.get("resolved_device", ""))
        configured_device = str(runtime.get("configured_device", ""))
        if resolved_device != "cuda" or configured_device == "cpu":
            return None

        degraded_paths: list[str] = []
        final_device = str(runtime.get("device", ""))
        preview_device = str(runtime.get("preview_device", ""))
        if final_device != "cuda":
            degraded_paths.append(f"final model loaded on {final_device}")
        if preview_device != "cuda":
            degraded_paths.append(f"preview model loaded on {preview_device}")
        if not degraded_paths:
            return None
        return "CUDA was expected, but " + " and ".join(degraded_paths)

    def _format_classifier_ready_message(self, runtime: dict[str, object]) -> str:
        model_name = str(runtime.get("model_name", "classifier"))
        device = str(runtime.get("device", "unknown"))
        label_count = len(runtime.get("labels", [])) if isinstance(runtime.get("labels"), list) else 0
        return f"{model_name} ready on {device} with {label_count} intent labels"

    def _refresh_execution_result(self, session: StreamSession, result: ExecutionResult) -> None:
        result.market_price = session.market.last_price
        result.position = session.position.model_copy(deep=True) if session.position else None

    async def _emit_execution(self, session_id: str, result: ExecutionResult) -> None:
        session = self.get_session(session_id)
        await self._emit(
            session_id,
            EventType.execution,
            "Execution",
            result.message,
            result.model_dump(mode="json"),
            patch=SessionPatch(
                market=session.market,
                position=session.position,
                realized_pnl=session.realized_pnl,
            ),
        )

    async def _emit(
        self,
        session_id: str,
        event_type: EventType,
        title: str,
        message: str,
        data: dict,
        *,
        patch: SessionPatch | None = None,
        persist_session: bool = True,
        persist_event: bool = True,
        append_to_session: bool = True,
    ) -> None:
        """Create a timeline event, broadcast it to WebSocket subscribers,
        and optionally persist the session and event to disk. The `patch`
        carries incremental state changes so the frontend can update without
        re-fetching the full session.
        """
        session = self.get_session(session_id)
        event = TimelineEvent(session_id=session_id, type=event_type, title=title, message=message, data=data)

        if append_to_session:
            session.events.append(event)
            del session.events[: -self._settings.max_events]

        if persist_session:
            self._schedule_session_save(session_id)

        ws_message: dict = {
            "type": "event",
            "event": event.model_dump(mode="json"),
            "patch": (patch or SessionPatch()).model_dump(mode="json", exclude_unset=True),
            "append_event": append_to_session,
        }
        await self._event_hub.publish(session_id, ws_message)

        if persist_event:
            self._schedule_event_write(event)

    def _schedule_session_save(self, session_id: str) -> None:
        """Schedule a debounced session save to disk.

        Many events fire in rapid succession (e.g. partial transcripts).
        Debouncing coalesces them into a single disk write per window,
        avoiding excessive I/O while still persisting state regularly.
        """
        self._dirty_sessions.add(session_id)
        task = self._pending_save_tasks.get(session_id)
        if task is not None and not task.done():
            return
        self._pending_save_tasks[session_id] = asyncio.create_task(
            self._debounced_save(session_id)
        )

    async def _debounced_save(self, session_id: str) -> None:
        try:
            await asyncio.sleep(_SESSION_SAVE_DEBOUNCE_S)
            # Drain the dirty flag: a mutation that lands during the write
            # re-marks the session, so loop until it is clean. The exit check
            # and the task pop in `finally` run with no await in between, so a
            # mutation can never slip through unsaved.
            while session_id in self._dirty_sessions:
                self._dirty_sessions.discard(session_id)
                session = self._sessions.get(session_id)
                if session is None:
                    return
                # Serialise on the event loop so the snapshot cannot be torn by
                # a concurrent mutation while the worker thread writes it.
                payload = session.model_dump_json()
                try:
                    await asyncio.to_thread(self._session_store.save_json, session_id, payload)
                except Exception:
                    _LOGGER.exception("Failed to persist session %s", session_id)
                    self._dirty_sessions.add(session_id)
                    return
        finally:
            self._pending_save_tasks.pop(session_id, None)

    def _schedule_event_write(self, event: TimelineEvent) -> None:
        session_id = event.session_id
        self._pending_event_writes[session_id] = self._pending_event_writes.get(session_id, 0) + 1
        waiter = self._pending_event_waiters.get(session_id)
        if waiter is not None:
            waiter.clear()

        task = asyncio.create_task(self._persist_event(event))
        self._event_write_tasks.add(task)
        task.add_done_callback(self._handle_event_write_done)

    async def _persist_event(self, event: TimelineEvent) -> None:
        session_id = event.session_id
        lock = self._event_write_locks.setdefault(session_id, asyncio.Lock())
        try:
            async with lock:
                await asyncio.to_thread(self._store.append, event)
        except Exception:
            _LOGGER.exception("Failed to persist event for session %s", session_id)
        finally:
            remaining = max(0, self._pending_event_writes.get(session_id, 0) - 1)
            if remaining == 0:
                self._pending_event_writes.pop(session_id, None)
                waiter = self._pending_event_waiters.get(session_id)
                if waiter is not None:
                    waiter.set()
            else:
                self._pending_event_writes[session_id] = remaining

    def _handle_event_write_done(self, task: asyncio.Task[None]) -> None:
        self._event_write_tasks.discard(task)
        try:
            task.result()
        except BaseException:
            pass

    async def _wait_for_pending_event_writes(self, session_id: str) -> None:
        # Loop on the counter instead of trusting a single wake. _schedule_event_write
        # clears the waiter as soon as a new write enqueues, so a wake from a prior
        # drain-to-zero must be re-validated before we return.
        while self._pending_event_writes.get(session_id, 0) > 0:
            waiter = self._pending_event_waiters.get(session_id)
            if waiter is None:
                waiter = asyncio.Event()
                self._pending_event_waiters[session_id] = waiter
            await waiter.wait()

        if self._pending_event_writes.get(session_id, 0) == 0:
            self._pending_event_waiters.pop(session_id, None)
            self._event_write_locks.pop(session_id, None)


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _looks_like_ninjatrader_contract(symbol: str | None) -> bool:
    if not symbol:
        return False
    return re.search(r"\s\d{2}-\d{2}$", symbol) is not None


def _as_optional_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            cleaned = value.strip()
            if not cleaned:
                return None
            return float(cleaned)
        except ValueError:
            return None
    return None
