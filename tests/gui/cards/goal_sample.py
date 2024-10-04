import asyncio
import datetime as dt
from gui.cards import WeeklyGoalCard


async def get_card():
    card = await WeeklyGoalCard.generate_sample()
    with open('output/weekly-sample.png', 'wb') as image_file:
        image_file.write(card.fp.read())

if __name__ == '__main__':
    asyncio.run(get_card())
