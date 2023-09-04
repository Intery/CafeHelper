from babel.translator import LocalBabel

babel = LocalBabel('blanket')


async def setup(bot):
    from .cog import BlanketCog

    await bot.add_cog(BlanketCog(bot))
