import logging

logger = logging.getLogger(__name__)

from .cog import TagCog

async def setup(bot):
    await bot.add_cog(TagCog(bot))
