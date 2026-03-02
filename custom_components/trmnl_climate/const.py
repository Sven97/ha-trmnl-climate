DOMAIN = "trmnl_climate"

CONF_WEBHOOK_URL = "webhook_url"

PUSH_INTERVAL_MINUTES = 15

CLIMATE_DEVICE_CLASSES = frozenset({
    "temperature",
    "humidity",
    "carbon_dioxide",
    "pressure",
    "pm25",
    "pm10",
    "volatile_organic_compounds",
    "nitrogen_dioxide",
    "carbon_monoxide",
})
