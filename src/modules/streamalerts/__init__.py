import logging
from meta import LionBot

logger = logging.getLogger(__name__)

async def setup(bot: LionBot):
    from .cog import AlertCog
    await bot.add_cog(AlertCog(bot))
