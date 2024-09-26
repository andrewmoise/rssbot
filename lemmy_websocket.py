import asyncio
import websockets
import json
from typing import List, Set, Dict, Any, Optional

class LemmyWebSocket:
    def __init__(self, server: str, jwt_token: str):
        self.server = server
        self.jwt_token = jwt_token
        self.uri = f"wss://{server}/api/v3/ws"
        self.websocket = None
        self.subscribed_events = set()
        self.connection_task = None
        self.message_queue = asyncio.Queue()
        self.connected = asyncio.Event()

    async def connect(self):
        self.connection_task = asyncio.create_task(self._maintain_connection())
        await self.connected.wait()  # Wait until the connection is established

    async def _maintain_connection(self):
        while True:
            try:
                async with websockets.connect(self.uri) as ws:
                    self.websocket = ws
                    await self._authenticate()
                    await self._resubscribe()
                    self.connected.set()  # Signal that the connection is established
                    await self._handle_messages()
            except websockets.exceptions.ConnectionClosed:
                print(f"Connection to {self.server} closed. Reconnecting...")
                self.connected.clear()  # Connection lost, clear the event
                await asyncio.sleep(5)

    async def _authenticate(self):
        await self.websocket.send(json.dumps({
            "op": "UserJoin",
            "data": {"auth": self.jwt_token}
        }))

    async def _resubscribe(self):
        for event_type in self.subscribed_events:
            await self.subscribe(event_type)

    async def subscribe(self, event_type: str):
        self.subscribed_events.add(event_type)
        if self.websocket:
            await self.websocket.send(json.dumps({
                "op": f"{event_type}Subscribe",
                "data": {}
            }))

    async def _handle_messages(self):
        while True:
            message = await self.websocket.recv()
            await self.message_queue.put(json.loads(message))

    async def get_message(self):
        return await self.message_queue.get()

async def wait_for_lemmy_events(
    websockets: List[LemmyWebSocket],
    event_types: Set[str] = None,
    timeout: Optional[float] = None
) -> Optional[Dict[str, Any]]:
    async def get_filtered_message(ws):
        while True:
            message = await ws.get_message()
            if event_types is None or message['op'] in event_types:
                return ws, message

    tasks = [asyncio.create_task(get_filtered_message(ws)) for ws in websockets]
    try:
        done, pending = await asyncio.wait(tasks, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if done:
            ws, event = await done.pop()
            return {
                "server": ws.server,
                "event": event
            }
    except asyncio.TimeoutError:
        return None
    return None