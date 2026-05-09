"""ASP.NET SignalR live-timing client for livetiming.bike-promotion.com.

Protocol: SignalR 1.5 over WebSocket.
  1. GET /lt/negotiate → ConnectionToken
  2. ws:// /lt/connect?transport=webSockets&connectionToken=…
  3. GET /lt/start  (fire-and-forget, completes handshake)

Messages are JSON frames: {"M": [["<method>", <arg>], ...]}
Compressed frames use the "_" method with LZString.decompressFromUTF16 payload.

Reverse-engineered from devsimsek/nrdash and the getraceresults.com platform.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)

_BASE = "https://livetiming.bike-promotion.com"
_BASE_HTTP = "http://livetiming.bike-promotion.com"
_PROTO = "1.5"
_GROUP = "w"

_FLAG_MAP = {
    -1: "green", 0: "green",
    1: "warmup",
    2: "red",
    3: "yellow", 4: "safety_car", 7: "vsc",
    5: "chequered",
    6: "green",
}

_MARKER_MAP = {4: "pit", 5: "pit", 6: "out", 7: "out"}


@dataclass
class LiveSession:
    name: str = ""
    flag: str = "unknown"
    elapsed_us: int = 0
    time_limit_us: int = 0


@dataclass
class LiveRow:
    position: int = 0
    number: str = ""
    name: str = ""
    cls: str = ""
    gap: str = ""
    last_lap_us: int = 0
    best_lap_us: int = 0
    status: str = "racing"  # racing / pit / out


@dataclass
class LiveTimingState:
    session: LiveSession = field(default_factory=LiveSession)
    rows: list[LiveRow] = field(default_factory=list)
    connected: bool = False
    columns: list[str] = field(default_factory=list)


def us_to_laptime(us: int) -> str:
    """Convert microseconds to M:SS.mmm string."""
    if us <= 0:
        return ""
    total_ms = us / 1000
    minutes = int(total_ms // 60_000)
    seconds = (total_ms % 60_000) / 1000
    return f"{minutes}:{seconds:06.3f}" if minutes else f"{seconds:.3f}"


class EuroMotoLiveTiming:
    """Manages the SignalR WebSocket connection for live timing data."""

    def __init__(self, session: aiohttp.ClientSession, tenant_id: str = "c1") -> None:
        self._session = session
        self._tenant_id = tenant_id
        self._state = LiveTimingState()
        self._columns: list[str] = []
        self._raw_rows: dict[int, dict[int, Any]] = {}
        self._task: asyncio.Task | None = None
        self._callbacks: list[Callable[[LiveTimingState], None]] = []

    @property
    def state(self) -> LiveTimingState:
        return self._state

    def add_update_callback(self, cb: Callable[[LiveTimingState], None]) -> None:
        self._callbacks.append(cb)

    def _notify(self) -> None:
        for cb in self._callbacks:
            try:
                cb(self._state)
            except Exception:
                pass

    async def async_start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def async_stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._state.connected = False
        self._notify()

    async def _run(self) -> None:
        backoff = 15
        attempts = 0
        while True:
            try:
                await self._connect_once()
                backoff = 15
                attempts = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempts += 1
                lvl = _LOGGER.warning if attempts <= 3 else _LOGGER.debug
                lvl("EuroMoto live timing: connection failed (attempt %d): %s – retry in %ds", attempts, exc, backoff)
            self._state.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)

    async def _connect_once(self) -> None:
        ts = int(time.time() * 1000)
        params = {
            "clientProtocol": _PROTO,
            "_tk": self._tenant_id,
            "_gr": _GROUP,
            "_": ts,
        }
        # Try HTTPS first, fall back to HTTP
        base = _BASE
        data: dict = {}
        for candidate_base in (_BASE, _BASE_HTTP):
            try:
                async with self._session.get(
                    f"{candidate_base}/lt/negotiate",
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                base = candidate_base
                break
            except Exception as exc:
                _LOGGER.debug("Negotiate failed at %s: %s", candidate_base, exc)
                if candidate_base == _BASE_HTTP:
                    raise

        token: str = data.get("ConnectionToken", "")
        if not token:
            raise RuntimeError(f"No ConnectionToken in negotiate response: {data}")

        scheme = "wss" if base.startswith("https") else "ws"
        host = base.split("://", 1)[1]
        ws_url = (
            f"{scheme}://{host}/lt/connect"
            f"?transport=webSockets"
            f"&clientProtocol={_PROTO}"
            f"&_tk={quote(self._tenant_id, safe='')}"
            f"&_gr={_GROUP}"
            f"&connectionToken={quote(token, safe='')}"
            f"&tid=0"
        )
        _LOGGER.debug("EuroMoto live timing: connecting to %s", ws_url)
        async with self._session.ws_connect(
            ws_url,
            timeout=aiohttp.ClientTimeout(total=None),
            heartbeat=30,
        ) as ws:
            # Step 3: start handshake (fire-and-forget)
            asyncio.create_task(self._session.get(
                f"{base}/lt/start",
                params={**params, "transport": "webSockets", "connectionToken": token},
            ))
            self._state.connected = True
            self._notify()
            _LOGGER.info("EuroMoto live timing: connected (tenant=%s, base=%s)", self._tenant_id, base)

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        self._handle_frame(json.loads(msg.data))
                    except Exception as exc:
                        _LOGGER.debug("Frame parse error: %s", exc)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

        self._state.connected = False
        self._notify()
        _LOGGER.debug("EuroMoto live timing: WebSocket closed")

    # ── Frame handling ────────────────────────────────────────────────────────

    def _handle_frame(self, frame: dict) -> None:
        for item in frame.get("M", []):
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                self._dispatch(str(item[0]), item[1])

    def _dispatch(self, method: str, arg: Any) -> None:
        if method == "_":
            self._handle_compressed(arg)
        elif method == "r_l":
            self._handle_layout(arg)
        elif method == "r_i":
            self._handle_init(arg)
        elif method == "r_c":
            self._handle_changes(arg)
        elif method in ("h_h", "h_i"):
            self._handle_heat(arg)

    def _handle_compressed(self, payload: str) -> None:
        try:
            import lzstring  # optional dependency
            if "::" in payload:
                payload = payload[:payload.rfind("::")]
            batch = json.loads(lzstring.LZString().decompressFromUTF16(payload))
            for pair in batch:
                if len(pair) >= 2:
                    self._dispatch(str(pair[0]), pair[1])
        except ImportError:
            _LOGGER.debug("lz-string not installed – compressed live-timing frames skipped")
        except Exception as exc:
            _LOGGER.debug("LZString decode failed: %s", exc)

    def _handle_layout(self, arg: dict) -> None:
        cols = []
        for h in arg.get("h", []):
            name = h.get("n", "")
            if "p" in h:
                name = f"{name}_{h['p']}"
            cols.append(name.lower().replace(" ", "_"))
        self._columns = cols
        self._state.columns = cols[:]

    def _handle_init(self, arg: dict) -> None:
        if "l" in arg:
            self._handle_layout(arg["l"])
        self._raw_rows.clear()
        for change in arg.get("r", []):
            self._apply_change(change)
        self._rebuild_rows()

    def _handle_changes(self, changes: list) -> None:
        for change in changes:
            self._apply_change(change)
        self._rebuild_rows()

    def _apply_change(self, change: list) -> None:
        if len(change) < 3:
            return
        row_idx, col_idx, value = int(change[0]), int(change[1]), change[2]
        self._raw_rows.setdefault(row_idx, {})[col_idx] = value

    def _rebuild_rows(self) -> None:
        if not self._columns:
            return

        def _get(row: dict, *names: str) -> Any:
            for n in names:
                if n in self._columns:
                    v = row.get(self._columns.index(n))
                    if v is not None:
                        return v
            return None

        rows: list[LiveRow] = []
        for idx in sorted(self._raw_rows):
            raw = self._raw_rows[idx]
            marker = _get(raw, "marker")
            status = _MARKER_MAP.get(int(marker), "racing") if marker is not None else "racing"
            try:
                pos = int(_get(raw, "position") or (idx + 1))
                last_us = int(_get(raw, "lastroundtime", "last_round_time") or 0)
                best_us = int(_get(raw, "fastestroundtime", "fastest_round_time") or 0)
            except (ValueError, TypeError):
                pos, last_us, best_us = idx + 1, 0, 0
            rows.append(LiveRow(
                position=pos,
                number=str(_get(raw, "startnumber") or ""),
                name=str(_get(raw, "currentdriver", "team_name") or ""),
                cls=str(_get(raw, "class") or ""),
                gap=str(_get(raw, "hole", "gap") or ""),
                last_lap_us=last_us,
                best_lap_us=best_us,
                status=status,
            ))

        rows.sort(key=lambda r: r.position)
        self._state.rows = rows
        self._notify()

    def _handle_heat(self, arg: dict) -> None:
        f = arg.get("f", -1)
        self._state.session = LiveSession(
            name=str(arg.get("n", "")),
            flag=_FLAG_MAP.get(int(f) if f is not None else -1, "unknown"),
            elapsed_us=int(arg.get("e", 0)),
            time_limit_us=int(arg.get("lt", 0)),
        )
        self._notify()
