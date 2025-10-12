import asyncio
import logging
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from runpod_alerts_tg_bot.runpod_client import BalanceInfo

from .alerts_service import AlertsService
from .config import load_config
from .logging_setup import setup_logging
from .telegram_bot import TelegramApp, TelegramSender


def main() -> None:
    cfg = load_config()
    setup_logging(cfg.log_level)
    logger = logging.getLogger("run")
    logger.info("Starting RunPod alerts bot")

    sender = TelegramSender(
        bot_token=cfg.telegram_bot_token, chat_id=cfg.telegram_chat_id
    )
    service = AlertsService(cfg, sender, state_path=Path("data/state.json"))

    async def get_balance_cb() -> BalanceInfo:
        return await service._fetch()

    from aiogram import Bot

    bot = Bot(token=cfg.telegram_bot_token)
    app = TelegramApp(
        bot,
        allowed_chat_id=cfg.telegram_chat_id,
        get_balance_cb=get_balance_cb,
    )

    async def run_all() -> None:
        scheduler = AsyncIOScheduler()
        service.schedule(scheduler)
        scheduler.start()

        await app.register_commands()
        try:
            await app.start_polling()
        finally:
            scheduler.shutdown(wait=False)

    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
