import logging
from homeassistant.core import HomeAssistant
from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from . import DOMAIN, ConfigEntry
from .service import DuerService

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    domain = hass.data.get(DOMAIN)
    if domain:
        service: DuerService = domain.get(
            config_entry.entry_id)["service"]
        if isinstance(service, DuerService):

            async_add_entities([MqttOnlineSensor(service),])


class MqttOnlineSensor(BinarySensorEntity):
    def __init__(self, service: DuerService):
        self._gateway = service
        self._attr_name = f'duer_mqtt_online'
        self._attr_unique_id = f"b_sensor_{self._attr_name}"
        self._attr_is_on = False
        self._device_class = BinarySensorDeviceClass.CONNECTIVITY
        self._gateway.mqtt_online_cb = self.process_callback

    # async def async_added_to_hass(self):
    #     self._attr_is_on = self._gateway.online_state
    #     self.schedule_update_ha_state()

    def process_callback(self, state: bool):
        self._attr_is_on = state
        self.schedule_update_ha_state()
