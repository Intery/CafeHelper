import logging

logger = logging.getLogger(__name__)

async def setup(bot):
    from .cog import VoiceRoleCog
    await bot.add_cog(VoiceRoleCog(bot))
