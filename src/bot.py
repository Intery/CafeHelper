import asyncio
from contextlib import AsyncExitStack
import logging
import websockets

import aiohttp
import discord
from discord.ext import commands

from meta import CrocBot, LionBot, conf, sharding, appname, shard_talk, sockets, args
from meta.app import shardname
from meta.logger import log_context, log_action_stack, setup_main_logger
from meta.context import ctx_bot
from meta.monitor import ComponentMonitor, StatusLevel, ComponentStatus, SystemMonitor

from data import Database

from babel.translator import LeoBabel, ctx_translator

from constants import DATA_VERSION


for name in conf.config.options('LOGGING_LEVELS', no_defaults=True):
    logging.getLogger(name).setLevel(conf.logging_levels[name])


logging_queue = setup_main_logger()


logger = logging.getLogger(__name__)

db = Database(conf.data['args'])


async def _data_monitor() -> ComponentStatus:
    """
    Component monitor callback for the database.
    """
    data = {
        'stats': str(db.pool.get_stats())
    }
    if not db.pool._opened:
        level = StatusLevel.WAITING
        info = "(WAITING) Database Pool is not opened."
    elif db.pool._closed:
        level = StatusLevel.ERRORED
        info = "(ERROR) Database Pool is closed."
    else:
        level = StatusLevel.OKAY
        info = "(OK) Database Pool statistics: {stats}"
    return ComponentStatus(level, info, info, data)


async def main():
    log_action_stack.set(("Initialising",))
    logger.info("Initialising StudyLion")

    intents = discord.Intents.all()
    intents.members = True
    intents.message_content = True
    intents.presences = False

    system_monitor = SystemMonitor()

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(db.open())

        version = await db.version()
        if version.version != DATA_VERSION:
            error = f"Data model version is {version}, required version is {DATA_VERSION}! Please migrate."
            logger.critical(error)
            raise RuntimeError(error)
        system_monitor.add_component(ComponentMonitor('Database', _data_monitor))

        translator = LeoBabel()
        ctx_translator.set(translator)

        session = await stack.enter_async_context(aiohttp.ClientSession())
        await stack.enter_async_context(
            websockets.serve(sockets.root_handler, '', conf.wserver['port'])
        )

        crocbot = CrocBot(
            config=conf,
            data=db,
            prefix='!',
            initial_channels=conf.croccy.getlist('initial_channels'),
            token=conf.croccy['token'],
        )

        lionbot = await stack.enter_async_context(
            LionBot(
                command_prefix='!',
                intents=intents,
                appname=appname,
                shardname=shardname,
                db=db,
                config=conf,
                initial_extensions=[
                    'utils', 'core', 'analytics',
                    'modules',
                    'babel',
                    'tracking.voice', 'tracking.text',
                    ],
                web_client=session,
                app_ipc=shard_talk,
                testing_guilds=conf.bot.getintlist('admin_guilds'),
                shard_id=sharding.shard_number,
                shard_count=sharding.shard_count,
                help_command=None,
                proxy=conf.bot.get('proxy', None),
                translator=translator,
                chunk_guilds_at_startup=False,
                system_monitor=system_monitor,
                crocbot=crocbot,
            )
        )

        crocstart = asyncio.create_task(start_croccy(crocbot))
        lionstart = asyncio.create_task(start_lion(lionbot))
        await asyncio.wait((crocstart, lionstart), return_when=asyncio.FIRST_COMPLETED)
        # crocstart.cancel()
        # lionstart.cancel()

async def start_lion(lionbot):
    ctx_bot.set(lionbot)
    try:
        log_context.set(f"APP: {appname}")
        logger.info("StudyLion initialised, starting!", extra={'action': 'Starting'})
        await lionbot.start(conf.bot['TOKEN'])
    except asyncio.CancelledError:
        log_context.set(f"APP: {appname}")
        logger.info("StudyLion closed, shutting down.", extra={'action': "Shutting Down"}, exc_info=True)

async def start_croccy(crocbot):
    try:
        log_context.set(f"APP: {appname}-croccy")
        logger.info("Starting Twitch bot.", extra={'action': 'Starting'})
        await crocbot.start()
    except asyncio.CancelledError:
        logger.info("Croccybot shutting down gracefully.")
    except Exception:
        logger.exception("Croccybot shutting down ungracefully.")
    finally:
        await crocbot.close()


def _main():
    from signal import SIGINT, SIGTERM

    loop = asyncio.get_event_loop()
    main_task = asyncio.ensure_future(main())
    for signal in [SIGINT, SIGTERM]:
        loop.add_signal_handler(signal, main_task.cancel)
    try:
        loop.run_until_complete(main_task)
    finally:
        loop.close()
        logging.shutdown()


if __name__ == '__main__':
    _main()
