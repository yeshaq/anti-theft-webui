# About this fork

This fork is based on Open WebUI **v0.6.5**, the last release under the plain
BSD-3-Clause license (see `LICENSE`). Later upstream releases use a different
license with a branding clause, so **do not copy code from upstream releases
newer than v0.6.5** into this fork. Write fixes from public advisories instead.

## Branding

All logo, favicon and splash assets come from one image:

```bash
python3 scripts/rebrand_logo.py branding/anti-theft-logo.png
```

Add `--dark other.png` for a separate dark-mode image. Needs Pillow.

## Automations

Run a saved prompt against a model on a schedule. Each run creates a normal
chat in the user's "Automations" folder and sends a notification (and the
user's webhook, when they are away).

- Page: sidebar → **Automations** (`/automations`).
- Schedules: once, every N hours, daily, weekly, monthly, or a custom iCalendar
  RRULE. Times follow the user's timezone, including summer/winter time changes.
- Admins can turn it off per group: Admin → Users → Groups → Permissions →
  Features → Automations.

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `ENABLE_AUTOMATIONS` | `True` | Turn the feature and scheduler on or off |
| `USER_PERMISSIONS_FEATURES_AUTOMATIONS` | `True` | Default permission for users |
| `AUTOMATION_MAX_COUNT` | `20` | Max automations per non-admin user |
| `AUTOMATION_MIN_INTERVAL` | `300` | Shortest gap between runs, in seconds |
| `AUTOMATION_POLL_INTERVAL` | `30` | How often the scheduler checks, in seconds |
| `AUTOMATION_MAX_CONCURRENT` | `3` | Runs allowed at the same time |

With several workers on one database, each due run is claimed with a
compare-and-swap update, so it runs only once.
