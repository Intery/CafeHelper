import logging

logger = logging.getLogger(__name__)

async def setup(bot):
    from .cog import VoiceFixCog
    await bot.add_cog(VoiceFixCog(bot))
