# TRMNL HA Climate Connector

A Home Assistant custom integration that pushes climate sensor data (temperature,
humidity, CO₂, etc.) to a [TRMNL](https://usetrmnl.com) device, grouped by area.
Only areas that contain at least one climate sensor are included.

**Supported device classes:** temperature · humidity · carbon_dioxide · pressure ·
pm25 · pm10 · volatile_organic_compounds · nitrogen_dioxide · carbon_monoxide

---

## How it works

```
HA integration (every 15 min)
  → reads area registry + entity states
  → POST https://trmnl.com/api/custom_plugins/{UUID}
       { merge_variables: { areas: [...] } }

TRMNL receives push → renders markup → shows on device
```

No external server. HA pushes data outbound to TRMNL's webhook endpoint.
Your HA credentials never leave your home network.

---

## Installation

### Via HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Go to **Integrations → ⋮ → Custom Repositories**
3. Add `https://github.com/Sven97/ha-trmnl-climate` with category **Integration**
4. Search for **TRMNL HA Climate Connector** and click **Download**
5. Restart Home Assistant

### Manual

Copy the `custom_components/trmnl_climate/` folder into your HA
`config/custom_components/` directory and restart.

---

## Setup

### 1. Create the TRMNL plugin

1. In TRMNL dashboard: **Plugins → Custom → New Plugin**
2. Strategy: **Webhook**
3. No form fields needed
4. Paste `trmnl/markup.html` into the **Markup Editor**
5. Save — copy the **Webhook URL** shown on the settings page
   (looks like `https://trmnl.com/api/custom_plugins/xxxxxxxxxxxxxxxx`)


### 2. Add the integration

1. **Settings → Devices & Services → Add Integration**
2. Search for **TRMNL HA Climate Connector**
3. Paste the webhook URL and submit

The integration immediately pushes the current data, then refreshes every 15 minutes.

---

## Troubleshooting

| Symptom | Cause |
|---------|-------|
| Display empty / "No climate sensors" | Sensors not assigned to areas — go to Settings → Areas & Zones |
| "Cannot connect" during setup | Wrong webhook URL, or TRMNL unreachable |
| Warnings in HA logs | TRMNL returned a non-2xx status — check the webhook URL |
| Sensor missing from an area | `device_class` not set — edit the entity in HA Settings → Devices |
| Data cuts off | Payload over 2 kb (free) / 5 kb (TRMNL+) — reduce sensor count or areas |

### Payload size estimate

Each sensor entry is ~60 bytes:

| Setup | Size |
|-------|------|
| 4 areas × 3 sensors | ~800 b |
| 8 areas × 3 sensors | ~1.5 kb |
| 10 areas × 5 sensors | ~3 kb (needs TRMNL+) |

To reduce payload, edit `CLIMATE_DEVICE_CLASSES` in `const.py` and remove
device classes you don't need.
