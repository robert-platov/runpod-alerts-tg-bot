from __future__ import annotations

import logging
import math
from datetime import UTC, datetime, timedelta

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

logger = logging.getLogger(__name__)


BALANCE_COMMAND_TEMPLATE = (
    "💰 <b>RunPod Balance</b>\n\n"
    "💵 Balance: ${balance:,.2f}\n"
    "⚡️ Spend rate: ${spend:,.2f}/hr\n"
    "⏳ Time remaining: ~{time_remaining}\n"
    "🕐 Will run out at: {eta}"
)

BALANCE_COMMAND_INFINITE_TEMPLATE = (
    "💰 <b>RunPod Balance</b>\n\n"
    "💵 Balance: ${balance:,.2f}\n"
    "⚡️ Spend rate: $0.00/hr\n"
    "⏳ Time remaining: ∞"
)


def _format_time_remaining(hours_left: float) -> str:
    if math.isinf(hours_left):
        return "∞"

    days = int(hours_left // 24)
    remaining_hours = hours_left % 24

    if days > 0:
        return f"{days}d {remaining_hours:.1f}h"
    return f"{remaining_hours:.1f}h"


def _format_eta(hours_left: float) -> str:
    if math.isinf(hours_left):
        return "∞"
    dt = datetime.now(tz=UTC) + timedelta(hours=hours_left)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


class TelegramSender:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot = Bot(token=bot_token)
        self._chat_id = chat_id

    async def send_message(self, text: str, disable_notification: bool = False) -> None:
        await self._bot.send_message(
            chat_id=self._chat_id,
            text=text,
            parse_mode="HTML",
            disable_notification=disable_notification,
        )


class TelegramApp:
    def __init__(self, bot: Bot, allowed_chat_id: str, get_balance_cb) -> None:
        self._bot = bot
        self._allowed_chat_id = allowed_chat_id
        self._dp = Dispatcher()
        self._register_handlers(get_balance_cb)

    def _check_chat(self, message: Message) -> bool:
        return str(message.chat.id) == str(self._allowed_chat_id)

    def _register_handlers(self, get_balance_cb) -> None:
        @self._dp.message(Command("balance"))
        async def balance_handler(message: Message) -> None:
            if not self._check_chat(message):
                return
            try:
                info = await get_balance_cb()
                balance = info.client_balance
                spend = info.current_spend_per_hr
                if spend <= 0:
                    text = BALANCE_COMMAND_INFINITE_TEMPLATE.format(balance=balance)
                else:
                    hours_left = balance / spend
                    time_remaining = _format_time_remaining(hours_left)
                    eta = _format_eta(hours_left)
                    text = BALANCE_COMMAND_TEMPLATE.format(
                        balance=balance,
                        spend=spend,
                        time_remaining=time_remaining,
                        eta=eta,
                    )
                await self._bot.send_message(
                    message.chat.id,
                    text,
                    parse_mode="HTML",
                )
            except Exception as e:  # noqa: BLE001
                logger.error("Failed to handle /balance command: %s", e)
                await self._bot.send_message(
                    message.chat.id,
                    f"❌ Error fetching balance: {e}",
                    parse_mode="HTML",
                )

    async def start_polling(self) -> None:
        await self._dp.start_polling(self._bot)

    async def register_commands(self) -> None:
        try:
            from aiogram.types import BotCommand

            commands = [
                BotCommand(
                    command="balance", description="Show RunPod balance and hours left"
                ),
            ]
            await self._bot.set_my_commands(commands)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to set bot commands: %s", e)
