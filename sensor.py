"""Platform for sensor integration."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import SLConfigEntry
from .device import DEVICE_AUDIO_TYPE, DEVICE_VIDEO_TYPE
from .entity import SLEntity

_LOGGER = logging.getLogger(__name__)

SENSOR_AUDIO_TYPE = "audio_signal_type"
SENSOR_VIDEO_TYPE = "video_signal_type"

SENSOR_MAP = {
    SENSOR_AUDIO_TYPE: DEVICE_AUDIO_TYPE,
    SENSOR_VIDEO_TYPE: DEVICE_VIDEO_TYPE
}

SENSOR_DESCRIPTIONS = (
    SensorEntityDescription(
        key=SENSOR_AUDIO_TYPE,
        translation_key=SENSOR_VIDEO_TYPE,
        device_class=SensorDeviceClass.ENUM,
    ),
    SensorEntityDescription(
        key=SENSOR_VIDEO_TYPE,
        translation_key=SENSOR_VIDEO_TYPE,
        device_class=SensorDeviceClass.ENUM,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: SLConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    coord = config_entry.runtime_data
    new_entities = [SLSensor(coord, desc) for desc in SENSOR_DESCRIPTIONS]
    if new_entities:
        async_add_entities(new_entities)


class SLSensor(SensorEntity, SLEntity):
    """Sensor class."""

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""

        dev_sensor = SENSOR_MAP[self.entity_description.key]
        self._attr_native_value = self.coordinator.device.get_data_value(dev_sensor)
        self.async_write_ha_state()
