# RunPod Alerts Telegram Bot

Minimal aiogram bot that monitors RunPod balance and sends notifications to Telegram. Features:

- **Daily heartbeat**: Posts balance status at 12:00 UTC (configurable)
- **Low balance alerts**: Sends alerts with decaying intervals (starting at 6h, down to 15min)
- **Recovery notifications**: Alerts when balance recovers above threshold
- **Bot commands**: `/balance` and `/status` for on-demand balance checks

Uses RunPod GraphQL `myself` to read `clientBalance` and `currentSpendPerHr` [spec](https://graphql-spec.runpod.io/#introduction).

## Environment

Configuration uses `pydantic-settings`. Set environment variables or create a `.env` file.

Required:
- `RUNPOD_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` (group id)

Optional (defaults in parentheses):
- `DAILY_NOTIFY_TIME` ("12:00")
- `DAILY_NOTIFY_TZ` ("UTC")
- `LOW_BALANCE_USD` (20.0)
- `POD_STOP_BALANCE_USD` (0.0) - balance at which pods actually stop (can be negative)
- `ALERT_INITIAL_INTERVAL_MINUTES` (360.0)
- `ALERT_DECAY_FACTOR` (0.5)
- `ALERT_MINIMUM_INTERVAL_MINUTES` (15.0)
- `ALERT_HYSTERESIS_USD` (2.0)
- `POLL_INTERVAL_SEC` (60.0)
- `LOG_LEVEL` ("INFO")

## Run locally

```bash
uv run runpod-alerts-tg-bot
```

## Docker

Build and run via compose:

```bash
docker compose up --build -d
```

State is stored in `./data/state.json`.

## Bot Commands

The bot responds to commands only from the configured `TELEGRAM_CHAT_ID`:

- `/balance` - Show current RunPod balance with detailed time remaining and ETA

## Message Examples

**`/balance` command** (on-demand balance check):
```
💰 RunPod Balance
💵 Balance: $123.45
⚡️ Spend rate: $1.23/hr
🛑 Pods stop at: $0.00
⏳ Time remaining: ~4d 5.4h
🕐 Will run out at: 2025-10-17 17:30 UTC
```

**Daily heartbeat** (sent at configured time with silent notification):
```
ℹ️ RunPod Daily Balance Report
💰 Balance: $123.45
⚡️ Spend rate: $1.23/hr
🛑 Pods stop at: $0.00
⏳ Time remaining: ~4d 5.4h
🕐 Will run out at: ~2025-10-17 17:30 UTC
```

**Low balance alert** (sent when balance drops below threshold):
```
🚨 LOW BALANCE ALERT
💰 Current balance: $12.34
⚠️ Threshold: $20.00
⚡️ Spend rate: $0.90/hr
🛑 Pods stop at: $0.00
⏳ Time remaining: ~13.7h
🕐 Will run out at: 2025-10-13 03:12 UTC
```

**Recovery notification** (sent when balance recovers above threshold + hysteresis):
```
✅ Balance Recovered
💰 Current balance: $22.50
📈 Recovery threshold: $22.00
🔄 Alerts have been reset
```

## Testing

A comprehensive simulation script is available to test the service without requiring API keys or sending real messages:

```bash
uv run simulate.py
```

The simulation tests 12 different scenarios including:
- Normal balance operation
- Low balance alerts with exponential decay intervals
- Balance recovery notifications
- Balance depleted states (pods stopped)
- Negative balance with active spend (pods still running)
- Recovery from depleted state
- Edge cases and boundary conditions
- Daily report generation
- Negative threshold handling
- Negative pod stop balance (pods run below $0)

