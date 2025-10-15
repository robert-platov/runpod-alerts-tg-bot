import json
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import AppConfig
from .runpod_client import BalanceInfo, RunpodClient
from .telegram_bot import TelegramSender

logger = logging.getLogger(__name__)


DAILY_BALANCE_TEMPLATE = (
    "ℹ️ <b>RunPod Daily Balance Report</b>\n\n"
    "💰 Balance: ${balance:,.2f}\n"
    "⚡️ Spend rate: ${spend:,.2f}/hr\n"
    "🛑 Pods stop at: ${pod_stop_balance:,.2f}\n"
    "⏳ Time remaining: ~{time_remaining}\n"
    "🕐 Will run out at: ~{eta}"
)

LOW_BALANCE_ALERT_TEMPLATE = (
    "🚨 <b>LOW BALANCE ALERT</b>\n\n"
    "💰 Current balance: ${balance:,.2f}\n"
    "⚠️ Threshold: ${threshold:,.2f}\n"
    "⚡️ Spend rate: ${spend:,.2f}/hr\n"
    "🛑 Pods stop at: ${pod_stop_balance:,.2f}\n"
    "⏳ Time remaining: ~{time_remaining}\n"
    "🕐 Will run out at: {eta}"
)

BALANCE_RECOVERED_TEMPLATE = (
    "✅ <b>Balance Recovered</b>\n\n"
    "💰 Current balance: ${balance:,.2f}\n"
    "📈 Recovery threshold: ${recovery_threshold:,.2f}\n"
    "🔄 Alerts have been reset"
)

BALANCE_DEPLETED_TEMPLATE = (
    "🔴 <b>BALANCE DEPLETED - PODS STOPPED</b>\n\n"
    "💰 Current balance: ${balance:,.2f}\n"
    "⚠️ Threshold: ${threshold:,.2f}\n"
    "🛑 Pod stop balance: ${pod_stop_balance:,.2f}\n"
    "⚡️ Spend rate: $0.00/hr (pods stopped)\n"
    "💀 All pods have been shut down due to insufficient balance"
)


@dataclass
class AlertState:
    last_alert_at: float | None
    current_interval_min: float
    alert_count: int


def _now_ts() -> float:
    return datetime.now(tz=UTC).timestamp()


class AlertsService:
    def __init__(
        self, cfg: AppConfig, sender: TelegramSender, state_path: Path
    ) -> None:
        self._cfg = cfg
        self._sender = sender
        self._state_path = state_path
        self._state = self._load_state()

    def _load_state(self) -> AlertState:
        if self._state_path.exists():
            try:
                raw = json.loads(self._state_path.read_text())
                return AlertState(
                    last_alert_at=raw.get("last_alert_at"),
                    current_interval_min=float(
                        raw.get("current_interval_min")
                        or self._cfg.alert_initial_interval_minutes
                    ),
                    alert_count=int(raw.get("alert_count") or 0),
                )
            except Exception:  # noqa: BLE001
                logger.warning("Failed to read state, starting fresh")
        return AlertState(
            last_alert_at=None,
            current_interval_min=self._cfg.alert_initial_interval_minutes,
            alert_count=0,
        )

    def _save_state(self) -> None:
        data: dict = {
            "last_alert_at": self._state.last_alert_at,
            "current_interval_min": self._state.current_interval_min,
            "alert_count": self._state.alert_count,
        }
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(data))

    async def _fetch(self) -> BalanceInfo:
        async with RunpodClient(self._cfg.runpod_api_key) as client:
            info = await client.fetch_balance()
            return info

    @staticmethod
    def _format_time_remaining(hours_left: float) -> str:
        if math.isinf(hours_left):
            return "∞"

        days = int(hours_left // 24)
        remaining_hours = hours_left % 24

        if days > 0:
            return f"{days}d {remaining_hours:.1f}h"
        return f"{remaining_hours:.1f}h"

    @staticmethod
    def _format_eta(hours_left: float) -> str:
        if math.isinf(hours_left):
            return "∞"
        dt = datetime.now(tz=UTC) + timedelta(hours=hours_left)
        return dt.strftime("%Y-%m-%d %H:%M UTC")

    def _format_hours_left(self, balance: float, spend_per_hr: float) -> float:
        if spend_per_hr <= 0:
            return math.inf
        return (balance - self._cfg.pod_stop_balance_usd) / spend_per_hr

    async def send_daily(self) -> None:
        info = await self._fetch()
        balance = info.client_balance
        spend = info.current_spend_per_hr
        hours_left = self._format_hours_left(balance, spend)
        time_remaining = self._format_time_remaining(hours_left)
        eta = self._format_eta(hours_left)
        text = DAILY_BALANCE_TEMPLATE.format(
            balance=balance,
            spend=spend,
            pod_stop_balance=self._cfg.pod_stop_balance_usd,
            time_remaining=time_remaining,
            eta=eta,
        )
        try:
            await self._sender.send_message(text, disable_notification=True)
            logger.info("Sent daily balance report")
        except Exception as e:  # noqa: BLE001
            logger.error("Failed to send daily balance report: %s", e)

    async def poll_and_alert(self) -> None:
        info = await self._fetch()
        balance = info.client_balance
        spend = info.current_spend_per_hr
        hours_left = self._format_hours_left(balance, spend)

        threshold = self._cfg.low_balance_usd
        hysteresis = self._cfg.alert_hysteresis_usd

        # Special case: spend is zero (pods stopped)
        if math.isinf(hours_left):
            # If balance is low/negative and spend is zero, pods were shut down
            if balance < threshold:
                should_send = False
                if self._state.last_alert_at is None:
                    should_send = True
                else:
                    elapsed_min = (_now_ts() - self._state.last_alert_at) / 60.0
                    if elapsed_min >= self._state.current_interval_min:
                        should_send = True

                if should_send:
                    text = BALANCE_DEPLETED_TEMPLATE.format(
                        balance=balance,
                        threshold=threshold,
                        pod_stop_balance=self._cfg.pod_stop_balance_usd,
                    )
                    try:
                        await self._sender.send_message(text)
                        logger.info("Sent balance depleted alert")
                        # Update state only after successful send
                        self._state.last_alert_at = _now_ts()
                        # decrease the interval multiplicatively down to min interval
                        self._state.current_interval_min = max(
                            self._cfg.alert_minimum_interval_minutes,
                            self._state.current_interval_min
                            * self._cfg.alert_decay_factor,
                        )
                        self._state.alert_count += 1
                        self._save_state()
                    except Exception as e:  # noqa: BLE001
                        logger.error("Failed to send balance depleted alert: %s", e)
                        # State is NOT updated - will retry on next poll
            elif balance >= threshold + hysteresis:
                # Balance recovered (recharged) but pods not yet running
                if self._state.alert_count > 0:
                    text = BALANCE_RECOVERED_TEMPLATE.format(
                        balance=balance, recovery_threshold=threshold + hysteresis
                    )
                    try:
                        await self._sender.send_message(text, disable_notification=True)
                        logger.info("Sent balance recovered message")
                    except Exception as e:  # noqa: BLE001
                        logger.error("Failed to send balance recovered message: %s", e)
                # Reset state regardless of message delivery
                self._state = AlertState(
                    last_alert_at=None,
                    current_interval_min=self._cfg.alert_initial_interval_minutes,
                    alert_count=0,
                )
                self._save_state()
            # If balance is OK and spend is zero, just skip (no active pods)
            return

        if balance < threshold:
            should_send = False
            if self._state.last_alert_at is None:
                should_send = True
            else:
                elapsed_min = (_now_ts() - self._state.last_alert_at) / 60.0
                if elapsed_min >= self._state.current_interval_min:
                    should_send = True

            if should_send:
                time_remaining = self._format_time_remaining(hours_left)
                eta = self._format_eta(hours_left)
                text = LOW_BALANCE_ALERT_TEMPLATE.format(
                    balance=balance,
                    threshold=threshold,
                    spend=spend,
                    pod_stop_balance=self._cfg.pod_stop_balance_usd,
                    time_remaining=time_remaining,
                    eta=eta,
                )
                try:
                    await self._sender.send_message(text)
                    logger.info("Sent low balance alert")
                    # Update state only after successful send
                    self._state.last_alert_at = _now_ts()
                    # decrease the interval multiplicatively down to min interval
                    self._state.current_interval_min = max(
                        self._cfg.alert_minimum_interval_minutes,
                        self._state.current_interval_min * self._cfg.alert_decay_factor,
                    )
                    self._state.alert_count += 1
                    self._save_state()
                except Exception as e:  # noqa: BLE001
                    logger.error("Failed to send low balance alert: %s", e)
                    # State is NOT updated - will retry on next poll
        elif balance >= threshold + hysteresis:
            # reset
            if self._state.alert_count > 0:
                text = BALANCE_RECOVERED_TEMPLATE.format(
                    balance=balance, recovery_threshold=threshold + hysteresis
                )
                try:
                    await self._sender.send_message(text, disable_notification=True)
                    logger.info("Sent balance recovered message")
                except Exception as e:  # noqa: BLE001
                    logger.error("Failed to send balance recovered message: %s", e)
            # Reset state regardless of message delivery
            self._state = AlertState(
                last_alert_at=None,
                current_interval_min=self._cfg.alert_initial_interval_minutes,
                alert_count=0,
            )
            self._save_state()

    def schedule(self, scheduler: AsyncIOScheduler) -> None:
        tz = self._cfg.get_daily_notify_tz()
        notify_time = self._cfg.get_daily_notify_time()
        cron = CronTrigger(
            hour=notify_time.hour,
            minute=notify_time.minute,
            timezone=tz,
        )
        scheduler.add_job(self.send_daily, cron, id="daily_balance")
        scheduler.add_job(
            self.poll_and_alert,
            "interval",
            seconds=self._cfg.poll_interval_sec,
            id="poll_alerts",
        )
