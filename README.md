<img src="https://raw.githubusercontent.com/Meppies/ha-brager-one/main/custom_components/brager_one/brand/icon.png" alt="" width="96" align="right">

# BragerOne for Home Assistant

[![Validate](https://github.com/Meppies/ha-brager-one/actions/workflows/validate.yml/badge.svg)](https://github.com/Meppies/ha-brager-one/actions/workflows/validate.yml)
[![Open your Home Assistant instance and add this repository to the Marketplace.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=Meppies&repository=ha-brager-one&category=integration)

A custom integration for pellet stoves and boilers that are connected to the **BragerOne** cloud (the web app at [one.brager.pl](https://one.brager.pl) and the BragerOne mobile app). It reads temperatures, burner data, pump states and alarms, lets you switch the boiler on and off, and change the boiler and hot water setpoints.

It talks to the same cloud API as the BragerOne web app. There is no official public API, so the integration depends on how Brager runs that service.

## Supported devices

- Tested: an HT-Tronic pellet stove with the HT Connect gateway (firmware 2.09) and an HT900TO controller.
- Expected to work: other controllers that BragerOne shows with the same parameter layout (boiler temperature in P4 v0, boiler setpoint in P6 v0). Entities are only created for parameters your controller actually reports.
- Not supported: heat pumps and other device families in BragerOne that use a different parameter layout. Diagnostics (see below) show what your device reports; open an issue with that file if you want support added.

## Installation

The integration is installed through the Marketplace (Home Assistant 2026.11 and newer) as a custom repository.

1. Click the "add to Marketplace" button above, or go to **Settings → Marketplace → ⋮ → Custom repositories** and add `https://github.com/Meppies/ha-brager-one` with type **Integration**.
2. Install **BragerOne** and restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and pick **BragerOne**.

Manual install: copy `custom_components/brager_one` into the `custom_components` folder of your configuration and restart.

### Configuration parameters

| Field | Description |
|---|---|
| Email | The email address of your BragerOne account. |
| Password | The password of that account. Home Assistant stores it to renew the session when the cloud token expires. |
| Module | Only asked when the account has more than one module. Each module becomes its own entry; add the others by running the flow again. |

### Options

| Option | Description |
|---|---|
| Polling interval | How often the stove is read from BragerOne, set with a slider in seconds: 10 to 300, default 60. Open the entry and choose **Configure**. The integration reloads with the new interval. Short intervals send more requests to the BragerOne cloud. |

To use another account or a new password, open the entry and choose **Reconfigure**. When BragerOne rejects the stored password, Home Assistant asks for the new one by itself.

## Entities

| Entity | Type | Source | Default |
|---|---|---|---|
| Boiler | switch | status word P5 s0 (bit 0); sends `BOILER_START` / `BOILER_STOP` | enabled |
| Boiler setpoint | number | P6 v0, limits from P6 n0 / x0 | enabled |
| Hot water setpoint | number | P6 v51, limits from P6 n51 / x51 | enabled |
| Boiler temperature | sensor | P4 v0 | enabled |
| Return temperature | sensor | P4 v1 | enabled |
| Feeder temperature | sensor | P4 v3 | enabled |
| Flame brightness | sensor | P4 v13 (%) | enabled |
| Burner power | sensor | P4 v14 (kW, reported in tenths) | enabled |
| Blower output | sensor | P4 v15 (%) | enabled |
| Operating state | sensor (enum) | bits 8-11 of P5 s5: `cleaning` (1), `igniting` (2), `work` (3), `damping` (4) or `standby` (5); unknown for other codes | enabled |
| Active alarms | sensor | number of active alarms, with code, description, start and end as attributes | enabled |
| Last alarm | sensor (timestamp) | start of the most recent alarm; attributes hold its code, description, end and the ten most recent alarms | enabled |
| Operating state code | sensor (diagnostic) | the state number from P5 s5, also for states not named yet | enabled |
| Boiler pump, Return pump, Hot water pump | binary sensor | P5 s11, s12, s19 | enabled |
| Hot water, outdoor, mixing valve 1, buffer and flue gas temperature | sensor | P4 v2, v4, v5, v6, v7 | disabled |
| Fuel level, oxygen in flue gas | sensor | P4 v8, v16 | disabled |

Disabled entities exist because many installations have no sensor connected to those inputs. Enable the ones that apply to you.

While an alarm is active, a repair issue appears under **Settings → System → Repairs**. It disappears when the alarm is cleared.

## Dashboard card

The integration ships a card, so there is nothing extra to install. After setup it is registered as a dashboard resource and appears in the card picker as **BragerOne**.

```yaml
type: custom:brager-one-card
device_id: <your BragerOne device>   # optional; the first BragerOne device is used when left out
name: Pellet stove                   # optional
```

The card shows:

- the boiler temperature with a bar towards the setpoint, and buttons to change the boiler and hot water setpoints (several taps are sent as one change);
- the operating state and an on/off button. Starting or stopping the boiler needs a second tap within four seconds, so it cannot happen by accident;
- return and feeder temperature, flame, blower and burner power;
- the three pumps, each with a word (running or stopped) as well as an icon;
- active alarms with ▲, or ✓ when there are none, and the most recent alarm. Alarm texts follow the dashboard language (English and Dutch).

Tap any value to open its history. The card follows the Home Assistant theme, light and dark. States never rely on colour alone.

The card is removed from the dashboard resources when the last BragerOne entry is deleted. Dashboards in YAML mode need the resource added by hand: `/brager_one/brager-one-card.js` as a JavaScript module.

## How data is updated

The integration polls BragerOne every 60 seconds by default (adjustable from 10 seconds to 5 minutes, see Options): one request for all parameters and one for active alarms. The alarm history is read every 10 minutes, and straight away when the set of active alarms changes. After you switch the boiler or change a setpoint, it polls again 5 seconds later. The entity shows the new value straight away and keeps it for up to 45 seconds while the cloud catches up.

## Use cases

- Show the boiler and return temperature on a dashboard next to your room thermostats.
- Get a notification when the stove reports an alarm, for example when the hopper runs empty.
- Switch the stove off automatically when you leave for a longer period, and back on before you return.
- Lower the boiler setpoint at night.

## Examples

Notify when an alarm appears:

```yaml
automation:
  - alias: "Pellet stove alarm"
    triggers:
      - trigger: numeric_state
        entity_id: sensor.pellet_stove_active_alarms
        above: 0
    actions:
      - action: notify.mobile_app_phone
        data:
          title: "Pellet stove"
          message: >-
            {{ state_attr('sensor.pellet_stove_active_alarms', 'alarms')
               | map(attribute='description') | join(', ') }}
```

Lower the boiler setpoint at night:

```yaml
automation:
  - alias: "Boiler setpoint night"
    triggers:
      - trigger: time
        at: "23:00:00"
    actions:
      - action: number.set_value
        target:
          entity_id: number.pellet_stove_boiler_setpoint
        data:
          value: 65
```

## Known limitations

- BragerOne has no official API. A change on Brager's side can break the integration without warning.
- The operating state codes are not documented. Only 1 ("Cleaning"), 3 ("Work"), 4 ("Damping") and 5 ("Standby") have been matched against the BragerOne app so far; other phases such as ignition show as unknown, with the raw number in the diagnostic code sensor. Open an issue with the code and what the app shows to get one added.
- Pump states: 3 is "on" and 0 or 1 is "off" in the app. Other values show as unknown.
- Burner power is reported in tenths of a kW (raw 200 is 20.0 kW, checked against the app).
- Changes are not pushed live; values are at most about a minute old.
- The integration does not offer a climate entity. A boiler water setpoint is not a room thermostat; use the number entity instead.
- Alarm descriptions are only available in English. Codes 54, 55 and 500 use the BragerOne app's wording; the others come from the controller manual.

## Troubleshooting

- **"BragerOne rejected the email address or password"**: log in at [one.brager.pl](https://one.brager.pl) with the same details.
- **Entities unavailable**: BragerOne could not be reached or returned an error. The log shows the reason once, and again when the connection recovers. Check whether the web app works.
- **A setpoint jumps back**: the controller refused the value, or the stove is in a mode where it ignores remote changes. Check the same change in the BragerOne app.
- **The card shows an old state or "State code" after an update**: the browser still runs the previous version of the card. Reload the page with the cache cleared (Ctrl+Shift+R, or in the companion app: Settings → Companion app → Debugging → Reset frontend cache). The browser console shows the loaded version as `BRAGER-ONE-CARD x.y.z`.
- **Debug logging**:

  ```yaml
  logger:
    logs:
      custom_components.brager_one: debug
  ```

- **Diagnostics**: on the device page choose **Download diagnostics**. The file contains all parameters with the email, password and module ID removed. Attach it to an issue.

## Migrating from the old `ht_tronic` integration

This integration replaces the earlier home-made `ht_tronic` integration. The domain and entity IDs are new, so:

1. Note which `ht_tronic` entities your dashboards and automations use.
2. Remove the `ht_tronic` entry and delete `custom_components/ht_tronic`.
3. Install and set up BragerOne, then update the entity IDs. The old climate entity maps to the **Boiler** switch plus the **Boiler setpoint** number.

## Removal

1. Go to **Settings → Devices & services → BragerOne**, open the ⋮ menu of the entry and choose **Delete**.
2. Remove the repository in the Marketplace, or delete `custom_components/brager_one`, and restart Home Assistant.

Removing the entry does not change anything on the stove or in your BragerOne account.

## Licence

MIT. Not affiliated with or endorsed by Brager.
