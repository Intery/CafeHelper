this_package = 'modules'

active_discord = [
    '.sysadmin',
    '.config',
    '.user_config',
    '.skins',
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
    '.blanket',
    '.voicefix',
    '.sponsors',
    '.topgg',
    '.premium',
    '.streamalerts',
    '.test',
]

active_twitch = [
    '.nowdoing',
    '.shoutouts',
    '.counters',
    '.tagstrings',
]


def prepare(bot):
    for ext in active_twitch:
        bot.load_module(this_package + ext)

async def setup(bot):
    for ext in active_discord:
        await bot.load_extension(ext, package=this_package)
