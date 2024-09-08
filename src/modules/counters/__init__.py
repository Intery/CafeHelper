import logging

logger = logging.getLogger(__name__)

from .cog import CounterCog

async def setup(bot):
    await bot.add_cog(CounterCog(bot))
