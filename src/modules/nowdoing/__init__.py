import logging

logger = logging.getLogger(__name__)

from .cog import NowDoingCog

async def setup(bot):
    await bot.add_cog(NowDoingCog(bot))
