<!-- 0058ed7d-fbe8-47fc-b67b-95f59cd87bcf caabd33e-232c-4d49-8618-3d8c98701943 -->
# RunPod Telegram Balance Alerts Bot - Implementation Plan

## Scope

- Daily heartbeat at 15:00 Europe/Moscow with current balance, spend/hour, and hours-to-runout.
- Low balance alerts with decreasing delay (immediate, then exponentially shorter until a floor) while balance remains below threshold; reset when recovered (with hysteresis).
- Group chat delivery only.
- Data source: `myself { clientBalance currentSpendPerHr }` from RunPod GraphQL API per spec: [RunPod GraphQL API](https://graphql-spec.runpod.io/#introduction).

## Files to add/update

- `pyproject.toml`: add deps (aiogram, httpx, apscheduler, tzdata), console script entrypoint.
- `src/runpod_alerts_tg_bot/config.py`: env-driven settings (tokens, chat id, schedule, thresholds, intervals, hysteresis, timezones, logging).
- `src/runpod_alerts_tg_bot/runpod_client.py`: async GraphQL client to fetch balance and spend/hour.
- `src/runpod_alerts_tg_bot/telegram_bot.py`: thin sender using aiogram `Bot` for group messages.
- `src/runpod_alerts_tg_bot/alerts_service.py`: core logic - daily heartbeat job, low-balance monitor with decaying interval and state persistence (JSON file), formatting.
- `src/runpod_alerts_tg_bot/logging_setup.py`: basic logging config to stdout (level from env).
- `src/runpod_alerts_tg_bot/__main__.py`: CLI entrypoint calling `main()`.
- `src/runpod_alerts_tg_bot/__init__.py`: implement `main()` to wire config, logging, bot, scheduler, and tasks.
- `Dockerfile`: container image using python:3.13-slim-bookworm and uv.
- `compose.yml`: single service with envs and volume for state.
- `README.md`: setup, env vars, run instructions.

## Key behaviors

- Timezone-aware cron: daily at 15:00 Europe/Moscow using APScheduler `CronTrigger` with `Europe/Moscow`.
- Hours-to-runout = `clientBalance / currentSpendPerHr` (if spend is 0, show ∞ and suppress low alerts).
- Decaying alert cadence: immediate, then start interval halves each alert until a minimum; configurable via env.
- Hysteresis reset: alert state resets only after balance > threshold + hysteresis.
- Simple state persistence: `data/state.json` storing last alert ts, current interval, alert count.
- Robustness: retries for HTTP calls; exceptions logged; messages guarded to avoid duplicates.

## Essential snippets

- GraphQL query used:
```gql
query MyselfBalance { myself { clientBalance currentSpendPerHr } }
```

- Example alert cadence (configurable): immediate, then 6h, 3h, 1.5h, 45m, 22m, ... floored at 15m.

## Env variables

- `RUNPOD_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` (group id)
- `DAILY_NOTIFY_TIME` (default "15:00")
- `DAILY_NOTIFY_TZ` (default "Europe/Moscow")
- `LOW_BALANCE_USD` (default "20")
- `ALERT_START_INTERVAL_MIN` (default "360")
- `ALERT_DECAY_FACTOR` (default "0.5")
- `ALERT_MIN_INTERVAL_MIN` (default "15")
- `ALERT_HYSTERESIS_USD` (default "2")
- `POLL_INTERVAL_SEC` (default "60")

## Message format (examples)

- Daily: "RunPod balance: $123.45 - $1.23/hr - ~100.4h left (runs out ~2025-10-12 19:30 MSK)"
- Alert: "ALERT: balance low ($12.34 < $20.00). $0.90/hr - ~13.7h left (ETA 03:12 MSK)."

## Testing

- Dry-run mode with `TELEGRAM_CHAT_ID` pointing to a private test group.
- Force-alert script path by temporarily lowering `LOW_BALANCE_USD` locally.

## Rollout

- Single process service (systemd/Docker) with envs. Ensure only one instance runs to avoid duplicate alerts.

### To-dos

- [ ] Add deps and console script in pyproject.toml
- [ ] Create config loader using env vars and timezone
- [ ] Implement async GraphQL client for balance and spend/hour
- [ ] Implement aiogram Bot sender for group chat
- [ ] Build heartbeat and decaying alert logic with state
- [ ] Wire scheduler and tasks in main entrypoint
- [ ] Document envs and run instructions in README.md