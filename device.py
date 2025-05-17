"""Stewart SL Device."""

import asyncio
import logging
import re

from homeassistant.core import HomeAssistant, callback

from .const import SL_CONNECT_TIMEOUT, SL_LOGIN_TIMEOUT, SL_PORT, SL_ZEROCONF_TIMEOUT

_LOGGER = logging.getLogger(__name__)

DEVICE_AUDIO_MODE = "AUDMODE"
DEVICE_AUDIO_MODES = "AUDMODEL"
DEVICE_AUDIO_MODE_COUNT = "AUDMODECOUNT"
DEVICE_AUDIO_TYPE = "AUDTYPE"
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

DEVICE_SUBS = (
    DEVICE_AUDIO_MODE,
    DEVICE_AUDIO_TYPE,
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
        self._reader: asyncio.StreamReader
        self._writer: asyncio.StreamWriter
        self._init_event = asyncio.Event()
        self._online = False
        self._callback = None
        self._listener = None
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

    async def open_connection(self, test: bool = False) -> bool:
        """Establish a connection."""
        if self.online:
            return True

        try:
            _LOGGER.debug("Establish new connection")
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, SL_PORT),
                timeout=SL_CONNECT_TIMEOUT,
            )
            self._writer.write(b"!DEVICE?\r")
            devresp = await asyncio.wait_for(
                self._reader.readuntil(b'\r'), timeout=SL_LOGIN_TIMEOUT
            )
            resp = self.decode_response(devresp)
            if resp is None:
                return False
            model = self._data[DEVICE_MODEL] = resp["data"]
            self._device_id = f"{model}_{self._host}"
            if test:
                self._writer.close()
            else:
                self._online = True
                self._listener = asyncio.create_task(self.listener())

        except (TimeoutError, OSError, asyncio.IncompleteReadError) as err:
            self._online = False
            _LOGGER.error("Connect sequence error %s", err)
            raise ConnectionError("Connect sequence error") from err

        return True

    async def send_to_device(self, reqstr: str) -> None:
        """Make an API call."""
        if await self.open_connection():
             _LOGGER.debug("-> %s", reqstr)
             self._writer.write(reqstr.encode("ascii"))

    async def send_query(self, method: str) -> None:
        """Format and send command."""
        reqstr = f"!{method}?\r"
        await self.send_to_device(reqstr)

    async def send_command(self, method: str, data=None) -> None:
        """Format and send command."""
        reqstr = f"!{method}\r" if data is None else f"!{method}({data})\r"
        await self.send_to_device(reqstr)

    def decode_response(self, resp: str) -> dict:
        """Decode the response."""
        respstr = resp.decode("ascii")
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

    async def async_init(self, data_callback: callback) -> dict:
        """Query position and wait for response."""
        await self.send_query(DEVICE_SOURCES)
        await self.send_query(DEVICE_AUDIO_MODES)
        await self.send_query(DEVICE_VOICINGS)
        await self.send_query(DEVICE_MUTE)
        await asyncio.wait_for(self._init_event.wait(), timeout=SL_LOGIN_TIMEOUT)

        self._callback = data_callback
        for sub in DEVICE_SUBS:
            await self.send_query(sub)
        await self.send_command("VERB", "1")
        return self._data

    async def listener(self) -> None:
        """Listen for status updates from device."""

        while True:
            buf = await self._reader.readuntil(b'\r')
            if len(buf) == 0:
                _LOGGER.error("Connection closed")
                break
            resp = self.decode_response(buf)
            if resp is None:
                continue

            method = resp.get("method")
            data = resp.get("data")
            if method is not None:
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

        self._writer.close()
        self._online = False

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
        return (int(devvol) + 1000) / 1000.0

    @property
    def is_volume_muted(self) -> bool:
        """Current mute."""
        return self._data.get(DEVICE_MUTE) == DEVICE_MUTEON

    async def async_mute_volume(self, mute: bool):
        """Set mute."""
        await self.send_command(DEVICE_MUTEON if mute else DEVICE_MUTEOFF)

    async def async_set_volume_level(self, volume: float):
        """Set vol."""
        await self.send_command(DEVICE_VOL, str(int(volume * 1000) - 1000))

    async def async_volume_up(self):
        """Step up volume."""
        vol = self.volume_level
        if vol is not None:
            await self.async_set_volume_level(max(vol + 0.05, 1.0))

    async def async_volume_down(self):
        """Step down volume."""
        vol = self.volume_level
        if vol is not None:
            await self.async_set_volume_level(min(vol - 0.05, 0))

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


