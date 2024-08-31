"""Support for bemfa service."""
from __future__ import annotations
import asyncio
import contextlib
import logging
import json
import uuid
import time
from time import strftime, localtime
import ssl
import socket
import paho.mqtt.client as mqtt
from paho.mqtt.client import Client, Properties, MQTTMessage, MQTTv31, MQTTv311, MQTTv5
from .async_mqtt_client import AsyncMQTTClient
from asyncio import Task
from homeassistant.core import HomeAssistant, State, Event, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    TOPIC_COMMAND,
)
TOPIC_COMMAND = 'ha2xiaodu/command/'
TOPIC_COMMAND = 'ha2xiaodu/report/'
TOPIC_PING = 'topic_ping'
_LOGGER = logging.getLogger(__name__)


class DuerMqttService:
    """Set up mqtt connections to bemfa service, subscribe topcs and publish messages."""
    host = "127.0.0.1"
    port = 1883
    client_id = None
    username = None,
    password: str = None,
    reconnect_interval = 30,
    keep_alive = 60,
    tls = False,
    tls_insecure = False,
    ca_certs = None,
    certfile = None,
    keyfile = None,
    cert_reqs = ssl.CERT_NONE,
    tls_version = ssl.PROTOCOL_TLSv1_2,
    ciphers = None,
    state_key = "state",
    connected = False

    def __init__(
        self, hass: HomeAssistant
    ) -> None:
        """Initialize."""
        self._hass = hass
        self._loop = hass.loop
        self._client: AsyncMQTTClient = None
        self.stop_conn = False
        self.entity_list = []
        self.on_message_cb_list: list[callable] = []
        self.on_connect_cb_list: list[callable] = []
        self._connection_lock = asyncio.Lock()
        self._misc_loop_task: Task = None
        self._reconnect_loop_task: Task = None
        self._misc_timer: asyncio.TimerHandle = None

    def _reg_state_change_event(self):
        @callback
        async def _entity_state_change_processor(event) -> None:
            new_state: State = event.data.get("new_state")
            if new_state is None:
                return
            _LOGGER.debug(f"entity state change: {new_state.as_dict_json}")
            publish_data = {'type': 'state_changed',
                            'data': new_state.as_dict()}
            # if isinstance(self._client, Client):
            #     self.publish(
            #         f'{TOPIC_COMMAND}{self.username}',
            #         json.dumps(publish_data),
            #     )
        self._state_unsub = async_track_state_change_event(
            self._hass, self.entity_list, _entity_state_change_processor)

    @callback
    def _handle_on_connect(self,
                           client: Client,
                           userdata: None,
                           flags: dict[str, int],
                           rc: int,
                           properties: mqtt.Properties | None = None,) -> None:
        _LOGGER.debug('Connected to MQTT broker!')

        _LOGGER.debug(f"Connected to MQTT broker! {mqtt.connack_string(rc)}")
        self.update_connect_state(True)
        _LOGGER.debug(f'reg state change callback {self.entity_list}')
        # self._hass.add_job(self._reg_state_change_event)
        # self._reg_state_change_event()
        self._reconnect_loop_task = self._hass.async_create_background_task(
            self._reconnect_loop(), name=f"{self.host}_mqtt_reconnect_loop"
        )
        self._client.subscribe(
            f'{TOPIC_COMMAND}{self.username}', 0)

    @callback
    def _handle_on_disconnect(self, client, packet, exc=None) -> None:
        _LOGGER.warning("Disconnected from %s:%s", self.host, self.port)
        try:
            for cb in self.on_connect_cb_list:
                if callable(cb):
                    cb(False)
        except Exception as ex:
            _LOGGER.error(f'disconn cb error: {ex}')

    @callback
    def _handle_on_message(self, client: Client, userData: None, msg: MQTTMessage):
        try:
            msg_dic = json.loads(msg.payload.decode())
            _LOGGER.debug(f'receive msg: {msg_dic}')
            for cb in self.on_message_cb_list:
                if callable(cb):
                    cb(msg_dic)
        except Exception as ex:
            _LOGGER.error(f'process mqtt message call back failed: {ex}')

    def _on_socket_open(
        self, client: mqtt.Client, userdata, sock
    ) -> None:
        """Handle socket open."""
        self._loop.call_soon_threadsafe(
            self._async_on_socket_open, client, userdata, sock
        )

    @callback
    def _async_on_socket_open(self, client: Client, userdata, sock):
        fileno = sock.fileno()
        _LOGGER.debug(f"connection opened {fileno}")

        @callback
        def _async_misc() -> None:
            """Start the MQTT client misc loop."""
            if self._client.loop_misc() == mqtt.MQTT_ERR_SUCCESS:
                self._misc_timer = self._loop.call_at(
                    self._loop.time() + 1, _async_misc)

        def cb():
            res = client.loop_read()
            _LOGGER.debug(f'MQTT Socket is readable, calling loop read {res}')
        if not self._misc_timer:
            self._misc_timer = self._loop.call_at(
                self._loop.time() + 1, _async_misc)

        self._loop.add_reader(sock, cb)

    @callback
    def _on_socket_close(self, client: Client, userdata, sock):
        fileno = sock.fileno()
        _LOGGER.debug(f"connection closed {fileno}")
        self.update_connect_state(False)
        if self._misc_timer:
            self._misc_timer.cancel()
            self._misc_timer = None
        if fileno > -1:
            self._loop.remove_reader(sock)

    def _on_socket_register_write(
        self, client: mqtt.Client, userdata, sock
    ) -> None:
        """Register the socket for writing."""
        self._loop.call_soon_threadsafe(
            self._async_on_socket_register_write, client, None, sock
        )

    @callback
    def _async_on_socket_register_write(self, client: Client, userdata, sock):
        _LOGGER.debug("Watching MQTT socket for writability.")

        def cb():
            _LOGGER.debug('MQTT Socket is writeable, calling loop write')
            client.loop_write()
        fileno = sock.fileno()
        _LOGGER.debug(f"register write {fileno}")
        if fileno > -1:
            self._loop.add_writer(sock, cb)

    @callback
    def _on_socket_unregister_write(self, client: Client, userdata, sock):
        _LOGGER.debug("Stop watching MQTT socket for writability.")
        fileno = sock.fileno()
        _LOGGER.debug(f"unregister write {fileno}")
        if fileno > -1:
            self._loop.remove_writer(sock)

    @contextlib.asynccontextmanager
    async def _async_connect_in_executor(self):
        # While we are connecting in the executor we need to
        # handle on_socket_open and on_socket_register_write
        # in the executor as well.
        mqtt_cli = self._client
        try:
            mqtt_cli.on_socket_open = self._on_socket_open
            mqtt_cli.on_socket_register_write = self._on_socket_register_write
            yield
        finally:
            # Once the executor job is done, we can switch back to
            # handling these in the event loop.
            mqtt_cli.on_socket_open = self._async_on_socket_open
            mqtt_cli.on_socket_register_write = self._async_on_socket_register_write

    @callback
    def _async_cancel_reconnect(self) -> None:
        """Cancel the reconnect task."""
        if self._reconnect_loop_task:
            self._reconnect_loop_task.cancel()
            self._reconnect_loop_task = None

    # @callback
    # async def _misc_loop(self):
    #     """misc loop need maintain state"""
    #     _LOGGER.debug("Misc MQTT loop start")
    #     # while self._client.loop_misc() == paho.MQTT_ERR_SUCCESS:
    #     while True:
    #         try:
    #             # if self._stop_mqtt:
    #             #     break
    #             await asyncio.sleep(1)
    #         except Exception as ex:
    #             _LOGGER.error(f'misc loop error: {ex}')
    #         await asyncio.sleep(1)
    #     # _LOGGER.debug("Misc MQTT loop is finished")

    async def _reconnect_loop(self) -> None:
        """Reconnect to the MQTT server."""
        while True:
            if not self.connected:
                try:
                    async with self._connection_lock, self._async_connect_in_executor():
                        await self._hass.async_add_executor_job(self._client.reconnect)
                except OSError as err:
                    _LOGGER.debug(
                        f"Error re-connecting to MQTT server due to exception: {err}"
                    )
            _LOGGER.debug('check reconnect loop invoke')
            await asyncio.sleep(60)

    @callback
    async def connect(self, url, port, user, pwd,
                      reconnect_interval=30,
                      keep_alive=60,
                      tls=False,
                      tls_insecure=False,
                      ca_certs=None,
                      certfile=None,
                      keyfile=None,
                      cert_reqs=ssl.CERT_NONE,
                      tls_version=ssl.PROTOCOL_TLSv1_2,
                      ciphers=None,
                      state_key="state",
                      notify_birth=False) -> None:
        _LOGGER.debug('start set mqtt client')
        self.host = url
        self.port = int(port)
        self.username = user
        self.password = pwd
        self.tls = tls
        self.tls_insecure = tls_insecure
        self.ca_certs = ca_certs
        self.certfile = certfile
        self.keyfile = keyfile
        self.cert_reqs = cert_reqs
        self.tls_version = tls_version
        self.ciphers = ciphers
        self.reconnect_interval = reconnect_interval
        self.keep_alive = keep_alive
        self._stop_mqtt = False
        self.client_id = user or mqtt.base62(uuid.uuid4().int, padding=22)
        self._client = AsyncMQTTClient(
            self.client_id, protocol=MQTTv311, reconnect_on_failure=False)
        self._client.setup()
        self._client.enable_logger()
        if self.tls:
            self._client.tls_set(self.ca_certs, self.certfile, self.keyfile,
                                 self.cert_reqs, self.tls_version, self.ciphers)
            if self.tls_insecure:
                self._client.tls_insecure_set(True)

        if user is not None and pwd is not None:
            self._client.username_pw_set(user, pwd)
            _LOGGER.debug(f'set user pwd {user} {pwd}')
        if notify_birth:
            self.on_connect_cb_list.append(self.notify_birth)
        self.state_key = state_key
        # self._client.will_set(
        #     f"{self.client_id}/{state_key}",
        #     json.dumps({"connected": False}),
        #     retain=True,
        # )
        _LOGGER.debug('set call back')
        self._client.on_socket_open = self._async_on_socket_open
        self._client.on_socket_close = self._on_socket_close
        self._client.on_socket_register_write = self._async_on_socket_register_write
        self._client.on_socket_unregister_write = self._on_socket_unregister_write
        self._client.on_connect = self._handle_on_connect
        self._client.on_disconnect = self._handle_on_disconnect
        self._client.on_message = self._handle_on_message
        _LOGGER.debug(f'start conn {self.host} {self.port} {self.keep_alive}')
        _LOGGER.debug(
            f'start conn {type(self.host)} {type(self.port)} {type(self.keep_alive)}')
        # self._client.connect(self.host, self.port, self.keep_alive)
        try:
            async with self._connection_lock, self._async_connect_in_executor():
                res = await self._hass.async_add_executor_job(self._client.connect, self.host, self.port, self.keep_alive)
        except Exception as ex:
            _LOGGER.error(f'mqtt create connect error: {ex}')
        finally:
            if res is not None:
                if res != 0:
                    _LOGGER.error(
                        f'mqtt create connect error: {mqtt.error_string(res)}')
        self._client.socket().setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 2048)
        _LOGGER.debug('mqtt client init finish')

    def stop(self):
        _LOGGER.info("mqtt stopping")
        # mqtt broker will send last will since brake of unexpectedly
        self._stop_mqtt = False
        sock = self._client.socket()
        if sock is not None:
            sock.close()
        if isinstance(self._reconnect_loop_task, Task):
            if not self._reconnect_loop_task.done():
                self._reconnect_loop_task.cancel()
        _LOGGER.info("mqtt stopped")

    def publish(self, topic, payload, **kwargs):
        _LOGGER.debug(f'pub topic {topic}')
        if self.connected:
            self._client.publish(topic, payload, **kwargs)

    def subscribe(self, *args, **kwargs):
        if self.connected:
            self._client.subscribe(*args, **kwargs)

    def update_connect_state(self, state: bool):
        self.connected = state
        for cb in self.on_connect_cb_list:
            if callable(cb):
                try:
                    cb(state)
                except Exception as ex:
                    _LOGGER.error(f'online cb error:{ex}')

    def notify_birth(self, state: bool):
        self.publish(
            self.state_key,
            json.dumps({"connected": True, "at": self.timestamp()}),
            retain=True,
        )

    @staticmethod
    def timestamp():
        time_format = strftime("%Y-%m-%d %H:%M:%S", localtime(time.time()))
        return time_format
