DOMAIN = "trmnl_climate"

CONF_WEBHOOK_URL = "webhook_url"

PUSH_INTERVAL_MINUTES = 15

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

# Single toggle: enable 24h history charts
CONF_SHOW_CHART = "show_chart"

# Chart order (controls series order in the combined chart)
CHART_SENSOR_ORDER = SENSOR_DISPLAY_ORDER

# Device classes that go on the RIGHT y-axis (opposite: true).
# Everything else uses the LEFT y-axis.
CHART_YAXIS_RIGHT = {"humidity"}

# Short labels appended to area name when multiple sensor types are charted.
CHART_TYPE_SHORT = {
    "temperature":                "temp",
    "humidity":                   "hum",
    "carbon_dioxide":             "CO₂",
    "pressure":                   "hPa",
    "pm25":                       "PM2.5",
    "pm10":                       "PM10",
    "volatile_organic_compounds": "VOC",
    "nitrogen_dioxide":           "NO₂",
    "carbon_monoxide":            "CO",
}
