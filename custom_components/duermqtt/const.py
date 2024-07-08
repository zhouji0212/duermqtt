"""Constants for the bemfa integration."""

from typing import Final

from homeassistant.backports.enum import StrEnum

DOMAIN: Final = "duermqtt"
CONST_VERSION: Final = '2024.7.8'

# #### Config ####
CONF_TOKEN: Final = "uid"
CONF_TOKEN: Final = "token"

OPTIONS_CONFIG: Final = "config"
OPTIONS_SELECT: Final = "select"

OPTIONS_NAME: Final = "name"

OPTIONS_TEMPERATURE: Final = "temperature"
OPTIONS_HUMIDITY: Final = "humidity"
OPTIONS_ILLUMINANCE: Final = "illuminance"
OPTIONS_PM25: Final = "pm25"
OPTIONS_CO2: Final = "co2"

OPTIONS_FAN_SPEED_0_VALUE: Final = "fan_speed_0_value"
OPTIONS_FAN_SPEED_1_VALUE: Final = "fan_speed_1_value"
OPTIONS_FAN_SPEED_2_VALUE: Final = "fan_speed_2_value"
OPTIONS_FAN_SPEED_3_VALUE: Final = "fan_speed_3_value"
OPTIONS_FAN_SPEED_4_VALUE: Final = "fan_speed_4_value"
OPTIONS_FAN_SPEED_5_VALUE: Final = "fan_speed_5_value"

OPTIONS_SWING_OFF_VALUE: Final = "swing_off_value"
OPTIONS_SWING_HORIZONTAL_VALUE: Final = "swing_horizontal_value"
OPTIONS_SWING_VERTICAL_VALUE: Final = "swing_vertical_value"
OPTIONS_SWING_BOTH_VALUE: Final = "swing_both_value"

# #### MQTT ####

MQTT_PORT: Final = 1883
MQTT_KEEPALIVE: Final = 600
TOPIC_PREFIX = 'test'
TOPIC_PING = "topic_ping"
TOPIC_REPORT: Final = "ha2xiaodu/command/{topic}"
TOPIC_REPORT: Final = "ha2xiaodu/report/{topic}"
INTERVAL_PING_SEND = 30  # send ping msg every 30s
INTERVAL_PING_RECEIVE = 20  # detect a ping lost in 20s after a ping message send
MAX_PING_LOST = 3  # reconnect to mqtt server when 3 continous ping losts detected
MSG_SEPARATOR: Final = "#"
MSG_ON: Final = "on"
MSG_OFF: Final = "off"
MSG_PAUSE: Final = "pause"  # for covers
MSG_SPEED_COUNT: Final = 4  # for fans, 4 speed supported at most

# #### Service Api ####
CONST_GET_VERSION_CHECK_URL = '/api/plugin/config'
CONST_POST_SYNC_DEVICE_URL = '/api/device/sync_entity_v1'
CONST_POST_SYNC_STATE_URL = '/api/device/change_state'
CONF_ENTITY_CONFIG = "entity_config"
CONF_FILTER = "filter"
CONF_INCLUDE_DOMAINS: Final = "include_domains"
CONF_INCLUDE_ENTITIES: Final = "include_entities"
CONF_EXCLUDE_DOMAINS: Final = "exclude_domains"
CONF_EXCLUDE_ENTITIES: Final = "exclude_entities"


CONFIG_OPTIONS = [
    CONF_FILTER,
    CONF_ENTITY_CONFIG,
]
