"""Constants for the TaskPad integration."""

DOMAIN = "taskpad"

CONF_TOPIC_PREFIX = "topic_prefix"
CONF_LOG_PATH = "log_path"
CONF_DEFAULT_INTERVAL = "default_interval_days"
CONF_IMPORT_ENTITY = "import_entity"
CONF_DEVICE_HOST = "device_host"
CONF_MQTT_URI = "mqtt_uri"
CONF_MQTT_USERNAME = "mqtt_username"
CONF_MQTT_PASSWORD = "mqtt_password"

DEFAULT_TOPIC_PREFIX = "taskpad"
DEFAULT_LOG_FILENAME = "taskpad_history.log"
DEFAULT_INTERVAL_DAYS = 30

EVENT_COMPLETED = "taskpad_completed"
EVENT_BLOCKED = "taskpad_blocked"

STORAGE_VERSION = 1
STORAGE_KEY = "taskpad.tasks"

SERVICE_COMPLETE = "complete"
SERVICE_BLOCK = "block"
SERVICE_ADD_TASK = "add_task"
SERVICE_UPDATE_TASK = "update_task"
ATTR_TASK = "task"

INTERVAL_UNITS = ["days", "weeks", "months"]
UNIT_TO_DAYS = {"days": 1, "weeks": 7, "months": 30}

CARD_URL = "/taskpad_files/taskpad-card.js"
VERSION = "0.7.0"  # keep in sync with manifest.json

# "interval: 90" / "interval: 2w" / "interval: 3m" / "interval: 1y"
INTERVAL_PATTERN = r"interval:\s*(\d+)\s*([dwmy]?)"
INTERVAL_UNIT_DAYS = {"": 1, "d": 1, "w": 7, "m": 30, "y": 365}

STATUS_NEEDS_ACTION = "needs_action"
STATUS_COMPLETED = "completed"
