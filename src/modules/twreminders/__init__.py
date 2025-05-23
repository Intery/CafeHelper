import logging

logger = logging.getLogger(__name__)

from .cog import ReminderCog

async def setup(bot):
    bot.add_cog(ReminderCog(bot))
