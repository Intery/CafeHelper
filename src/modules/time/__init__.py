import logging

logger = logging.getLogger(__name__)

from .cog import TimeCog

async def setup(bot):
    await bot.add_cog(TimeCog(bot))
