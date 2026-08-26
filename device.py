"""Stewart SL Device."""

import asyncio
import logging
import re
import socket
import time

from homeassistant.core import HomeAssistant, callback

from .const import (
    SL_CONNECT_TIMEOUT,
    SL_KEEPALIVE_INTERVAL,
    SL_KEEPALIVE_TIMEOUT,
    SL_LOGIN_TIMEOUT,
    SL_PORT,
    SL_RECONNECT_DELAY,
    SL_RECONNECT_DELAY_MAX,
    SL_WRITE_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)

DEVICE_AUDIO_MODE = "AUDMODE"
DEVICE_AUDIO_MODES = "AUDMODEL"
DEVICE_AUDIO_MODE_COUNT = "AUDMODECOUNT"
DEVICE_AUDIO_TYPE = "AUDTYPE"
DEVICE_LIPSYNC = "LIPSYNC"
DEVICE_MODEL = "DEVICE"
DEVICE_MUTE = "MUTE"
DEVICE_MUTEOFF = "MUTEOFF"
DEVICE_MUTEON = "MUTEON"
DEVICE_POWER = "POWER"
DEVICE_SOURCE = "SRC"
DEVICE_SOURCES = "SRCS"
DEVICE_SOURCE_COUNT = "SRCCOUNT"
DEVICE_VIDEO_TYPE = "VIDTYPE"
DEVICE_VOICING = "RPVOI"
DEVICE_VOICINGS = "RPVOIS"
DEVICE_VOICING_COUNT = "RPVOICOUNT"
DEVICE_VOL = "VOL"
DEVICE_VOL_RANGE = 400.0

DEVICE_SUBS = (
    DEVICE_AUDIO_MODE,
    DEVICE_AUDIO_TYPE,
    DEVICE_LIPSYNC,
    DEVICE_MUTE,
    DEVICE_POWER,
    DEVICE_SOURCE,
    DEVICE_VIDEO_TYPE,
    DEVICE_VOICING,
    DEVICE_VOL
)

class SLDevice:
    """Represents a single SL device."""

    def __init__(self, hass: HomeAssistant, host: str) -> None:
        """Set up class."""

        self._hass = hass
        self._host = host
        self._device_id = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._init_event = asyncio.Event()
        self._online = False
        self._callback = None
        self._listener = None
        self._keepalive = None
        self._reconnector = None
        self._resumer = None
        self._closing = False
        self._conn_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._last_rx = 0.0
        self._data = {}
        self._data[DEVICE_SOURCES] = []
        self._data[DEVICE_AUDIO_MODES] = []
        self._data[DEVICE_VOICINGS] = []
        self._response_re = re.compile("^\\!([A-Z0-9]+)(\\(([^)]+)\\)(\"([^\"]+)\")?)?")

    @property
    def device_id(self) -> str:
        """Use the mac."""
        return self._device_id

    @property
    def online(self) -> bool:
        """Return status."""
        return self._online

    @property
    def data(self) -> dict:
        """Return data."""
        return self._data

    def get_data_value(self, name: str):
        """Return the named data."""
        return self._data.get(name)

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    async def open_connection(self, test: bool = False) -> bool:
        """Establish a connection, unless one is already up."""
        if self.online:
            return True

        async with self._conn_lock:
            # Another task may have connected while we waited for the lock.
            if self.online:
                return True
            return await self._connect(test)

    async def _connect(self, test: bool = False) -> bool:
        """Open the socket and run the handshake. Caller holds _conn_lock."""
        writer = None
        try:
            _LOGGER.debug("Establish new connection to %s", self._host)
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, SL_PORT),
                timeout=SL_CONNECT_TIMEOUT,
            )
            self._set_socket_options(writer)
            writer.write(b"!DEVICE?\r")
            await asyncio.wait_for(writer.drain(), timeout=SL_WRITE_TIMEOUT)
            devresp = await asyncio.wait_for(
                reader.readuntil(b'\r'), timeout=SL_LOGIN_TIMEOUT
            )
            resp = self.decode_response(devresp)
            if resp is None:
                _LOGGER.error("Unexpected handshake response from %s", self._host)
                await self._close_writer(writer)
                return False
            model = self._data[DEVICE_MODEL] = resp["data"]
            self._device_id = f"{model}_{self._host}"
            if test:
                await self._close_writer(writer)
                return True

            self._reader = reader
            self._writer = writer
            self._last_rx = time.monotonic()
            self._init_event.clear()
            self._online = True
            self._listener = asyncio.create_task(self.listener())
            self._keepalive = asyncio.create_task(self._keepalive_loop())
            if self._callback is not None:
                # We have been up before: this is a reconnect, so the device
                # needs its subscriptions and our state needs a refresh.
                self._resumer = asyncio.create_task(self._resume())

        except (
            TimeoutError,
            OSError,
            asyncio.IncompleteReadError,
            asyncio.LimitOverrunError,
        ) as err:
            self._online = False
            if writer is not None:
                await self._close_writer(writer)
            if asyncio.current_task() is self._reconnector:
                # Retrying in the background: do not spam the log.
                _LOGGER.debug("Connect sequence error %s", err)
            else:
                _LOGGER.error("Connect sequence error %s", err)
            raise ConnectionError("Connect sequence error") from err

        return True

    @staticmethod
    def _set_socket_options(writer: asyncio.StreamWriter) -> None:
        """Ask the kernel to notice a link that has gone away."""
        sock = writer.get_extra_info("socket")
        if sock is None:
            return
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for name, value in (
                ("TCP_KEEPIDLE", 30),
                ("TCP_KEEPALIVE", 30),
                ("TCP_KEEPINTVL", 10),
                ("TCP_KEEPCNT", 3),
            ):
                opt = getattr(socket, name, None)
                if opt is not None:
                    sock.setsockopt(socket.IPPROTO_TCP, opt, value)
        except OSError as err:
            _LOGGER.debug("Could not set socket options: %s", err)

    @staticmethod
    async def _close_writer(writer: asyncio.StreamWriter) -> None:
        """Close a writer and wait for the transport to go away."""
        try:
            writer.close()
            await writer.wait_closed()
        except (OSError, asyncio.IncompleteReadError) as err:
            _LOGGER.debug("Error while closing connection: %s", err)

    def _handle_disconnect(self) -> None:
        """Tear down a dead connection and schedule a reconnect.

        Must stay synchronous: it runs from the listener's finally block,
        which may be executing because the task was cancelled.
        """
        was_online = self._online
        self._online = False
        self._init_event.clear()
        writer, self._writer = self._writer, None
        self._reader = None
        if writer is not None:
            try:
                writer.close()
            except OSError as err:
                _LOGGER.debug("Error while closing connection: %s", err)

        current = asyncio.current_task()
        if self._keepalive is not None and self._keepalive is not current:
            self._keepalive.cancel()
        self._keepalive = None

        if was_online and self._callback is not None:
            # Let the entities go unavailable instead of silently lying.
            self._callback(self._data)

        if self._closing:
            return
        if self._reconnector is None or self._reconnector.done():
            self._reconnector = asyncio.create_task(self._reconnect())

    async def _reconnect(self) -> None:
        """Reconnect in the background, backing off between attempts."""
        delay = SL_RECONNECT_DELAY
        while not self._closing and not self._online:
            _LOGGER.debug("Reconnecting to %s in %ss", self._host, delay)
            await asyncio.sleep(delay)
            if self._closing or self._online:
                return
            try:
                if await self.open_connection():
                    _LOGGER.info("Reconnected to %s", self._host)
                    return
            except (ConnectionError, TimeoutError, OSError) as err:
                _LOGGER.debug("Reconnect to %s failed: %s", self._host, err)
            delay = min(delay * 2, SL_RECONNECT_DELAY_MAX)

    async def _resume(self) -> None:
        """Restore the session after a reconnect."""
        try:
            await self._init_sequence()
        except (TimeoutError, ConnectionError, OSError) as err:
            _LOGGER.warning("Could not restore session with %s: %s", self._host, err)

    async def _keepalive_loop(self) -> None:
        """Probe the link so a silently dead socket does not go unnoticed."""
        while True:
            await asyncio.sleep(SL_KEEPALIVE_INTERVAL)
            if not self._online:
                return
            if time.monotonic() - self._last_rx < SL_KEEPALIVE_INTERVAL:
                # The device is chatting to us, no probe needed.
                continue
            mark = self._last_rx
            try:
                await self.send_query(DEVICE_MODEL)
            except (ConnectionError, TimeoutError, OSError) as err:
                _LOGGER.warning("Keepalive to %s failed: %s", self._host, err)
                self._force_disconnect()
                return
            await asyncio.sleep(SL_KEEPALIVE_TIMEOUT)
            if self._online and self._last_rx == mark:
                _LOGGER.warning(
                    "No reply from %s within %ss, dropping connection",
                    self._host,
                    SL_KEEPALIVE_TIMEOUT,
                )
                self._force_disconnect()
                return

    def _force_disconnect(self) -> None:
        """Abort the transport so the listener unblocks and cleans up."""
        writer = self._writer
        if writer is None:
            self._handle_disconnect()
            return
        transport = writer.transport
        try:
            if transport is not None:
                transport.abort()
            else:
                writer.close()
        except OSError as err:
            _LOGGER.debug("Error while aborting connection: %s", err)

    async def async_close(self) -> None:
        """Shut down for good (config entry unload)."""
        self._closing = True
        for task in (self._reconnector, self._resumer, self._keepalive, self._listener):
            if task is not None:
                task.cancel()
        self._reconnector = self._resumer = self._keepalive = self._listener = None
        writer, self._writer = self._writer, None
        self._reader = None
        self._online = False
        if writer is not None:
            await self._close_writer(writer)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    async def send_to_device(self, reqstr: str) -> None:
        """Make an API call."""
        if not await self.open_connection():
            raise ConnectionError("No connection to device")

        async with self._write_lock:
            writer = self._writer
            if writer is None or not self._online:
                raise ConnectionError("No connection to device")
            _LOGGER.debug("-> %s", reqstr)
            try:
                writer.write(reqstr.encode("ascii"))
                await asyncio.wait_for(writer.drain(), timeout=SL_WRITE_TIMEOUT)
            except (TimeoutError, OSError) as err:
                _LOGGER.warning("Write to %s failed: %s", self._host, err)
                self._force_disconnect()
                raise ConnectionError("Write failed") from err

    async def send_query(self, method: str) -> None:
        """Format and send command."""
        reqstr = f"!{method}?\r"
        await self.send_to_device(reqstr)

    async def send_command(self, method: str, data=None) -> None:
        """Format and send command."""
        reqstr = f"!{method}\r" if data is None else f"!{method}({data})\r"
        await self.send_to_device(reqstr)

    def decode_response(self, resp: bytes) -> dict:
        """Decode the response."""
        respstr = resp.decode("ascii", errors="replace")
        _LOGGER.debug("<- %s", respstr)
        m = self._response_re.match(respstr)
        if m is None:
            return None
        return {"method": m.group(1), "data": m.group(3), "extra": m.group(5) }

    async def test_connection(self) -> bool:
        """Test a connect."""
        return await self.open_connection(test=True)

    async def update_data(self) -> bool:
        """Stuff that has to be polled."""
        # return await self.send_command("environment.getcontrolblocks",{"type": "Sensor", "valuetype": "Temperature"})
        return True

    async def _init_sequence(self, data_callback: callback = None) -> None:
        """Read the lists and current state, then subscribe to updates."""
        await self.send_query(DEVICE_SOURCES)
        await self.send_query(DEVICE_AUDIO_MODES)
        await self.send_query(DEVICE_VOICINGS)
        await self.send_query(DEVICE_MUTE)
        await asyncio.wait_for(self._init_event.wait(), timeout=SL_LOGIN_TIMEOUT)

        if data_callback is not None:
            self._callback = data_callback
        for sub in DEVICE_SUBS:
            await self.send_query(sub)
        await self.send_command("VERB", "1")

    async def async_init(self, data_callback: callback) -> dict:
        """Query position and wait for response."""
        await self._init_sequence(data_callback)
        return self._data

    # ------------------------------------------------------------------
    # Receiving
    # ------------------------------------------------------------------

    async def listener(self) -> None:
        """Listen for status updates from device."""
        try:
            while True:
                buf = await self._reader.readuntil(b'\r')
                self._last_rx = time.monotonic()
                self._handle_response(buf)
        except asyncio.CancelledError:
            raise
        except asyncio.IncompleteReadError:
            _LOGGER.warning("Connection to %s closed by device", self._host)
        except (OSError, asyncio.LimitOverrunError) as err:
            _LOGGER.warning("Connection to %s lost: %s", self._host, err)
        except Exception:  # noqa: BLE001 - never let the listener die quietly
            _LOGGER.exception("Unexpected error reading from %s", self._host)
        finally:
            self._handle_disconnect()

    def _handle_response(self, buf: bytes) -> None:
        """Decode one message and update our state."""
        resp = self.decode_response(buf)
        if resp is None:
            return

        method = resp.get("method")
        data = resp.get("data")
        if method is None:
            return

        if method in [DEVICE_MUTEOFF, DEVICE_MUTEON]:
            data = method
            method = DEVICE_MUTE
        if not self._init_event.is_set():
            if method == DEVICE_SOURCE:
                self._data[DEVICE_SOURCES][int(data)] = resp.get("extra")
            elif method == DEVICE_SOURCE_COUNT:
                self._data[DEVICE_SOURCES] = [None for i in range(int(data))]
            elif method == DEVICE_AUDIO_MODE:
                self._data[DEVICE_AUDIO_MODES][int(data)] = resp.get("extra")
            elif method == DEVICE_AUDIO_MODE_COUNT:
                self._data[DEVICE_AUDIO_MODES] = [None for i in range(int(data))]
            elif method == DEVICE_VOICING:
                self._data[DEVICE_VOICINGS][int(data)] = resp.get("extra")
            elif method == DEVICE_VOICING_COUNT:
                self._data[DEVICE_VOICINGS] = [None for i in range(int(data))]
            elif method == DEVICE_MUTE:
                self._data[method] = data
                self._init_event.set()
                _LOGGER.debug("init sequence complete")
        else:
            self._data[method] = data
        if self._callback is not None:
            self._callback(self._data)

    @property
    def is_on(self) -> bool:
        """Property power."""
        return self._data.get(DEVICE_POWER) == "1"

    @property
    def source_list(self) -> list[str]:
        """Return source list."""
        return self._data.get(DEVICE_SOURCES)

    @property
    def source(self) -> str:
        """Current source."""
        src = self._data.get(DEVICE_SOURCE)
        if src is None:
            return None
        return self._data[DEVICE_SOURCES][int(src)]

    async def async_select_source(self, source: str):
        """Change source."""
        await self.send_command(DEVICE_SOURCE, self._data[DEVICE_SOURCES].index(source))

    async def async_turn_on(self):
        """Device turn on."""
        await self.send_command("POWERONMAIN", None)

    async def async_turn_off(self):
        """Device turn off."""
        await self.send_command("POWEROFFMAIN", None)

    @property
    def volume_level(self) -> float | None:
        """Current volume."""
        devvol = self._data.get(DEVICE_VOL)
        if devvol is None:
            return None
        return (int(devvol) + DEVICE_VOL_RANGE) / DEVICE_VOL_RANGE

    @property
    def is_volume_muted(self) -> bool:
        """Current mute."""
        return self._data.get(DEVICE_MUTE) == DEVICE_MUTEON

    @property
    def lipsync(self) -> int:
        """Current lipsync."""
        return int(self._data.get(DEVICE_LIPSYNC))

    async def async_set_lipsync(self, lipsync: int):
        """Set lipsync."""
        await self.send_command(DEVICE_LIPSYNC, str(lipsync))

    async def async_mute_volume(self, mute: bool):
        """Set mute."""
        await self.send_command(DEVICE_MUTEON if mute else DEVICE_MUTEOFF)

    async def async_set_volume_level(self, volume: float):
        """Set vol."""
        await self.send_command(DEVICE_VOL, str(int((volume * DEVICE_VOL_RANGE) - DEVICE_VOL_RANGE)))

    async def async_volume_up(self):
        """Step up volume."""
        vol = self.volume_level
        if vol is not None:
            await self.async_set_volume_level(min(vol + 0.05, 1.0))

    async def async_volume_down(self):
        """Step down volume."""
        vol = self.volume_level
        if vol is not None:
            await self.async_set_volume_level(max(vol - 0.05, 0))

    @property
    def sound_mode_list(self) -> list[str]:
        """Return source list."""
        return self._data.get(DEVICE_VOICINGS)

    @property
    def sound_mode(self) -> str:
        """Current source."""
        mode = self._data.get(DEVICE_VOICING)
        if mode is None:
            return None
        return self._data[DEVICE_VOICINGS][int(mode)]

    async def async_select_sound_mode(self, mode: str):
        """Change source."""
        await self.send_command(DEVICE_VOICING, self._data[DEVICE_VOICINGS].index(mode))

    @property
    def audio_processing_mode_list(self) -> list[str]:
        """Return source list."""
        return self._data.get(DEVICE_AUDIO_MODES)

    @property
    def audio_processing_mode(self) -> str:
        """Current source."""
        mode = self._data.get(DEVICE_AUDIO_MODE)
        if mode is None:
            return None
        return self._data[DEVICE_AUDIO_MODES][int(mode)]

    async def async_select_audio_processing_mode(self, mode: str):
        """Change source."""
        await self.send_command(DEVICE_AUDIO_MODE, self._data[DEVICE_AUDIO_MODES].index(mode))


