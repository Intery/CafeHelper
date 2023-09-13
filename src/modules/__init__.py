this_package = 'modules'

active = [
    '.sysadmin',
    '.config',
    '.user_config',
    '.schedule',
    '.economy',
    '.ranks',
    '.reminders',
    '.shop',
    '.statistics',
    '.pomodoro',
    '.rooms',
    '.tasklist',
    '.rolemenus',
    '.member_admin',
    '.moderation',
    '.video_channels',
    '.meta',
    '.test',
]


async def setup(bot):
    for ext in active:
        await bot.load_extension(ext, package=this_package)
