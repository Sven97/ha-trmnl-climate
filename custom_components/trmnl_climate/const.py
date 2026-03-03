DOMAIN = "trmnl_climate"

CONF_WEBHOOK_URL = "webhook_url"
CONF_PUSH_INTERVAL = "push_interval"
CONF_AREAS = "areas"
CONF_DISPLAY_MODE = "display_mode"         # "values" | "chart"
CONF_SENSOR_TYPES = "sensor_types"         # values mode: list of sensor type strings
CONF_CHART_SENSOR_TYPE = "chart_sensor_type"  # chart mode: single sensor type string
CONF_CHART_TYPE = "chart_type"             # "line" | "gauge"
CONF_CHART_HOURS = "chart_hours"

SENSOR_DISPLAY_ORDER = [
    "temperature",
    "humidity",
    "carbon_dioxide",
    "pressure",
    "pm25",
    "pm10",
    "volatile_organic_compounds",
    "nitrogen_dioxide",
    "carbon_monoxide",
]

CLIMATE_DEVICE_CLASSES = frozenset(SENSOR_DISPLAY_ORDER)

GAUGE_RANGES = {
    "temperature":                (0, 40),
    "humidity":                   (0, 100),
    "carbon_dioxide":             (400, 2000),
    "pressure":                   (960, 1040),
    "pm25":                       (0, 150),
    "pm10":                       (0, 200),
    "volatile_organic_compounds": (0, 500),
    "nitrogen_dioxide":           (0, 200),
    "carbon_monoxide":            (0, 100),
}
