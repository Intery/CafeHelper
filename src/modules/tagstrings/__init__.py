import logging

logger = logging.getLogger(__name__)

from .cog import TagCog

def prepare(bot):
    bot.add_cog(TagCog(bot))
