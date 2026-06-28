# Person State

Adds `sleep`, `dnd`, and `away` states to the native Home Assistant person entity, plus boolean attributes, instead of creating a separate sensor.

The person entity stays the single object you click on the map. Native zone states (Work, School, ...) pass through untouched; only `home` and `not_home` get the extra layer.

## How it works

The integration does not own the person entity. It wraps two internal callbacks on core's `Person`:

- `_update_state` — runs core, then applies a cascade (`sleep > dnd > not_home→away > presence`)
- `async_added_to_hass` — runs core, then attaches a bedroom-door listener and sleep-window timers

State logic lives in `logic.py` (no HA imports, the direct port of the original Node-RED nodes). The wrapping lives in `augment.py` and is pinned against a known HA version (`BUILT_AGAINST`); a core rename fails loud and falls back to plain presence rather than going silently wrong.

## State and attributes

```
person.adalea
  state: sleep            # sleep | dnd | away | home | <zone name>
  attributes:
    presence: home        # raw person state before the cascade
    dnd: false
    is_sleep: true
    sleep_window: true
    sleep_grace: false
```

`door_age` is published only when the debug option is on (it churns, so it stays out of the recorder by default).

## Settings (per person)

- person and bedroom door contact
- sleep window start/end hour (default 22-08, local time)
- door-closed delay before DND (default 180s)
- door-open grace still counted as sleep (default 300s)

## Caveat

This touches core internals on purpose. Re-test after Home Assistant upgrades that change the person component and bump `BUILT_AGAINST` in `augment.py`.

## License

Copyright (C) 2026 FireBall1725. Licensed under the GNU Affero General Public License v3.0 or later. See [LICENSE](LICENSE).
