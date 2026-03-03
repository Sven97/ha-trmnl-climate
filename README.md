# TRMNL HA Climate Connector

A Home Assistant custom integration that pushes climate sensor data to your
[TRMNL](https://usetrmnl.com) e-ink display — grouped by area, with live
values or historical charts.

**Supported sensor types:** temperature · humidity · CO₂ · pressure · PM2.5 · PM10 · VOC · NO₂ · CO

---

## Features

- **Values mode** — shows current readings per area with sensor icons; choose which sensor types to display
- **Chart mode** — line chart (history over time) or gauge dials (current value), one sensor type per chart instance
- **Up to 4 areas** displayed simultaneously
- **TRMNL mashup ready** — combine multiple plugin instances (e.g. values + chart) using TRMNL's built-in Mashup UI
- Single shared template that adapts to all TRMNL slot sizes: Full, Half horizontal, Half vertical, Quadrant
- Scheduled push (configurable interval) + on-demand push button in HA
- No external server — HA pushes outbound to TRMNL's webhook; your credentials never leave your home network

---

## How it works

```
Home Assistant (every N minutes)
  → reads area registry + entity states (+ recorder history for charts)
  → POST https://trmnl.com/api/custom_plugins/{UUID}
       { merge_variables: { areas: [...], chart: {...} } }

TRMNL receives push → renders shared.html → displays on device
```

---

## Installation

### Via HACS (recommended)

1. Open HACS in your Home Assistant instance
2. Go to **Integrations → ⋮ → Custom Repositories**
3. Add `https://github.com/Sven97/ha-trmnl-climate` with category **Integration**
4. Search for **TRMNL HA Climate Connector** and click **Download**
5. Restart Home Assistant

### Manual

Copy `custom_components/trmnl_climate/` into your HA `config/custom_components/`
directory and restart.

---

## Setup

### 1. Create the TRMNL plugin

1. In your TRMNL dashboard: **Plugins → Custom → New Plugin**
2. Strategy: **Webhook** — no form fields needed
3. Open the **Markup Editor**, select the **Shared** tab, and paste the contents of [`trmnl/shared.html`](trmnl/shared.html)
4. Save and copy the **Webhook URL** (e.g. `https://trmnl.com/api/custom_plugins/xxxxxxxxxxxxxxxx`)

> **Tip:** To show both values and a chart on one screen, create two separate plugin instances with the same webhook URL and arrange them with TRMNL's Mashup UI.

### 2. Add the integration in Home Assistant

1. **Settings → Devices & Services → Add Integration**
2. Search for **TRMNL HA Climate Connector**
3. Paste the webhook URL → **Submit**

The integration pushes current data immediately, then on the configured schedule.

---

## Configuration

Open **Configure** on the integration to adjust settings. The flow walks through each option in order:

| Step | Setting | Description |
|------|---------|-------------|
| 1 | **Push interval** | How often HA pushes data to TRMNL (5–60 min). Configure independently from the TRMNL device Refresh Rate — both must be set. |
| 2 | **Areas** | Up to 4 areas to display. Leave empty to auto-include all areas with climate sensors (up to 4, alphabetically). |
| 3 | **Display mode** | **Values** — current sensor readings per area. **Chart** — line chart or gauge. |
| 4a | **Sensor types** *(values mode)* | Which sensor types to show per area. Leave empty to show all available types. |
| 4b | **Sensor type** *(chart mode)* | One type for the chart — each configured area becomes a separate line or gauge dial. |
| 5 | **Chart type + history window** *(chart mode only)* | Line chart with 6/12/24 h of history, or Gauge showing the current value. |

> Sensors must be assigned to areas in **Settings → Areas & Zones**, and each entity must have a `device_class` set.

---

## Mashup examples

TRMNL's [Mashup](https://docs.usetrmnl.com/go/framework/mashup) UI lets you combine multiple plugin instances on one screen. Each instance uses the same webhook URL but can be configured independently.

| Layout | Slot A | Slot B |
|--------|--------|--------|
| 1 Top, 1 Bottom | Values — all areas | Temperature line chart |
| 1 Left, 1 Right | Values — indoor areas | Values — outdoor areas |
| 1 Left, 2 Right | Values — all areas | CO₂ gauge · Humidity gauge |

---

## Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| "No climate sensors found" on display | Sensors not assigned to areas — go to Settings → Areas & Zones |
| "Cannot connect" during setup | Wrong webhook URL, or TRMNL temporarily unreachable |
| Sensor missing from display | `device_class` not set — edit the entity in Settings → Devices |
| Chart shows no data | Recorder integration not running, or history window too short |
| Data appears stale | Both push interval (HA) and Refresh Rate (TRMNL) must be configured |
| Payload size warning | Free tier: 2 kb limit; TRMNL+: 5 kb. Reduce areas or limit sensor types in configuration. |

---

## License

MIT
