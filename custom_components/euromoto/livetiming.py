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

_HOST = "livetiming.raceresults.de"
_PROTO = "1.5"
_GROUP = "w"         # live timing group
_GROUP_TICKER = "t"  # ticker / incident feed

# Some SignalR servers enforce an Origin check – send browser-like headers.
_NEGOTIATE_HEADERS = {
    "Origin": f"https://{_HOST}",
    "Referer": f"https://{_HOST}/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Candidate (base, hub_path) pairs tried in order during negotiate.
# Paths are ordered by likelihood based on known raceresults.de architecture.
_NEGOTIATE_CANDIDATES = [
    (f"https://{_HOST}", "/lt"),
    (f"https://{_HOST}", "/signalr"),
    (f"https://{_HOST}", "/hubs"),
    (f"https://{_HOST}", "/hub"),
    (f"https://{_HOST}", "/timing"),
    (f"https://{_HOST}", "/race"),
    (f"https://{_HOST}", "/api"),
    (f"https://{_HOST}", "/live"),
    (f"https://{_HOST}", "/channel"),
    (f"https://{_HOST}", "/realtime"),
    (f"https://{_HOST}", "/push"),
    (f"https://{_HOST}", "/ws"),
    (f"https://{_HOST}", "/socket"),
    # Channel-prefixed paths (tenant ID embedded in URL)
    (f"https://{_HOST}", "/c1"),
    (f"https://{_HOST}", "/lt/c1"),
    (f"https://{_HOST}", "/channel/c1"),
    (f"https://{_HOST}", ""),
    (f"http://{_HOST}", "/lt"),
    (f"http://{_HOST}", "/signalr"),
    (f"http://{_HOST}", "/hubs"),
    (f"http://{_HOST}", ""),
]

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
class LiveIncident:
    timestamp: str = ""
    rider: str = ""
    number: str = ""
    text: str = ""
    kind: str = ""  # "crash", "penalty", "info", "sc", "flag"


@dataclass
class LiveTimingState:
    session: LiveSession = field(default_factory=LiveSession)
    rows: list[LiveRow] = field(default_factory=list)
    incidents: list[LiveIncident] = field(default_factory=list)
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
        self._ticker_task: asyncio.Task | None = None
        self._callbacks: list[Callable[[LiveTimingState], None]] = []
        self._background_tasks: set[asyncio.Task] = set()
        self._hub_path_cached = False
        self._cached_hub_path: str | None = None

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
        if not (self._task and not self._task.done()):
            self._task = asyncio.create_task(self._run(_GROUP))
        if not (self._ticker_task and not self._ticker_task.done()):
            self._ticker_task = asyncio.create_task(self._run(_GROUP_TICKER))

    async def async_stop(self) -> None:
        for task in (self._task, self._ticker_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._task = None
        self._ticker_task = None
        self._state.connected = False
        self._notify()

    async def _run(self, group: str) -> None:
        backoff = 15
        attempts = 0
        while True:
            try:
                await self._connect_once(group)
                backoff = 15
                attempts = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                attempts += 1
                # INFO is not shown in the HA warning panel; reserve WARNING for
                # genuinely unexpected errors, not expected 404s when no session runs.
                lvl = _LOGGER.info if attempts == 1 else _LOGGER.debug
                lvl(
                    "EuroMoto live timing [%s]: connection failed (attempt %d): %s – retry in %ds",
                    group, attempts, exc, backoff,
                )
            if group == _GROUP:
                self._state.connected = False
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)

    async def _discover_hub_path(self) -> str | None:
        """Fetch the page source and extract the SignalR hub path from the JS bundle.

        Cached after the first attempt (success or failure) so repeated reconnects
        (this runs once per group per reconnect cycle) don't re-fetch the homepage
        and up to 8 JS bundles on every retry.
        """
        if self._hub_path_cached:
            return self._cached_hub_path

        result = await self._discover_hub_path_uncached()
        self._cached_hub_path = result
        self._hub_path_cached = True
        return result

    async def _discover_hub_path_uncached(self) -> str | None:
        import re

        try:
            async with self._session.get(
                f"https://{_HOST}/",
                headers=_NEGOTIATE_HEADERS,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    return None
                html = await resp.text()
        except Exception:
            return None

        script_urls = re.findall(
            r'<script[^>]+src=["\']([^"\']+\.js(?:\?[^"\']*)?)["\']', html
        )
        for src in script_urls[:8]:
            url = src if src.startswith("http") else f"https://{_HOST}{src}"
            try:
                async with self._session.get(
                    url,
                    headers=_NEGOTIATE_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status != 200:
                        continue
                    js = await resp.text()
            except Exception:
                continue

            # Look for hub path strings adjacent to "negotiate"
            for m in re.finditer(r'["\']([/][\w/-]{1,40})["\']', js):
                candidate = m.group(1)
                if any(
                    s in candidate
                    for s in ("/lt", "/signalr", "/hub", "/timing", "/race", "/live", "/push", "/ws")
                ):
                    _LOGGER.debug(
                        "EuroMoto: auto-discovered hub path candidate: %s", candidate
                    )
                    return candidate.rstrip("/")

        return None

    async def _connect_once(self, group: str = _GROUP) -> None:
        ts = int(time.time() * 1000)
        params = {
            "clientProtocol": _PROTO,
            "_tk": self._tenant_id,
            "_gr": group,
            "_": ts,
        }
        # Probe candidate (base, hub_path) pairs until negotiate succeeds
        base = ""
        hub_path = ""
        data: dict = {}
        last_exc: Exception = RuntimeError("No negotiate candidate succeeded")

        # Build candidates: hardcoded list first, then auto-discovered path
        candidates = list(_NEGOTIATE_CANDIDATES)
        discovered = await self._discover_hub_path()
        if discovered:
            _LOGGER.debug("EuroMoto: prepending auto-discovered path %s", discovered)
            candidates.insert(0, (f"https://{_HOST}", discovered))

        for candidate_base, candidate_hub in candidates:
            url = f"{candidate_base}{candidate_hub}/negotiate"
            try:
                async with self._session.get(
                    url,
                    params=params,
                    headers=_NEGOTIATE_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
                base = candidate_base
                hub_path = candidate_hub
                _LOGGER.debug("Negotiate succeeded at %s (group=%s)", url, group)
                break
            except Exception as exc:
                _LOGGER.debug("Negotiate failed at %s: %s", url, exc)
                last_exc = exc
        else:
            raise last_exc

        token: str = data.get("ConnectionToken", "")
        if not token:
            raise RuntimeError(f"No ConnectionToken in negotiate response: {data}")

        scheme = "wss" if base.startswith("https") else "ws"
        host = base.split("://", 1)[1]
        ws_url = (
            f"{scheme}://{host}{hub_path}/connect"
            f"?transport=webSockets"
            f"&clientProtocol={_PROTO}"
            f"&_tk={quote(self._tenant_id, safe='')}"
            f"&_gr={group}"
            f"&connectionToken={quote(token, safe='')}"
            f"&tid=0"
        )
        _LOGGER.debug("EuroMoto live timing [%s]: connecting to %s", group, ws_url)
        async with self._session.ws_connect(
            ws_url,
            timeout=aiohttp.ClientTimeout(total=None),
            # heartbeat omitted: aiohttp's internal heartbeat task raises
            # ClientConnectionResetError on close → "Task exception was never retrieved"
        ) as ws:
            # Step 3: start handshake (fire-and-forget, exceptions silenced)
            async def _do_start() -> None:
                try:
                    async with self._session.get(
                        f"{base}{hub_path}/start",
                        params={**params, "transport": "webSockets", "connectionToken": token},
                        headers=_NEGOTIATE_HEADERS,
                        timeout=aiohttp.ClientTimeout(total=5),
                    ):
                        pass
                except Exception:
                    pass

            start_task = asyncio.create_task(_do_start())
            self._background_tasks.add(start_task)
            start_task.add_done_callback(self._background_tasks.discard)
            if group == _GROUP:
                self._state.connected = True
                self._notify()
            _LOGGER.info(
                "EuroMoto live timing [%s]: connected (tenant=%s, base=%s)",
                group, self._tenant_id, base,
            )

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        self._handle_frame(json.loads(msg.data))
                    except Exception as exc:
                        _LOGGER.debug("Frame parse error [%s]: %s", group, exc)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

        if group == _GROUP:
            self._state.connected = False
            self._notify()
        _LOGGER.debug("EuroMoto live timing [%s]: WebSocket closed", group)

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
        elif method == "t_i":
            self._handle_ticker(arg, replace=True)
        elif method in ("t_m", "ticker"):
            self._handle_ticker(arg)

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
            self._safe_apply_change(change)
        self._rebuild_rows()

    def _handle_changes(self, changes: list) -> None:
        for change in changes:
            self._safe_apply_change(change)
        self._rebuild_rows()

    def _safe_apply_change(self, change: list) -> None:
        """Apply one row/col update; a single malformed entry must not drop the whole batch."""
        try:
            self._apply_change(change)
        except (ValueError, TypeError, IndexError) as exc:
            _LOGGER.debug("Skipping malformed row change %r: %s", change, exc)

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
            try:
                status = _MARKER_MAP.get(int(marker), "racing") if marker is not None else "racing"
            except (ValueError, TypeError):
                status = "racing"
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

    def _handle_ticker(self, arg: Any, replace: bool = False) -> None:
        """Handle ticker/incident messages from the t channel.

        `replace=True` (init frame "t_i") resets the incident list first – otherwise
        every reconnect during a race weekend would re-prepend the same history,
        duplicating entries in LiveIncidentsSensor.
        """
        import datetime as _dt

        if replace:
            self._state.incidents = []

        if isinstance(arg, dict):
            items = arg.get("m", arg.get("items", [arg]))
        elif isinstance(arg, list):
            items = arg
        else:
            items = [{"text": str(arg)}]

        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("t", item.get("text", item.get("m", "")))).strip()
            if not text:
                continue
            number = str(item.get("n", item.get("number", item.get("nr", ""))))
            rider = str(item.get("d", item.get("driver", item.get("name", ""))))
            ts = str(item.get("ts", item.get("time", _dt.datetime.now().strftime("%H:%M:%S"))))

            # Classify incident type from keywords in text
            tl = text.lower()
            if any(w in tl for w in ("crash", "sturz", "fall", "retired", "dnf", "ausfall")):
                kind = "crash"
            elif any(w in tl for w in ("safety car", "sc", "safetyCar")):
                kind = "sc"
            elif any(w in tl for w in ("penalty", "strafe", "drive through", "long lap")):
                kind = "penalty"
            elif any(w in tl for w in ("red flag", "rote flagge", "abbruch")):
                kind = "flag"
            else:
                kind = "info"

            incident = LiveIncident(
                timestamp=ts, rider=rider, number=number, text=text, kind=kind
            )
            # Keep only the last 20 incidents
            self._state.incidents = ([incident] + self._state.incidents)[:20]

        if items:
            self._notify()

    def _handle_heat(self, arg: dict) -> None:
        f = arg.get("f")
        try:
            flag_key = int(f) if f is not None else -1
        except (ValueError, TypeError):
            flag_key = -1
        try:
            elapsed = int(arg.get("e", 0))
            time_limit = int(arg.get("lt", 0))
        except (ValueError, TypeError):
            elapsed, time_limit = 0, 0
        self._state.session = LiveSession(
            name=str(arg.get("n", "")),
            flag=_FLAG_MAP.get(flag_key, "unknown"),
            elapsed_us=elapsed,
            time_limit_us=time_limit,
        )
        self._notify()
