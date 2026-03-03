DOMAIN = "trmnl_climate"

CONF_WEBHOOK_URL = "webhook_url"

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

# Chart count
CONF_CHART_COUNT = "chart_count"

# Chart 1
CONF_CHART1_SENSOR_TYPE = "chart1_sensor_type"
CONF_CHART1_AREAS = "chart1_areas"
CONF_CHART1_TYPE = "chart1_type"

# Chart 2
CONF_CHART2_SENSOR_TYPE = "chart2_sensor_type"
CONF_CHART2_AREAS = "chart2_areas"
CONF_CHART2_TYPE = "chart2_type"

# Per-chart history window (only used for line/bar)
CONF_CHART1_HOURS = "chart1_hours"
CONF_CHART2_HOURS = "chart2_hours"

CONF_PUSH_INTERVAL = "push_interval"

# Gauge y-axis ranges per sensor type
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
