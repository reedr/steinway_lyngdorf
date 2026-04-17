"""Steinway Lyngdorf number platform."""

import logging

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SLConfigEntry
from .entity import SLEntity

_LOGGER = logging.getLogger(__name__)

NUMBER_LIPSYNC = "lipsync_delay"

NUMBER_DESCRIPTIONS = [
    NumberEntityDescription(
        key=NUMBER_LIPSYNC,
        translation_key=NUMBER_LIPSYNC,
        device_class=NumberDeviceClass.DURATION,
        native_min_value=0,
        native_max_value=10000,
        native_step=10,
        native_unit_of_measurement="ms",
        icon="mdi:microphone-plus",
    )
]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SLConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    coord = config_entry.runtime_data
    new_entities = [SLNumber(coord, desc) for desc in NUMBER_DESCRIPTIONS]
    if new_entities:
        async_add_entities(new_entities)


class SLNumber(NumberEntity, SLEntity):
    """Number class."""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""

        self._attr_native_value = self.coordinator.device.lipsync
        self.async_write_ha_state()

    async def async_set_native_value(self, value: float) -> None:
        """Set the value of the number."""
        await self.coordinator.device.async_set_lipsync(int(value))
