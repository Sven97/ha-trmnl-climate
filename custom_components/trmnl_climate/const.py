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

# Chart order matches display order — all device classes are charted if data exists
CHART_SENSOR_ORDER = SENSOR_DISPLAY_ORDER

# Preferred Highcharts chart type per device class.
# areaspline is used for single-series; spline is used when multiple areas are present
# (overlapping fills on e-ink are unreadable).
CHART_TYPE_PREFERRED = {
    "temperature":                "spline",
    "humidity":                   "spline",
    "carbon_dioxide":             "areaspline",
    "pressure":                   "spline",
    "pm25":                       "areaspline",
    "pm10":                       "areaspline",
    "volatile_organic_compounds": "areaspline",
    "nitrogen_dioxide":           "areaspline",
    "carbon_monoxide":            "areaspline",
}
