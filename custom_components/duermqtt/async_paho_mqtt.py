import json
import uuid
import time
from time import strftime, localtime
import asyncio
from asyncio import Task
import logging
import ssl
from homeassistant.core import HomeAssistant
import paho.mqtt.client as paho
from paho.mqtt.client import Client, Properties, MQTTMessage

_LOGGER = logging.getLogger(__name__)


class AsyncClient:
    def __init__(
        self,
        hass: HomeAssistant,
        client=None,
        host="127.0.0.1",
        port=1883,
        client_id=None,
        protocol=paho.MQTTv311,
        username=None,
        password: str = None,
        reconnect_interval=15,
        keepalive=60,
        tls=False,
        tls_insecure=False,
        ca_certs=None,
        certfile=None,
        keyfile=None,
        cert_reqs=ssl.CERT_NONE,
        tls_version=ssl.PROTOCOL_TLSv1_2,
        ciphers=None,
        state_key="state",
        notify_birth=False
    ):
        self.host = host
        self.port = port
        self._connted = False
        self._hass = hass
        self.keepalive = keepalive
        self._stop = False
        self._loop = hass.loop
        self.reconnect_interval = reconnect_interval
        self._reconnector_loop_task: Task = None
        self.client_id = client_id or paho.base62(uuid.uuid4().int, padding=22)
        self._client = client or paho.Client(self.client_id, protocol=protocol)
        if tls:
            self._client.tls_set(ca_certs, certfile, keyfile,
                                 cert_reqs, tls_version, ciphers)
            if tls_insecure:
                self._client.tls_insecure_set(True)

        if username is not None and password is not None:
            self._client.username_pw_set(username, password)
        self._misc_loop_task: Task = None
        self.connected = False
        if notify_birth:
            self.on_connect = [self.notify_birth]
        else:
            self.on_connect = []
        self.state_key = state_key
        self.on_disconnect = []
        self.on_message = []
        self._client.will_set(
            f"{self.client_id}/{state_key}",
            json.dumps({"connected": False}),
            retain=True,
        )
        self._client.on_socket_open = self._on_socket_open
        self._client.on_socket_close = self._on_socket_close
        self._client.on_socket_register_write = self._on_socket_register_write
        self._client.on_socket_unregister_write = self._on_socket_unregister_write
        self._client.on_connect = self._handle_on_connect
        self._client.on_disconnect = self._handle_on_disconnect
        self._client.on_message = self._handle_on_message

    def _handle_on_connect(self, *args, **kwargs):
        self._connted = True
        for on_connect_handler in self.on_connect:
            try:
                func = on_connect_handler(*args, **kwargs)
                if callable(func):
                    self._loop.call_soon_threadsafe(func)
            except Exception as error:
                _LOGGER.exception(f"Failed handling connect {error}")
        _LOGGER.info("Connected to %s:%s", self.host, self.port)

    async def subscribe(self, *args, **kwargs):
        self._client.subscribe(*args, **kwargs)
        await asyncio.sleep(0.01)

    def message_callback_add(self, *args, **kwargs):
        self._client.message_callback_add(*args, **kwargs)

    def _handle_on_disconnect(self, *args, **kwargs):
        self._connted = False
        for on_disconnect_handler in self.on_disconnect:
            try:
                func = on_disconnect_handler(*args, **kwargs)
                if callable(func):
                    self._loop.call_soon_threadsafe(func)
            except Exception as error:
                _LOGGER.exception(f"Failed handling disconnect {error}")
        _LOGGER.warning("Disconnected from %s:%s", self.host, self.port)

    def _handle_on_message(self, client: Client, userData: None, msg: MQTTMessage):
        _LOGGER.debug('on message invoke')
        for cb_func in self.on_message:
            try:
                if callable(cb_func):
                    _LOGGER.debug('call func')
                    self._loop.call_soon_threadsafe(cb_func, client, msg)
            except Exception as error:
                _LOGGER.exception(f"Failed handling on_message {error}")

    def _on_socket_open(self, client: Client, userdata, sock):
        _LOGGER.debug("MQTT socket opened")

        def cb():
            # _LOGGER.debug('MQTT Socket is readable, calling loop read')
            client.loop_read()

        self._loop.add_reader(sock, cb)
        self._misc_loop_task = self._hass.async_create_background_task(
            self._create_misc_loop(), f'amqtt_misc_loop_{self.host}')
        self.connected = True

    def _on_socket_close(self, client: Client, userdata, sock):
        _LOGGER.debug("MQTT socket closed")
        self.connected = False
        self._loop.remove_reader(sock)
        if self._misc_loop_task is not None and not self._misc_loop_task.done():
            self._misc_loop_task.cancel()

    def _on_socket_register_write(self, client: Client, userdata, sock):
        _LOGGER.debug("Watching MQTT socket for writability.")

        def cb():
            # _LOGGER.debug('MQTT Socket is writeable, calling loop write')
            client.loop_write()

        self._loop.add_writer(sock, cb)

    def _on_socket_unregister_write(self, client: Client, userdata, sock):
        _LOGGER.debug("Stop watching MQTT socket for writability.")
        self._loop.remove_writer(sock)

    async def _create_misc_loop(self):
        """misc loop need maintain state"""
        _LOGGER.debug("Misc MQTT loop started")
        while self._client.loop_misc() == paho.MQTT_ERR_SUCCESS:
            try:
                # _LOGGER.debug('Misc loop sleep')
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
        _LOGGER.debug("Misc MQTT loop is finished")

    async def reconnect_loop(self):
        """tries to connect forever unless stop set or connection established"""
        _LOGGER.debug(
            f"MQTT starting reconnect loop to {self.host} {self.port}")
        while not self._stop:
            try:
                if not self._connted:
                    _LOGGER.warning(
                        "start mqtt connect"
                    )
                    self._client.connect(self.host, port=self.port,
                                         keepalive=self.keepalive)
            except Exception as error:
                _LOGGER.warning(
                    f"MQTT connect failed {error}, sleeping {self.reconnect_interval}")
            await asyncio.sleep(self.reconnect_interval)
        _LOGGER.info("MQTT stop reconnect loop")

    def start(self):
        _LOGGER.debug('start amqtt')
        self._reconnector_loop_task = self._hass.async_create_background_task(
            self.reconnect_loop(), f'mqtt_reconn_loop_{self.host}')

    def stop(self):
        _LOGGER.info("mqtt stopping")
        self._stop = True
        # mqtt broker will send last will since brake of unexpectedly
        if self._reconnector_loop_task is not None and not self._reconnector_loop_task.done():
            self._reconnector_loop_task.cancel()
        sock = self._client.socket()
        if sock is not None:
            sock.close()
        if self._misc_loop_task is not None and not self._misc_loop_task.done():
            self._misc_loop_task.cancel()
        _LOGGER.info("mqtt stopped")

    async def publish(self, topic, payload, **kwargs):
        _LOGGER.debug(f'pub topic {topic}')
        self._client.publish(topic, payload, **kwargs)
        await asyncio.sleep(0.01)

    @staticmethod
    def timestamp():
        time_format = strftime("%Y-%m-%d %H:%M:%S", localtime(time.time()))
        return time_format

    async def notify_birth(self, *args, **kwargs):
        await self.publish(
            self.state_key,
            json.dumps({"connected": True, "at": self.timestamp()}),
            retain=True,
        )
