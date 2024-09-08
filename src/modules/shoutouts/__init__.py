import logging

logger = logging.getLogger(__name__)

from .cog import ShoutoutCog

async def setup(bot):
    await bot.add_cog(ShoutoutCog(bot))
