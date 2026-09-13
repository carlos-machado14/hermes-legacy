# Data and update policy

This repository contains only reusable Hermes code, generic defaults and example configuration.

## Never committed

User-specific runtime data must stay outside the Git checkout, normally under `~/.hermes/`:

- credentials and auth files;
- API keys and `.env` files;
- cron jobs and schedules created by the user;
- Telegram/WhatsApp/app identifiers;
- memories, events and operational history;
- subscriptions or financial data;
- personal timezone/preferences;
- local models and generated state;
- backups and logs.

The repository `.gitignore` also blocks common local-state names as a second line of defense.

## Updates

`./update.sh` performs a fast-forward `git pull` and runs the idempotent installers.

Updates may replace application code and systemd service definitions owned by this project, but they must not:

- create/edit/delete user cron jobs;
- change the user's timezone;
- overwrite `~/.hermes/core-v2/config.yaml`;
- overwrite user-created scripts;
- reset memory or operational state;
- copy one developer's state into another installation.

Schema migrations, when eventually needed for Hermes Core's own internal state format, must be automatic, versioned, idempotent and operate only on the local user's runtime state. They must never contain hard-coded user records or schedules.

## First-time setup

A fresh clone starts without personal data. The installer creates runtime directories and example-derived local configuration only when those files do not already exist.

Timezone is opt-in and generic:

```bash
./configure-timezone.sh America/Sao_Paulo
```

Each installation owns its own data under `~/.hermes/`.
