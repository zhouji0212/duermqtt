"""Support for bemfa service."""
from __future__ import annotations
import asyncio
import base64
import logging
import json

from typing import Any

from .async_paho_mqtt import AsyncClient as amqtt
from .async_paho_mqtt import Client, MQTTMessage
from homeassistant.core import HomeAssistant, State, Event, callback
from homeassistant.helpers.event import async_track_state_change_event, EventStateChangedData

from .const import (
    TOPIC_REPORT,
)
TOPIC_COMMAND = 'ha2xiaodu/command/'
TOPIC_REPORT = 'ha2xiaodu/report/'
TOPIC_PING = 'topic_ping'
_LOGGER = logging.getLogger(__name__)


class DuerMqttService:
    """Set up mqtt connections to bemfa service, subscribe topcs and publish messages."""

    def __init__(
        self, hass: HomeAssistant
    ) -> None:
        """Initialize."""
        self.hass = hass
        self._user = None
        # Init MQTT connection
        self._amqtt = None
        self._conn_dic = None
        self.entity_list = []
        self.on_mqtt_message_cb = []
        self.on_connect_cb: callable[None, bool] = None

    async def connect(self, url, port, user, pwd) -> None:
        try:
            _LOGGER.debug('create ha mqtt conn')
            self._user = user
            self._amqtt = amqtt(
                hass=self.hass,
                host=url,
                port=int(port),
                username=user,
                password=pwd,
                client_id=user)
            self._amqtt.on_connect.append(self._mqtt_on_connect)
            self._amqtt.on_disconnect.append(self._mqtt_on_disconnect)
            self._amqtt.on_message.append(self._mqtt_on_message)
            self._amqtt.start()
            _LOGGER.debug('ha create mqtt conn finish')
        except Exception as ex:
            print(f'create mqtt connection failed:{ex}')

    def disconnect(self) -> None:
        self._amqtt.stop()

    def _mqtt_on_connect(self, client: Client, flags, rc, properties) -> None:
        async def _entity_state_change_processor(event: Event[EventStateChangedData]) -> None:
            new_state: State = event.data.get("new_state")
            if new_state is None:
                return
            _LOGGER.debug(f"entity state change: {new_state.as_dict_json}")
            publish_data = {'type': 'state_changed',
                            'data': new_state.as_dict()}
            if isinstance(self, DuerMqttService):
                if isinstance(self._amqtt, amqtt):
                    self.hass.add_job(
                        self._amqtt.publish(
                            f'{TOPIC_REPORT}{self._user}',
                            json.dumps(publish_data),
                        ))
        _LOGGER.debug(f"Connected to MQTT broker! {rc}")
        if callable(self.on_connect_cb):
            self.on_connect_cb(True)
        # self._state_unsub = async_track_state_change_event(
        #     self.hass, self.entity_list, _entity_state_change_processor)
        self.hass.add_job(self._amqtt.subscribe(
            f'{TOPIC_COMMAND}{self._user}', 2))

    def _mqtt_on_disconnect(self, client, packet, exc=None) -> None:
        _LOGGER.error(f'mqtt client Disconnected')
        if callable(self.on_connect_cb):
            self.on_connect_cb(False)
        # self._online_state = False

    def _mqtt_on_message(self, client: Client, message: MQTTMessage) -> None:
        try:
            msg_dic = json.loads(message.payload.decode())
            _LOGGER.debug(f'receive msg: {msg_dic}')
            for cb in self.on_mqtt_message_cb:
                if callable(cb):
                    cb(msg_dic)
        except Exception as ex:
            _LOGGER.error(f'process mqtt message call back failed: {ex}')
