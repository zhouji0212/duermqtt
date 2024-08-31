"""Config flow for HomeKit integration."""
from __future__ import annotations
import logging
from collections.abc import Iterable
from copy import deepcopy
from typing import Any, TypedDict

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.const import (
    ATTR_FRIENDLY_NAME,
    CONF_DOMAINS,
    CONF_ENTITIES,
    CONF_NAME,
    CONF_TOKEN
)
from homeassistant.core import HomeAssistant, callback, split_entity_id
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.loader import async_get_integrations

from .const import (
    DOMAIN,
    CONF_FILTER,
    CONF_INCLUDE_DOMAINS,
    CONF_INCLUDE_ENTITIES,
)
_LOGGER = logging.getLogger(__name__)
CONF_ACTION = "action"
CONF_EDIT_DEVICE = "edit_device"
CONF_CHANGE_TOKEN = "change_token"
CONF_ACTIONS = {
    CONF_EDIT_DEVICE: "Edit a HA device",
    CONF_CHANGE_TOKEN: "Change Duer Platform Token",
}

CONFIGURE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACTION, default=CONF_EDIT_DEVICE): vol.In(CONF_ACTIONS),
    }
)
CONF_INCLUDE_EXCLUDE_MODE = "include_exclude_mode"
CONF_EXCLUDE_ACCESSORY_MODE = "exclude_accessory_mode"


MODE_INCLUDE = "include"
MODE_EXCLUDE = "exclude"

INCLUDE_EXCLUDE_MODES = [MODE_INCLUDE,]

SUPPORTED_DOMAINS = [
    "button",
    "climate",
    "fan",
    "cover",
    "input_button",
    "light",
    "scene",
    "switch",
    "water_heater",
]

DEFAULT_DOMAINS = ['light', 'switch', 'cover', 'scene', 'climate']


class EntityFilterDict(TypedDict, total=False):
    """Entity filter dict."""

    include_domains: list[str]
    include_entities: list[str]
    exclude_domains: list[str]
    exclude_entities: list[str]


def _make_entity_filter(
    include_domains: list[str] | None = None,
    include_entities: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    exclude_entities: list[str] | None = None,
) -> EntityFilterDict:
    """Create a filter dict."""
    return EntityFilterDict(
        include_domains=include_domains or [],
        include_entities=include_entities or [],
        exclude_domains=exclude_domains or [],
        exclude_entities=exclude_entities or [],
    )


async def _async_domain_names(hass: HomeAssistant, domains: list[str]) -> str:
    """Build a list of integration names from domains."""
    name_to_type_map = await _async_name_to_type_map(hass)
    return ", ".join(
        [name for domain, name in name_to_type_map.items() if domain in domains]
    )


@callback
def _async_build_entities_filter(
    domains: list[str], entities: list[str]
) -> EntityFilterDict:
    """Build an entities filter from domains and entities."""
    return _make_entity_filter(
        include_domains=sorted(
            set(domains).difference(_domains_set_from_entities(entities))
        ),
        include_entities=entities,
    )


async def _async_name_to_type_map(hass: HomeAssistant) -> dict[str, str]:
    integrations = await async_get_integrations(hass, SUPPORTED_DOMAINS)
    # _LOGGER_.debug(f'get intergations: {integrations}')
    return {
        domain: integration_or_exception.name
        if (integration_or_exception := integrations[domain])
        and not isinstance(integration_or_exception, Exception)
        else domain
        for domain in SUPPORTED_DOMAINS
    }


class DuerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HomeKit."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self.duer_data: dict[str, Any] = {}

    async def async_step_include_device(
        self, user_input: dict[str, Any] | None = None
    ):
        """Choose entities to include from the domain on the bridge."""
        duer_data = self.duer_data
        # _LOGGER_.debug(f'opt:{duer_options}')
        domains = duer_data[CONF_DOMAINS]
        if user_input is not None:
            # VERSION = self.config_entry.version+1
            entities = cv.ensure_list(user_input[CONF_ENTITIES])
            duer_data[CONF_FILTER] = _async_build_entities_filter(
                domains, entities)
            duer_data.update(user_input)
            # _LOGGER.debug(f'options entry: {self.duer_options}')

            return self.async_create_entry(title="", data=self.duer_data)

        entity_filter: EntityFilterDict = duer_data.get(CONF_FILTER, {})
        entities = entity_filter.get(CONF_INCLUDE_ENTITIES, [])
        all_supported_entities = _async_get_matching_entities(
            self.hass, domains, include_entity_category=True, include_hidden=True
        )
        # Strip out entities that no longer exist to prevent error in the UI
        default_value = [
            entity_id for entity_id in entities if entity_id in all_supported_entities
        ]
        # _LOGGER.debug(f'include_list: {default_value}')
        return self.async_show_form(
            step_id="include_device",
            description_placeholders={
                "domains": await _async_domain_names(self.hass, domains)
            },
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ENTITIES, default=default_value): cv.multi_select(
                        all_supported_entities
                    )
                }
            ),
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        """Choose specific domains in bridge mode."""
        if user_input is not None:
            self.duer_data[CONF_TOKEN] = user_input[CONF_TOKEN]
            self.duer_data[CONF_FILTER] = _make_entity_filter(
                include_domains=[]
            )
            self.duer_data[CONF_FILTER][CONF_INCLUDE_ENTITIES] = [state.entity_id
                                                                  for state in self.hass.states.async_all(self.duer_data[CONF_FILTER][CONF_INCLUDE_DOMAINS])
                                                                  ]
            return await self.async_step_select_domain()

        self.duer_data[CONF_NAME] = 'Duer_MQTT'
        # name_to_type_map = await _async_name_to_type_map(self.hass)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): str,
                }
            ),
        )

    async def async_step_select_domain(
        self, user_input: dict[str, Any] | None = None
    ):
        if user_input is not None:
            self.duer_data.update(user_input)
            return await self.async_step_include_device()
        include_exclude_mode = MODE_INCLUDE
        domains = DEFAULT_DOMAINS
        name_to_type_map = await _async_name_to_type_map(self.hass)
        return self.async_show_form(
            step_id="select_domain",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INCLUDE_EXCLUDE_MODE, default=include_exclude_mode
                    ): vol.In(INCLUDE_EXCLUDE_MODES),
                    vol.Required(
                        CONF_DOMAINS,
                        default=domains,
                    ): cv.multi_select(name_to_type_map),
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlowHandler:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(OptionsFlow):
    """Handle a option flow for homekit."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry
        _LOGGER.debug(f'config_entry data:{config_entry.data}')
        # self.duer_options: dict[str, Any] = {}
        if not self.config_entry.options:
            self.duer_options = deepcopy(dict(self.config_entry.data))
        else:
            self.duer_options = deepcopy(dict(self.config_entry.options))

    async def async_step_include_device(
        self, user_input: dict[str, Any] | None = None
    ):
        """Choose entities to include from the domain on the bridge."""
        duer_options = self.duer_options
        # _LOGGER_.debug(f'opt:{duer_options}')
        domains = duer_options[CONF_DOMAINS]
        if user_input is not None:
            # VERSION = self.config_entry.version+1
            entities = cv.ensure_list(user_input[CONF_ENTITIES])
            duer_options[CONF_FILTER] = _async_build_entities_filter(
                domains, entities)
            duer_options.update(user_input)
            # _LOGGER.debug(f'options entry: {self.duer_options}')

            return self.async_create_entry(title="", data=self.duer_options)

        entity_filter: EntityFilterDict = duer_options.get(CONF_FILTER, {})
        entities = entity_filter.get(CONF_INCLUDE_ENTITIES, [])
        all_supported_entities = _async_get_matching_entities(
            self.hass, domains, include_entity_category=True, include_hidden=True
        )
        # Strip out entities that no longer exist to prevent error in the UI
        default_value = [
            entity_id for entity_id in entities if entity_id in all_supported_entities
        ]
        # _LOGGER.debug(f'include_list: {default_value}')
        return self.async_show_form(
            step_id="include_device",
            description_placeholders={
                "domains": await _async_domain_names(self.hass, domains)
            },
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_ENTITIES, default=default_value): cv.multi_select(
                        all_supported_entities
                    )
                }
            ),
        )

    async def async_step_change_token(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            self.duer_options.update(user_input)
            # _LOGGER.debug(f'options entry: {self.duer_options}')

            return self.async_create_entry(title="", data=self.duer_options)
        return self.async_show_form(
            step_id="change_token",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TOKEN): str,
                }
            ),
        )

    async def async_step_edit_domain(
        self, user_input: dict[str, Any] | None = None
    ):
        """Handle options flow."""
        if user_input is not None:
            self.duer_options.update(user_input)
            return await self.async_step_include_device()
        entity_filter: EntityFilterDict = self.duer_options.get(
            CONF_FILTER, {})
        include_exclude_mode = MODE_INCLUDE
        if include_entities := entity_filter.get(CONF_INCLUDE_ENTITIES):
            domains = _domains_set_from_entities(include_entities)
        else:
            domains = entity_filter.get(CONF_INCLUDE_DOMAINS, DEFAULT_DOMAINS)
        name_to_type_map = await _async_name_to_type_map(self.hass)
        return self.async_show_form(
            step_id="edit_domain",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_INCLUDE_EXCLUDE_MODE, default=include_exclude_mode
                    ): vol.In(INCLUDE_EXCLUDE_MODES),
                    vol.Required(
                        CONF_DOMAINS,
                        default=domains,
                    ): cv.multi_select(name_to_type_map),
                }
            ),
        )

    async def async_step_init(self, user_input=None):
        """Manage basic options."""
        if user_input is not None:
            if user_input.get(CONF_ACTION) == CONF_CHANGE_TOKEN:
                return await self.async_step_change_token()
            if user_input.get(CONF_ACTION) == CONF_EDIT_DEVICE:
                return await self.async_step_edit_domain()

        return self.async_show_form(
            step_id="init",
            data_schema=CONFIGURE_SCHEMA,
        )


def _exclude_by_entity_registry(
    ent_reg: er.EntityRegistry,
    entity_id: str,
    include_entity_category: bool,
    include_hidden: bool,
) -> bool:
    """Filter out hidden entities and ones with entity category (unless specified)."""
    return bool(
        (entry := ent_reg.async_get(entity_id))
        and (
            (not include_hidden and entry.hidden_by is not None)
            or (not include_entity_category and entry.entity_category is not None)
        )
    )


def _async_get_matching_entities(
    hass: HomeAssistant,
    domains: list[str] | None = None,
    include_entity_category: bool = False,
    include_hidden: bool = False,
) -> dict[str, str]:
    """Fetch all entities or entities in the given domains."""
    ent_reg = er.async_get(hass)
    return {
        state.entity_id: (
            f"{state.attributes.get(ATTR_FRIENDLY_NAME, state.entity_id)} ({state.entity_id})"
        )
        for state in sorted(
            hass.states.async_all(domains and set(domains)),
            key=lambda item: item.entity_id,
        )
        if not _exclude_by_entity_registry(
            ent_reg, state.entity_id, include_entity_category, include_hidden
        )
    }


def _domains_set_from_entities(entity_ids: Iterable[str]) -> set[str]:
    """Build a set of domains for the given entity ids."""
    return {split_entity_id(entity_id)[0] for entity_id in entity_ids}
