"""
Testing client for the twitch AuthServer.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.getcwd()))
sys.path.insert(0, os.path.join(os.getcwd(), "src"))

import asyncio
import aiohttp
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.type import AuthScope

from meta.config import conf


URI = "http://localhost:3000/twiauth/confirm"
TARGET_SCOPE = [AuthScope.CHAT_EDIT, AuthScope.CHAT_READ]

async def main():
    # Load in client id and secret
    twitch = await Twitch(conf.twitch['app_id'], conf.twitch['app_secret'])
    auth = UserAuthenticator(twitch, TARGET_SCOPE, url=URI)
    url = auth.return_auth_url()

    # Post url to user
    print(url)

    # Send listen request to server
    # Wait for listen request
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect('http://localhost:3000/twiauth/listen') as ws:
            await ws.send_json({'state': auth.state})
            result = await ws.receive_json()

    # Hopefully get back code, print the response
    print(f"Recieved: {result}")

    # Authorise with code and client details
    tokens = await auth.authenticate(user_token=result['code'])
    if tokens:
        token, refresh = tokens
        await twitch.set_user_authentication(token, TARGET_SCOPE, refresh)
        print(f"Authorised!")


if __name__ == '__main__':
    asyncio.run(main())
