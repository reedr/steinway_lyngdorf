"""Remote platform."""

import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityDescription,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SLConfigEntry, SLCoordinator
from .entity import SLEntity

_LOGGER = logging.getLogger(__name__)

DESC = MediaPlayerEntityDescription(key="receiver", translation_key="receiver")

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SLConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add Remote entity."""
    coord = config_entry.runtime_data

    async_add_entities([SLMediaPlayer(coord)])


class SLMediaPlayer(MediaPlayerEntity, SLEntity):
    """Receiver as media_player."""

    _attr_device_class = MediaPlayerDeviceClass.RECEIVER
    _attr_supported_features = (
        MediaPlayerEntityFeature.SELECT_SOUND_MODE
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
    )
    _attr_media_content_type = MediaType.MOVIE
    _supports_volume = True
    _supports_sound_mode = True
    _supports_source = True

    def __init__(self, coord: SLCoordinator) -> None:
        """Get going."""
        super().__init__(coord, DESC)

    @property
    def available(self) -> bool:
        """Is device online."""
        return self.coordinator.device.online

    @property
    def is_on(self) -> bool:
        """Return True if entity is on."""
        return self.coordinator.device.is_on

    @property
    def source_list(self) -> list[str]:
        """Source list."""
        return self.coordinator.device.source_list

    @property
    def source(self) -> str:
        """Current source."""
        return self.coordinator.device.source

    async def async_select_source(self, source: str):
        """Change source."""
        await self.coordinator.device.async_select_source(source)

    async def async_turn_on(self) -> None:
        """Turn the device on."""
        await self.coordinator.device.async_turn_on()

    async def async_turn_off(self) -> None:
        """Turn the device off."""
        await self.coordinator.device.async_turn_off()

    @property
    def sound_mode_list(self) -> list[str]:
        """Mode."""
        return self.coordinator.device.sound_mode_list

    @property
    def sound_mode(self) -> str:
        """Mode."""
        return self.coordinator.device.sound_mode

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Select sound mode."""
        await self.coordinator.device.async_select_sound_mode(sound_mode)

    @property
    def volume_level(self) -> float | None:
        """Volume level."""
        return self.coordinator.device.volume_level

    @property
    def is_volume_muted(self) -> bool:
        """Mute state."""
        return self.coordinator.device.is_volume_muted

    async def async_mute_volume(self, mute: bool):
        """Mute it."""
        await self.coordinator.device.async_mute_volume(mute)

    async def async_volume_up(self) -> None:
        """Volume up media player."""
        await self.coordinator.device.async_volume_up()

    async def async_volume_down(self) -> None:
        """Volume down media player."""
        await self.coordinator.device.async_volume_down()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set volume level, range 0..1."""
        await self.coordinator.device.async_set_volume_level(volume)

    @property
    def state(self) -> MediaPlayerState:
        """Current state."""
        return MediaPlayerState.ON if self.is_on else MediaPlayerState.STANDBY


    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.schedule_update_ha_state()
