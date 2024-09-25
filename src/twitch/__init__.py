import logging

logger = logging.getLogger(__name__)

from .cog import TwitchAuthCog

async def setup(bot):
    await bot.add_cog(TwitchAuthCog(bot))

