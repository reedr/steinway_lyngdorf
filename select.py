"""Platform for sensor integration."""

import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SLConfigEntry, SLCoordinator
from .entity import SLEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SLConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add cover entity."""
    coord = config_entry.runtime_data

    async_add_entities([SLSelect(coord)])

SELECT_KEY = "audio_processing_mode"

DESC = SelectEntityDescription(
        key=SELECT_KEY,
        translation_key=SELECT_KEY
    )

class SLSelect(SelectEntity, SLEntity):
    """Screen aspect selector."""

    def __init__(self, coord: SLCoordinator) -> None:
        """Get going."""
        super().__init__(coord, DESC)
        self._attr_options = self.coordinator.device.audio_processing_mode_list
        self._local_current_option = self.coordinator.device.audio_processing_mode

    def set_state(self) -> None:
        """Set how things are."""
        self._local_current_option = self.coordinator.device.audio_processing_mode

    @property
    def current_option(self) -> str:
        """Override the base class which doesn't work."""
        return self._local_current_option

    async def async_select_option(self, option: str) -> None:
       """Select the ar."""
       self._local_current_option = option
       await self.coordinator.device.async_select_audio_processing_mode(option)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.set_state()
        self.schedule_update_ha_state()
