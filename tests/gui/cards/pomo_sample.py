import asyncio
import datetime as dt
from gui.cards import BreakTimerCard, FocusTimerCard


async def get_card():
    card = await BreakTimerCard.generate_sample()
    with open('output/break_timer_sample.png', 'wb') as image_file:
        image_file.write(card.fp.read())
    card = await FocusTimerCard.generate_sample()
    with open('output/focus_timer_sample.png', 'wb') as image_file:
        image_file.write(card.fp.read())

if __name__ == '__main__':
    asyncio.run(get_card())
