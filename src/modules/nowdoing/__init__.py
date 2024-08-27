import logging

logger = logging.getLogger(__name__)

from .cog import NowDoingCog

def prepare(bot):
    logger.info("Preparing the nowdoing module.")
    bot.add_cog(NowDoingCog(bot))
