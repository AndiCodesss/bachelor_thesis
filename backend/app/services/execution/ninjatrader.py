"""HTTP client and executor for the NinjaTrader trading platform.

NinjaTrader runs on Windows as a desktop application. This module talks to a
small HTTP bridge service that sits next to NinjaTrader and translates our
JSON commands into real broker orders. The communication flow is:

    StreamCopier backend  --(HTTP)-->  Bridge service  --(API)-->  NinjaTrader

Because the backend may run inside WSL while NinjaTrader runs on the Windows
host, a WSL fallback mechanism is included to resolve the correct IP address.
"""

from __future__ import annotations

from datetime import UTC, datetime
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import Settings
from app.models.domain import ExecutionResult, StreamSession, TradeIntent


class BridgeUnavailableError(RuntimeError):
    """Raised when the NinjaTrader bridge cannot be reached (connection never opened).

    Kept distinct from a generic bridge error so callers can treat a missing bridge
    as a benign "disconnected" state -- the app keeps running, just without copying
    trades -- instead of a hard failure that spams the logs.
    """


class NinjaTraderBridgeClient:
    """Low-level HTTP client that sends requests to the NinjaTrader bridge.

    Handles connection details (timeouts, auth headers) and transparently
    retries on a WSL fallback URL when the primary URL is unreachable.
    """
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        timeout_s = _bridge_timeout_seconds(settings)
        self._client = httpx.AsyncClient(
            # Keep read/write/pool at the full configured budget (the bridge needs
            # time to actually place an order), but cap the CONNECT phase so an
            # absent bridge fails fast (~1.5s) instead of blocking the caller for
            # the whole budget on every probe.
            timeout=httpx.Timeout(timeout_s, connect=min(1.5, timeout_s)),
            headers=_bridge_headers(settings),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def post_command(self, payload: dict[str, Any]) -> httpx.Response:
        """Send a trade command (entry, exit, etc.) to the bridge.

        Commands are NOT idempotent (a duplicate POST can double-fill), so the
        WSL fallback URL is only tried when the failure happened before the
        request was sent.
        """
        return await self._request(
            "POST",
            "/api/stream-copier/commands",
            error_context="command request",
            idempotent=False,
            json=payload,
        )

    async def fetch_state(
        self,
        *,
        account: str | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        """Query the bridge for the current account/position state."""
        params: dict[str, str] = {}
        if account:
            params["account"] = account
        if symbol:
            params["symbol"] = symbol

        response = await self._request(
            "GET",
            "/api/stream-copier/state",
            error_context="state request",
            require_success_status=True,
            idempotent=True,
            params=params,
        )
        return _decode_state_payload(response)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        error_context: str,
        require_success_status: bool = False,
        idempotent: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        # Try the primary URL first, then the WSL fallback if it exists.
        # This lets the same code work whether running natively on Windows
        # or inside a WSL Linux environment.
        last_error: Exception | None = None
        for base_url in _bridge_base_urls(self._settings):
            endpoint = f"{base_url}{path}"
            try:
                response = await self._client.request(method, endpoint, **kwargs)
                if require_success_status:
                    response.raise_for_status()
                return response
            except Exception as error:
                last_error = error
                # For a non-idempotent request, only fall through to the next
                # URL when the connection was never established; a post-send
                # failure (read timeout, protocol error) may mean the order was
                # already submitted, so retrying could double-fill.
                if not idempotent and not _is_pre_send_error(error):
                    break

        if last_error is not None and _is_pre_send_error(last_error):
            # The connection never opened -> the bridge is not reachable (not
            # running, wrong URL, or blocked). Surface a distinct type so callers
            # can degrade gracefully instead of treating it as a hard error.
            raise BridgeUnavailableError(
                f"NinjaTrader bridge {error_context} failed: {last_error}"
            ) from last_error
        raise RuntimeError(f"NinjaTrader bridge {error_context} failed: {last_error}") from last_error


class NinjaTraderExecutor:
    """Routes trade commands to a local NinjaTrader bridge HTTP service.

    The bridge is expected to expose POST /api/stream-copier/commands and return
    JSON (or plain text) with order acceptance details.
    """

    def __init__(self, settings: Settings, *, bridge_client: NinjaTraderBridgeClient) -> None:
        self._settings = settings
        self._bridge_client = bridge_client

    async def execute(
        self,
        session: StreamSession,
        intent: TradeIntent,
        *,
        contract_size: int | None = None,
    ) -> ExecutionResult:
        """Send a trade intent to NinjaTrader and return an ExecutionResult.

        The result is marked approved only when the bridge responds with a
        success status. Network errors and HTTP 4xx/5xx are treated as rejections.
        ``contract_size`` overrides the per-session default for this order only
        (used by manual trades) without mutating shared session state.
        """
        payload = self._build_payload(session=session, intent=intent, contract_size=contract_size)
        position_snapshot = session.position.model_copy(deep=True) if session.position else None
        try:
            response = await self._bridge_client.post_command(payload)
        except Exception as error:
            # The request may have reached the broker before the failure, so the
            # outcome is unknown -- flag it uncertain so the caller reconciles.
            return ExecutionResult(
                session_id=session.id,
                action=intent.tag,
                approved=False,
                uncertain=True,
                message=f"NinjaTrader bridge error: {error}",
                market_price=session.market.last_price,
                position=position_snapshot,
            )

        bridge_message = self._extract_message(response)
        verdict = self._classify_response(response)
        if verdict == "accepted":
            return ExecutionResult(
                session_id=session.id,
                action=intent.tag,
                approved=True,
                message=f"NinjaTrader accepted: {bridge_message}",
                market_price=session.market.last_price,
                position=position_snapshot,
            )

        status_note = f" (HTTP {response.status_code})" if response.status_code >= 400 else ""
        if verdict == "rejected":
            return ExecutionResult(
                session_id=session.id,
                action=intent.tag,
                approved=False,
                message=f"NinjaTrader rejected: {bridge_message}{status_note}",
                market_price=session.market.last_price,
                position=position_snapshot,
            )

        # "uncertain": a 2xx whose body we could not confirm as success.
        return ExecutionResult(
            session_id=session.id,
            action=intent.tag,
            approved=False,
            uncertain=True,
            message=f"NinjaTrader response could not be confirmed: {bridge_message}{status_note}",
            market_price=session.market.last_price,
            position=position_snapshot,
        )

    def _build_payload(
        self,
        *,
        session: StreamSession,
        intent: TradeIntent,
        contract_size: int | None = None,
    ) -> dict[str, Any]:
        """Build the JSON payload the bridge expects.

        Account and symbol are resolved with a priority chain:
        per-session override > global setting > value from the intent/market.
        """
        configured_account = (session.config.broker_account_override or self._settings.ninjatrader_account or "").strip()
        configured_symbol = (session.config.broker_symbol_override or self._settings.ninjatrader_symbol or "").strip()
        resolved_symbol = configured_symbol or intent.symbol or session.market.symbol
        effective_contract_size = contract_size if contract_size is not None else session.config.default_contract_size
        return {
            "intent_id": intent.id,
            "session_id": session.id,
            "account": configured_account or None,
            "symbol": resolved_symbol,
            "action": _as_value(intent.tag),
            "side": _as_value(intent.side),
            "quantity_hint": intent.quantity_hint,
            "default_contract_size": effective_contract_size,
            "time_in_force": self._settings.ninjatrader_time_in_force,
            "entry_price": intent.entry_price,
            "stop_price": intent.stop_price,
            "target_price": intent.target_price,
            "market_price": session.market.last_price,
            "evidence_text": intent.evidence_text,
            "sent_at": datetime.now(UTC).isoformat(),
        }

    def _extract_message(self, response: httpx.Response) -> str:
        """Pull a human-readable message from the bridge response.

        Tries JSON first, falls back to raw text. Returns "ok" when empty.
        """
        try:
            payload = response.json()
        except Exception:
            text = response.text.strip()
            return text[:200] if text else "ok"

        if isinstance(payload, dict):
            # Bridge may use different key names depending on version
            for key in ("message", "status", "result", "orderId", "order_id"):
                value = payload.get(key)
                if value:
                    return str(value)
        return "ok"

    def _classify_response(self, response: httpx.Response) -> str:
        """Classify a bridge response as 'accepted', 'rejected', or 'uncertain'.

        Fail-closed for the real contract: the bridge always returns a JSON body
        carrying ``ok`` (and an order id on success), so a 4xx, an explicit
        ``ok: false``, an unparseable body, or a 2xx that confirms neither is
        never treated as an accepted order. Anything we cannot positively
        confirm is 'uncertain', prompting the caller to reconcile from the
        broker rather than silently assume success or failure.
        """
        try:
            payload = response.json()
        except Exception:
            if response.status_code >= 400:
                return "rejected"
            return "uncertain"

        if isinstance(payload, dict):
            code = str(payload.get("code") or "")
            # The C# bridge returns Ok=false as HTTP 400. Dispatch failures are
            # still ambiguous because the command may have reached NinjaTrader
            # before the bridge timed out or abandoned the wait.
            if code.startswith("dispatch_"):
                return "uncertain"
            if "ok" in payload:
                if payload.get("ok"):
                    return "accepted"
                return "rejected"
            if payload.get("orderId") or payload.get("order_id"):
                return "accepted"
        if response.status_code >= 400:
            return "rejected"
        return "uncertain"


def _is_pre_send_error(error: Exception) -> bool:
    """True when a request failed before being sent (connection never opened).

    Such failures are safe to retry on a fallback URL even for non-idempotent
    requests; post-send failures are not, because the order may already be in
    flight at the broker.
    """
    return isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))


def _decode_state_payload(response: httpx.Response) -> dict[str, Any]:
    """Normalize the bridge's state response into a dict.

    Handles JSON dicts, non-dict JSON values, and plain text gracefully.
    """
    try:
        payload = response.json()
    except Exception:
        text = response.text.strip()
        return {"ok": True, "code": "ok", "message": text[:200] if text else "ok"}

    if isinstance(payload, dict):
        return payload

    return {"ok": True, "code": "ok", "message": str(payload)}


def _as_value(value: Any) -> Any:
    """Unwrap Python enums to their primitive value for JSON serialization."""
    if value is None:
        return None
    if hasattr(value, "value"):
        return value.value
    return value


def _bridge_timeout_seconds(settings: Settings) -> float:
    return max(0.25, settings.ninjatrader_bridge_timeout_ms / 1000)


def _bridge_headers(settings: Settings) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.ninjatrader_bridge_token:
        headers["Authorization"] = f"Bearer {settings.ninjatrader_bridge_token}"
    return headers


def _bridge_base_urls(settings: Settings) -> list[str]:
    """Return the list of bridge URLs to try, primary first.

    When running inside WSL, "localhost" points to the Linux VM, not Windows.
    A fallback URL pointing to the Windows host IP is appended so the bridge
    (which runs on Windows alongside NinjaTrader) can still be reached.
    """
    primary = settings.ninjatrader_bridge_url.rstrip("/")
    urls = [primary]
    fallback = _wsl_windows_host_url(primary)
    if fallback and fallback not in urls:
        urls.append(fallback)
    return urls


def _wsl_windows_host_url(url: str) -> str | None:
    """Rewrite a localhost URL to the Windows host IP when running in WSL.

    Only activates when the WSL_DISTRO_NAME env var is set (i.e., inside WSL)
    and the URL targets localhost/127.0.0.1. Returns None otherwise.
    """
    if not os.environ.get("WSL_DISTRO_NAME"):
        return None

    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost"}:
        return None

    windows_host_ip = _resolve_wsl_windows_host_ip()
    if not windows_host_ip:
        return None

    port = parsed.port
    netloc = f"{windows_host_ip}:{port}" if port is not None else windows_host_ip
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", "")).rstrip("/")


def _resolve_wsl_windows_host_ip() -> str | None:
    """Read the Windows host IP from /etc/resolv.conf.

    Inside WSL, the DNS nameserver entry in resolv.conf typically points to the
    Windows host, making it a reliable way to discover that IP address.
    """
    resolv_conf = Path("/etc/resolv.conf")
    if not resolv_conf.exists():
        return None

    try:
        for line in resolv_conf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line.startswith("nameserver "):
                continue
            candidate = line.split(maxsplit=1)[1].strip()
            if candidate:
                return candidate
    except Exception:
        return None

    return None
