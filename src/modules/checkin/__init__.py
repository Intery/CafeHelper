import logging

logger = logging.getLogger(__name__)

from .cog import CheckinCog

async def setup(bot):
    await bot.add_cog(CheckinCog(bot))
