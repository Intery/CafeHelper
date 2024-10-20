import itertools
from typing import Optional
from datetime import timedelta, datetime
import calendar

from meta import LionBot
from gui.cards import WeeklyStatsCard, MonthlyStatsCard
from gui.base import CardMode
from modules.profiles.profile import UserProfile
from babel import LocalBabel
from modules.statistics.lib import apply_month_offset

from ..data import CounterData

babel = LocalBabel('counters')
_ = babel._



async def counter_monthly_card(
    bot: LionBot,
    userid: int,
    profile: UserProfile,
    counter: CounterData.Counter,
    guildid: int,
    offset: int,
):
    cog = bot.get_cog('CounterCog')
    data: CounterData = cog.data

    if guildid:
        lion = await bot.core.lions.fetch_member(guildid, userid)
        user = await lion.fetch_member()
    else:
        lion = await bot.core.lions.fetch_user(userid)
        user = await bot.fetch_user(userid)
    today = lion.today

    month_start = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    target = apply_month_offset(month_start, offset)
    target_end = (target + timedelta(days=40)).replace(day=1, hour=0, minute=0) - timedelta(days=1)

    months = [target]
    for i in range(0, 3):
        months.append((months[-1] - timedelta(days=1)).replace(day=1))
    months.reverse()

    rows = await data.CounterEntry.fetch_where(
        data.CounterEntry.counterid == counter.counterid,
        data.CounterEntry.userid == profile.profileid,
        data.CounterEntry.created_at <= target_end,
        data.CounterEntry.created_at >= months[0],
    )

    events = [(row.created_at, row.value) for row in rows]

    month_lengths = [
        (calendar.monthrange(month.year, month.month)[1]) for month in months
    ]
    month_dates = []
    for month, length in zip(months, month_lengths):
        for day in range(1, length + 1):
            month_dates.append(datetime(month.year, month.month, day, tzinfo=month.tzinfo))

    monthly_flat = events_to_dayfreq(events, month_dates)
    print(monthly_flat)
    
    monthly = []
    i = 0
    for length in month_lengths:
        this_month = monthly_flat[i : i+length]
        i += length
        monthly.append(this_month)


    skin = await bot.get_cog('CustomSkinCog').get_skinargs_for(
        guildid, userid, MonthlyStatsCard.card_id
    )
    skin |= {
        'title_text': f"{counter.name.upper()}",
        'this_month_text': f"THIS MONTH: {{amount}} {counter.name.upper()}",
        'last_month_text': f"LAST MONTH: {{amount}} {counter.name.upper()}"
    }

    if user:
        username = (user.display_name, '')
    else:
        username = (await profile.get_name(), '')


    card = MonthlyStatsCard(
        user=username,
        timezone=str(lion.timezone),
        now=lion.now.timestamp(),
        month=int(target.timestamp()),
        monthly=monthly,
        current_streak=-1,
        longest_streak=-1,
        skin=skin | {'mode': CardMode.TEXT}
    )
    return card




async def counter_weekly_card(
    bot: LionBot,
    userid: int,
    profile: UserProfile,
    counter: CounterData.Counter,
    guildid: int,
    offset: int,
):
    cog = bot.get_cog('CounterCog')
    data: CounterData = cog.data

    if guildid:
        lion = await bot.core.lions.fetch_member(guildid, userid)
        user = await lion.fetch_member()
    else:
        lion = await bot.core.lions.fetch_user(userid)
        user = await bot.fetch_user(userid)
    today = lion.today
    week_start = today - timedelta(days=today.weekday()) - timedelta(weeks=offset)
    days = [week_start + timedelta(i) for i in range(-7, 8 if offset else (today.weekday() + 2))]

    rows = await data.CounterEntry.fetch_where(
        data.CounterEntry.counterid == counter.counterid,
        data.CounterEntry.userid == profile.profileid,
        data.CounterEntry.created_at <= days[-1],
        data.CounterEntry.created_at >= days[0],
    )

    events = [(row.created_at, row.value) for row in rows]

    daily = events_to_dayfreq(events, days)
    sessions = events_to_sessions(next(zip(*events), []))

    skin = await bot.get_cog('CustomSkinCog').get_skinargs_for(
        guildid, userid, WeeklyStatsCard.card_id
    )
    skin |= {
        'title_text': f"{counter.name.upper()}",
        'this_week_text': f"THIS WEEK: {{amount}} {counter.name.upper()}",
        'last_week_text': f"LAST WEEK: {{amount}} {counter.name.upper()}"
    }

    if user:
        username = (user.display_name, '')
    else:
        username = (await profile.get_name(), '')


    card = WeeklyStatsCard(
        user=username,
        timezone=str(lion.timezone),
        now=lion.now.timestamp(),
        week=week_start.timestamp(),
        daily=tuple(map(int, daily)),
        sessions=sessions,
        skin=skin | {'mode': CardMode.TEXT}
    )
    return card



def events_to_dayfreq(events: list[tuple[datetime, int]], days: list[datetime]) -> list[int]:
    if not days:
        return []

    last_day = 0
    dayts = 0

    daymap = {}
    for day in sorted(days, reverse=True):
        dayts = day.timestamp()
        last_day = last_day or (day + timedelta(days=1)).timestamp()
        daymap[dayts] = 0
    
    first_day = dayts

    for tim, count in events:
        timts = tim.timestamp()
        if not first_day < timts < last_day:
            continue

        for day_start in daymap:
            if timts > day_start:
                daymap[day_start] += count
                break

    return list(reversed(daymap.values()))


def events_to_sessions(event_times: list[datetime]) -> list[tuple[int, int]]:
    """
    Convert a provided list of event times to a session list.
    """
    sessions = []

    session_start = None
    session_end = None

    SESSION_GAP = 60 * 30
    SESSION_RADIUS = 60 * 30

    for time in sorted(event_times):
        if session_start and session_end and (time - session_end).total_seconds() - SESSION_RADIUS > SESSION_GAP:
            session = (int(session_start.timestamp()), int(session_end.timestamp()))
            sessions.append(session)
            session_start = None
            session_end = None
        
        if session_start is None:
            session_start = time - timedelta(seconds=SESSION_RADIUS)
        session_end = time + timedelta(seconds=SESSION_RADIUS)

    if session_start and session_end:
        session = (int(session_start.timestamp()), int(session_end.timestamp()))
        sessions.append(session)

    return sessions
