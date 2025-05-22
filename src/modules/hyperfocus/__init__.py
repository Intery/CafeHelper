import logging

logger = logging.getLogger(__name__)

from .cog import HyperFocusCog 

async def setup(bot):
    await bot.add_cog(HyperFocusCog(bot))
