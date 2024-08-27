import logging

logger = logging.getLogger(__name__)

from .cog import CounterCog

def prepare(bot):
    bot.add_cog(CounterCog(bot))

async def setup(bot):
    from .lion_cog import CounterCog

    await bot.add_cog(CounterCog(bot))
