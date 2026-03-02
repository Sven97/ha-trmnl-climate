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

# Chart options
CONF_CHART_TYPE = "chart_type"
CONF_CHART_SENSOR = "chart_sensor"
CONF_CHART_AREA = "chart_area"
CONF_CHART_RESOLUTION = "chart_resolution"
CONF_CHART_DAILY_MODE = "chart_daily_mode"

CHART_TYPE_DISABLED = "disabled"
CHART_TYPE_24H = "24h_trend"
CHART_TYPE_7DAY = "7day_averages"

CHART_RESOLUTION_1H = "1"
CHART_RESOLUTION_2H = "2"
CHART_RESOLUTION_6H = "6"

CHART_DAILY_AVERAGE = "average"
CHART_DAILY_MINMAX = "minmax"

CHART_SENSOR_OPTIONS = ["temperature", "humidity", "carbon_dioxide", "pressure"]
