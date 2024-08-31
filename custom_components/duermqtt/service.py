"""Support for bemfa service."""
from __future__ import annotations

import logging
import asyncio
from datetime import datetime
from asyncio import Task, Lock, Queue
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.aiohttp_client import async_create_clientsession
import base64
import json
from aiohttp import ClientSession, ClientResponse
from .mqtt_service import DuerMqttService
from . import DOMAIN
from . const import CONST_POST_SYNC_DEVICE_URL, CONST_POST_SYNC_STATE_URL, CONST_GET_VERSION_CHECK_URL, CONST_VERSION
_LOGGER = logging.getLogger(__name__)
TOPIC_COMMAND = 'ha2xiaodu/command/'
TOPIC_REPORT = 'ha2xiaodu/report/'
TOPIC_PING = 'topic_ping'


class DuerService:
    """Service handles mqtt topocs and connection."""

    def __init__(self, hass: HomeAssistant, token: str) -> None:
        """Initialize."""
        self.hass = hass
        self._token = token
        self._duer_mqtt_service = DuerMqttService(hass)
        self.mqtt_online_cb: callable[None,
                                      bool] = None
        self.mqtt_online = False
        self._start = False
        self._duer_mqtt_service.on_message_cb_list.append(
            self._on_mqtt_message)
        self._duer_mqtt_service.on_connect_cb_list.append(
            self._on_mqtt_connect)
        self._mqtt_url: str = None
        self._web_url: str = None
        self._port: str = None
        self._user: str = None
        self._pwd: str = None
        self._version_check = False
        self._entity_list = []
        self._session = async_create_clientsession(self.hass, False, True)
        self._state_change_unsub = None
        self._sync_state_queue: Queue = Queue(3000)
        self._sync_state_task: Task = None
        self._sync_state_lock = Lock()

    def _sub_state_change(self):
        @callback
        async def _entity_state_change_processor(event) -> None:
            new_state: State = event.data.get("new_state")
            if new_state is None:
                return
            try:
                _LOGGER.debug(f"entity state change: {new_state}")
                self._sync_state_queue.put_nowait(new_state)
            except Exception as ex:
                _LOGGER.error(f'sync state queue full: {ex}')
        self._state_change_unsub = async_track_state_change_event(
            self.hass, self._entity_list, _entity_state_change_processor)
        _LOGGER.debug('state change sub success')

    async def async_start(self, entity_list: list) -> None:
        self._entity_list = entity_list
        _LOGGER.debug('duer mqtt service start')
        _LOGGER.debug(f'token:{self._token}')
        self._duer_mqtt_service.entity_list = entity_list
        try:
            conn_dic = json.loads(
                base64.b64decode(self._token).decode())
            self._mqtt_url = conn_dic.get('mqtt_url')
            self._web_url = conn_dic.get('web_url')
            self._port = conn_dic.get('port')
            self._user = conn_dic.get('username')
            self._pwd = conn_dic.get('password')
        except Exception as ex:
            _LOGGER.error(f'token decode error: {ex}')
        self._version_check = await self._check_plugin_version()

        def _start(event: Event | None = None):
            try:
                if self._version_check:
                    _LOGGER.debug('check version ok start post data')
                    self.hass.create_task(self._duer_mqtt_service.connect(
                        self._mqtt_url, self._port, self._user, self._pwd))
                    self._sync_device_entities(self._entity_list)
                    self._sub_state_change()
                    self._start = True
            except Exception as ex:
                _LOGGER.error(f'start mqtt service err:{ex}')
        if self.hass.state == CoreState.running:
            _start()
        else:
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, _start)
        await asyncio.sleep(3)
        self._sync_state_task = self.hass.async_create_background_task(
            self._sync_entities_state_loop(), f'{self._user}_sync_state_entities')

    def stop(self) -> None:
        self._duer_mqtt_service.stop()

    async def _get_data(self, session: ClientSession, url: str):
        try:
            res: ClientResponse = await session.get(url)
            res.raise_for_status()
            dic_res: dict = await res.json()
            if 'code' in dic_res and dic_res['code'] == 0:
                _LOGGER.debug(f"res raw_data:{dic_res}")
                return dic_res
        except Exception as ex:
            _LOGGER.error(f'get data err:{ex}')

    async def _post_data(self, url: str, data: dict):
        try:
            if isinstance(self._session, ClientSession):
                if self._session.closed:
                    self._session = async_create_clientsession(
                        self.hass, False, True)
            post_headers = {'Content-Type': 'application/json'}
            j_data = json.dumps(data)
            _LOGGER.debug(f"post json:{j_data}")
            res: ClientResponse = await self._session.post(
                url, data=j_data, headers=post_headers)
            res.raise_for_status()
            dic_res: dict = await res.json()
            if 'code' in dic_res and dic_res['code'] == 0:
                _LOGGER.debug(f"res raw_data:{dic_res}")
            else:
                _LOGGER.error(f"post data:{data}, res raw_data:{dic_res}")
        except Exception as ex:
            _LOGGER.error(f'post data err:{ex}')

    async def _check_plugin_version(self):
        check_state = False
        res_dic = await self._get_data(self._session, f'{self._web_url}{CONST_GET_VERSION_CHECK_URL}')
        if res_dic is None:
            _LOGGER.error('check plugin version err')
            return
        if 'data' in res_dic.keys():
            if 'plugin_version' in res_dic['data'].keys():
                str_version = res_dic['data']['plugin_version']
                current_version = datetime.strptime(CONST_VERSION, "%Y.%m.%d")
                get_version = datetime.strptime(str_version, "%Y.%m.%d")
                if current_version >= get_version:
                    check_state = True
                else:
                    _LOGGER.error(
                        'duermqtt plugin version is too old,please update plugin')
        return check_state

    def _sync_device_entities(self, entities: list[str]):
        if isinstance(entities, list):
            _LOGGER.debug('start sync entities')
            entity_list = []
            for entity in entities:
                state: State = self.hass.states.get(entity)
                if isinstance(state, State):
                    entity_list.append(state.as_dict())
            post_device_data = {
                'type': 'syncentity',
                'data': entity_list,
                'openid': self._user,
                'secret': self._pwd
            }
            self.hass.add_job(
                self._post_data(f'{self._web_url}{CONST_POST_SYNC_DEVICE_URL}', post_device_data))
            _LOGGER.debug('sync entities finish')

    @callback
    async def _sync_entities_state_loop(self):
        # await asyncio.sleep(10)
        # _LOGGER.debug('start sync entities')
        # for entity in self._entity_list:
        #     e_state: State = self.hass.states.get(entity)
        #     if isinstance(e_state, State):
        #         post_device_data = {
        #             'type': 'state_changed',
        #             'data': e_state.as_dict(),
        #             'openid': self._user,
        #             'secret': self._pwd
        #         }
        #         await self._post_data(self._session, f'{self._web_url}{CONST_POST_SYNC_STATE_URL}', post_device_data)
        #         await asyncio.sleep(0.01)
        _LOGGER.debug('start sync state queue loop')
        # self._sync_state_queue = asyncio.Queue(3000)
        while True:
            try:
                if isinstance(self._sync_state_queue, asyncio.Queue):
                    state: State = await self._sync_state_queue.get()
                    self._sync_state_queue.task_done()
                    _LOGGER.debug('post_change data')
                    if isinstance(state, State):
                        post_device_data = {
                            'type': 'state_changed',
                            'data': state.as_dict(),
                            'openid': self._user,
                            'secret': self._pwd
                        }
                        await self._post_data(f'{self._web_url}{CONST_POST_SYNC_STATE_URL}', post_device_data)
            except Exception as ex:
                _LOGGER.error(f'get queue error {ex}')
            await asyncio.sleep(0.01)

    def _on_mqtt_connect(self, state):
        self.mqtt_online = state
        self._duer_mqtt_service.subscribe(
            f'{TOPIC_COMMAND}{self._user}', 0)
        if callable(self.mqtt_online_cb):
            self.mqtt_online_cb(state)

    def _on_mqtt_message(self, data: dict):
        _LOGGER.debug(f'get mqtt message:{data}')
        cmd_type = data.get('type')
        if cmd_type:
            match cmd_type:
                case 'syncentity':
                    _LOGGER.debug(f'sync device entitys:{self._entity_list}')
                    self._sync_device_entities(self._entity_list)
                case 'callservice':
                    self._call_service(data)

    def _call_service(self, data: dict) -> None:
        _LOGGER.debug(f'call hass service: {data}')
        service = data.get('service')
        s_data = data.get('service_data')
        entity_id = data.get('entity_id')
        domain = entity_id.split('.')[0]
        if not s_data:
            s_data = {
                'entity_id': entity_id
            }
        if isinstance(s_data, dict):
            s_data['entity_id'] = entity_id

        _LOGGER.debug(f'call data:{s_data}')
        self.hass.add_job(self.hass.services.async_call(
            domain=domain, service=service, service_data=s_data, blocking=False
        ))
