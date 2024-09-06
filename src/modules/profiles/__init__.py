import logging

logger = logging.getLogger(__name__)

from .cog import ProfileCog

async def setup(bot):
    await bot.add_cog(ProfileCog(bot))
