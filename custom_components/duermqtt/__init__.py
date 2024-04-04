from __future__ import annotations
import logging
from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import CONF_TOKEN
from .const import DOMAIN, CONF_FILTER, CONF_INCLUDE_ENTITIES
from .service import DuerMQTTService
_LOGGER = logging.getLogger(__name__)


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug(f'update entry data')
    if entry.source == SOURCE_IMPORT:
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up bemfa from a config entry."""
    if not hass.data.get(DOMAIN):
        hass.data.setdefault(DOMAIN, {})
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    entity_filter = None
    data_conf = entry.data
    options_conf = entry.options

    # _LOGGER.debug(f'entry conf:{entry.as_dict()}')
    # _LOGGER.debug(f'entry data:{entry.data}')
    # _LOGGER.debug(f'entry options:{entry.options}')
    if not options_conf:
        entity_filter = data_conf.get(CONF_FILTER, {})
    else:
        entity_filter = options_conf.get(CONF_FILTER, {})
    if entity_filter:
        if len(entity_filter[CONF_INCLUDE_ENTITIES]) > 0:
            enttities = entity_filter[CONF_INCLUDE_ENTITIES]
            _LOGGER.debug(f'include entities:{enttities}')
            service = DuerMQTTService(hass, entry.data[CONF_TOKEN])
            hass.data[DOMAIN][entry.entry_id] = {
                "service": service,
            }
            await service.async_start(
                enttities
            )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    data = hass.data[DOMAIN].get(entry.entry_id)
    if data is not None:
        data["service"].stop()
        hass.data[DOMAIN].pop(entry.entry_id)

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove a config entry."""
    # await hass.async_add_executor_job(
    #     remove_state_files_for_entry_id, hass, entry.entry_id
    # )
    _LOGGER.debug('remove entry invoke')
