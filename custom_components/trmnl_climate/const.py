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

# Chart options — just two toggles
CONF_SHOW_1DAY = "show_1day"
CONF_SHOW_7DAY = "show_7day"

# Auto-detect sensor type in priority order
CHART_SENSOR_PRIORITY = ["temperature", "humidity", "carbon_dioxide", "pressure"]

CHART_SENSOR_LABELS = {
    "temperature": "Temperature",
    "humidity": "Humidity",
    "carbon_dioxide": "CO₂",
    "pressure": "Pressure",
}
