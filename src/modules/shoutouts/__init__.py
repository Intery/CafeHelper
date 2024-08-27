import logging

logger = logging.getLogger(__name__)

from .cog import ShoutoutCog

def prepare(bot):
    bot.add_cog(ShoutoutCog(bot))
