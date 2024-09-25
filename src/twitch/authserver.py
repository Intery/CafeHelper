import logging
import uuid
import asyncio
from contextvars import ContextVar

import aiohttp
from aiohttp import web

logger = logging.getLogger(__name__)
reqid: ContextVar[str] = ContextVar('reqid', default='ROOT')


class AuthServer:
    def __init__(self):
        self.listeners = {}

    async def handle_twitch_callback(self, request: web.Request) -> web.StreamResponse:
        args = request.query
        if 'state' not in args:
            raise web.HTTPBadRequest(text="No state provided.")
        if args['state'] not in self.listeners:
            raise web.HTTPBadRequest(text="Invalid state.")
        self.listeners[args['state']].set_result(dict(args))
        return web.Response(text="Authorisation complete! You may now close this page and return to the application.")

    async def handle_listen_request(self, request: web.Request) -> web.StreamResponse:
        _reqid = str(uuid.uuid1())
        reqid.set(_reqid)

        logger.debug(f"[reqid: {_reqid}] Received websocket listen connection: {request!r}")

        ws = web.WebSocketResponse()
        await ws.prepare(request)

        # Get the listen request data
        try:
            listen_req = await ws.receive_json(timeout=60)
            logger.info(f"[reqid: {_reqid}] Received websocket listen request: {request}")
            if 'state' not in listen_req:
                logger.error(f"[reqid: {_reqid}] Websocket listen request is missing state, cancelling.")
                raise web.HTTPBadRequest(text="Listen request must include state string.")
            elif listen_req['state'] in self.listeners:
                logger.error(f"[reqid: {_reqid}] Websocket listen request with duplicate state, cancelling.")
                raise web.HTTPBadRequest(text="Invalid state string.")
        except ValueError:
            logger.exception(f"[reqid: {_reqid}] Listen request could not be parsed to JSON.")
            raise web.HTTPBadRequest(text="Request must be a JSON formatted string.")
        except TypeError:
            logger.exception(f"[reqid: {_reqid}] Listen request was binary not JSON.")
            raise web.HTTPBadRequest(text="Request must be a JSON formatted string.")
        except asyncio.TimeoutError:
            logger.info(f"[reqid: {_reqid}] Timed out waiting for listen request data.")
            raise web.HTTPRequestTimeout(text="Request must be a JSON formatted string.")
        except Exception:
            logger.exception(f"[reqid: {_reqid}] Unknown exception.")
            raise web.HTTPInternalServerError()

        try:
            fut = self.listeners[listen_req['state']] = asyncio.Future()
            result = await asyncio.wait_for(fut, timeout=120)
        except asyncio.TimeoutError:
            logger.info(f"[reqid: {_reqid}] Timed out waiting for auth callback from Twitch, closing.")
            raise web.HTTPGatewayTimeout(text="Did not receive an authorisation code from Twitch in time.")
        finally:
            self.listeners.pop(listen_req['state'], None)

        logger.debug(f"[reqid: {_reqid}] Responding with auth result {result}.")
        await ws.send_json(result)
        await ws.close()
        logger.debug(f"[reqid: {_reqid}] Request completed handling.")

        return ws

def main(argv):
    app = web.Application()
    server = AuthServer()
    app.router.add_get("/twiauth/confirm", server.handle_twitch_callback)
    app.router.add_get("/twiauth/listen", server.handle_listen_request)

    logger.info("App setup and configured. Starting now.")
    web.run_app(app, port=int(argv[1]) if len(argv) > 1 else 8080)


if __name__ == '__main__':
    import sys
    main(sys.argv)
