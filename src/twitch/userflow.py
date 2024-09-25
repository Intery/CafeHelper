from typing import Optional
import datetime as dt

from aiohttp import web

import aiohttp
from twitchAPI.twitch import Twitch
from twitchAPI.oauth import UserAuthenticator, validate_token
from twitchAPI.type import AuthType
from twitchio.client import asyncio

from meta.errors import SafeCancellation
from utils.lib import utc_now
from .data import TwitchAuthData
from . import logger

class UserAuthFlow:
    auth: UserAuthenticator
    data: TwitchAuthData
    auth_ws: str
    
    def __init__(self, data, auth, auth_ws):
        self.auth = auth
        self.data = data
        self.auth_ws = auth_ws

        self._setup_done = asyncio.Event()
        self._comm_task: Optional[asyncio.Task] = None

    async def setup(self):
        """
        Establishes websocket connection to the AuthServer,
        and requests listening for the given state.
        Propagates any exceptions that occur during connection setup.
        """
        if self._setup_done.is_set():
            raise ValueError("UserAuthFlow is already set up.")
        self._comm_task = asyncio.create_task(self._communicate(), name='UserAuthFlow-communicate')
        await self._setup_done.wait()
        if self._comm_task.done() and (exc := self._comm_task.exception()):
            raise exc

    async def _communicate(self):
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(self.auth_ws) as ws:
                await ws.send_json({'state': self.auth.state})
                self._setup_done.set()
                return await ws.receive_json()

    async def run(self):
        if not self._setup_done.is_set():
            raise ValueError("Cannot run UserAuthFlow before setup.")
        if self._comm_task is None:
            raise ValueError("UserAuthFlow running with no comm task! This should be impossible.")

        result = await self._comm_task
        if result.get('error', None):
            # TODO Custom auth errors
            # This is only documented to occure when the user denies the auth
            raise SafeCancellation(f"Could not authenticate user! Reason: {result['error_description']}")

        if result.get('state', None) != self.auth.state:
            # This should never happen unless the authserver has its wires crossed somehow,
            # or the connection has been tampered with.
            # TODO: Consider terminating for safety in this case? Or at least refusing more auth requests.
            logger.critical(
                f"Received {result} while waiting for state {self.auth.state!r}. SOMETHING IS WRONG."
            )
            raise SafeCancellation(
                "Could not complete authentication! Invalid server response."
            )

        # Now assume result has a valid code 
        # Exchange code for an auth token and a refresh token
        # Ignore type here, authenticate returns None if a callback function has been given.
        token, refresh = await self.auth.authenticate(user_token=result['code'])  # type: ignore

        # Fetch the associated userid and basic info
        v_result = await validate_token(token)
        userid = v_result['user_id']
        expiry = utc_now() + dt.timedelta(seconds=v_result['expires_in'])

        # Save auth data
        return await self.data.UserAuthRow.update_user_auth(
            userid=userid, token=token, refresh=refresh,
            expires_at=expiry, obtained_at=utc_now(),
            scopes=[scope.value for scope in self.auth.scopes]
        )
