from abc import ABC
from collections import defaultdict
import json
from typing import Any
import logging

import websockets


logger = logging.getLogger(__name__)



class Channel(ABC):
    """
    A channel is a stateful connection handler for a group of connected websockets.
    """
    name = "Root Channel"

    def __init__(self, **kwargs):
        self.connections = set()

    @property
    def empty(self):
        return not self.connections

    async def on_connection(self, websocket: websockets.WebSocketServerProtocol, event: dict[str, Any]):
        logger.info(f"Channel '{self.name}' attached new connection {websocket=} {event=}")
        self.connections.add(websocket)

    async def del_connection(self, websocket: websockets.WebSocketServerProtocol):
        logger.info(f"Channel '{self.name}' dropped connection {websocket=}")
        self.connections.discard(websocket)

    async def handle_message(self, websocket: websockets.WebSocketServerProtocol, message):
        raise NotImplementedError

    async def send_event(self, event, websocket=None):
        message = json.dumps(event)
        if not websocket:
            for ws in self.connections:
                await ws.send(message)
        else:
            await websocket.send(message)

channels = {}

def register_channel(name, channel: Channel):
    channels[name] = channel


async def root_handler(websocket: websockets.WebSocketServerProtocol):
    message = await websocket.recv()
    event = json.loads(message)

    if event.get('type', None) != 'init':
        raise ValueError("Received Websocket connection with no init.")

    if (channel_name := event.get('channel', None)) not in channels:
        raise ValueError(f"Received Init for unhandled channel {channel_name=}")
    channel = channels[channel_name]

    try:
        await channel.on_connection(websocket, event)
        async for message in websocket:
            await channel.handle_message(websocket, message)
    finally:
        await channel.del_connection(websocket)
