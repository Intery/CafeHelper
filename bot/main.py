import asyncio
import logging

import discord
from discord.ext import commands

from meta import LionBot, conf, sharding
from meta.logger import log_context, log_action

from data import Database

from constants import DATA_VERSION

# from data import tables

# Note: This MUST be imported after core, due to table definition orders
# from settings import AppSettings

# Load and attach app specific data
if sharding.sharded:
    appname = f"{conf.data['appid']}_{sharding.shard_count}_{sharding.shard_number}"
else:
    appname = conf.data['appid']
log_context.set(f"APP: {appname}")

# client.appdata = core.data.meta.fetch_or_create(appname)

# client.data = tables

# client.settings = AppSettings(conf.bot['data_appid'])

# Initialise all modules
# client.initialise_modules()

for name in conf.config.options('LOGGING_LEVELS', no_defaults=True):
    logging.getLogger(name).setLevel(conf.logging_levels[name])

logger = logging.getLogger(__name__)

db = Database(conf.data['args'])


async def main():
    log_action.set("Initialising")
    logger.info("Initialising StudyLion")

    intents = discord.Intents.all()
    intents.members = True
    intents.message_content = True

    async with await db.connect():
        version = await db.version()
        if version.version != DATA_VERSION:
            error = f"Data model version is {version}, required version is {DATA_VERSION}! Please migrate."
            logger.critical(error)
            raise RuntimeError(error)
        async with LionBot(
            command_prefix=commands.when_mentioned,
            intents=intents,
            appname=appname,
            db=db,
            config=conf,
            initial_extensions=['modules'],
            web_client=None,
            testing_guilds=[889875661848723456]
        ) as lionbot:
            log_action.set("Launching")
            await lionbot.start(conf.bot['TOKEN'])

asyncio.run(main())
