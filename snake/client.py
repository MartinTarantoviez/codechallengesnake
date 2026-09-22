"""
MatchClient: websocket connection, event loop, and per-game log files.
This is everything run.py used to do inline, now testable in isolation
from the actual network (GameLogger and MatchClient.handle_event() take
plain dicts).
"""

import asyncio
import json
import time
import traceback
from pathlib import Path

import websockets

LOGS_DIR = Path(__file__).resolve().parent.parent / 'logs'


class GameLogger:
    def __init__(self, logs_dir=LOGS_DIR):
        self.logs_dir = logs_dir
        self._history = {}

    def log_event(self, game_id, message):
        self._history.setdefault(game_id, []).append('< ' + json.dumps(message))

    def log_action(self, game_id, message):
        self._history.setdefault(game_id, []).append('> ' + json.dumps(message))

    def write(self, game_id):
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            path = self.logs_dir / f"game_{game_id}.log"
            with open(path, "w") as f:
                f.write("\n".join(self._history.get(game_id, [])) + "\n")
            print(f"saved {path}")
        except OSError as e:
            print(f"could not write game log: {e}")

    def forget(self, game_id):
        self._history.pop(game_id, None)


class MatchClient:
    _ERROR_EVENTS = ('error', 'invalid_action', 'invalid_move')

    def __init__(self, bot, logger=None, show_board=False, pending_challenge=None):
        self.bot = bot
        self.logger = logger or GameLogger()
        self.show_board = show_board
        self.pending_challenge = pending_challenge  # username to challenge on connect

    async def _send(self, websocket, action, data):
        message = json.dumps({'action': action, 'data': data})
        print(message)
        await websocket.send(message)

    async def run_forever(self, uri):
        while True:
            try:
                print(f'connection to {uri}')
                async with websockets.connect(uri) as websocket:
                    print('connection READY!')
                    if self.pending_challenge:
                        await self.challenge_user(websocket, self.pending_challenge)
                    await self._play(websocket)
            except KeyboardInterrupt:
                print('Exiting...')
                break
            except Exception as e:
                print(f'connection error! {type(e).__name__}: {e}')
                traceback.print_exc()
                time.sleep(3)

    async def _play(self, websocket):
        while True:
            try:
                raw = await websocket.recv()
                print(f"< {raw}")
                request_data = json.loads(raw)
                await self._handle_event(websocket, request_data)
            except KeyboardInterrupt:
                print('Exiting...')
                break
            except Exception as e:
                print(f'error {e}')
                break  # force reconnect/login again

    async def _handle_event(self, websocket, request_data):
        event = request_data.get('event')
        data = request_data.get('data', {})
        if event in self._ERROR_EVENTS:
            self._handle_rejected(data, request_data)
        elif event == 'game_over':
            self._handle_game_over(data, request_data)
        elif event == 'challenge':
            await self._send(websocket, 'accept_challenge',
                              {'challenge_id': data['challenge_id']})
        elif event == 'your_turn':
            self.logger.log_event(data['game_id'], request_data)
            await self._process_turn(websocket, data)

    def _handle_rejected(self, data, request_data):
        game_id = data.get('game_id')
        if game_id:
            self.logger.log_event(game_id, request_data)
        print(f"!!! SERVER REJECTED ACTION: {request_data}")

    def _handle_game_over(self, data, request_data):
        game_id = data.get('game_id')
        if game_id:
            self.logger.log_event(game_id, request_data)
            self.logger.write(game_id)
            self.bot.forget_game(game_id)
            self.logger.forget(game_id)
        if self.show_board:
            self._print_match_result(data)

    async def challenge_user(self, websocket, username):
        """Send an outgoing challenge to a specific username.

        NOT confirmed against the real server: the rules doc only
        documents the server->client 'challenge' event and the
        'accept_challenge' action that replies to it. It never shows
        the client->server action that *originates* one. This mirrors
        that same shape (action 'challenge', data with the target
        username) as the most likely guess -- try it and check the
        server's response for an 'error'/'invalid_action' event (those
        get logged automatically, see _handle_event above) to confirm
        or correct the exact field name/action name.
        """
        await self._send(websocket, 'challenge', {'opponent': username})

    async def _process_turn(self, websocket, data):
        direction = self.bot.choose_move(data)
        move = {
            'game_id': data['game_id'],
            'turn_token': data['turn_token'],
            'direction': direction,
        }
        self.logger.log_action(move['game_id'], {'action': 'move', 'data': move})
        await self._send(websocket, 'move', move)

    def _print_match_result(self, data):
        print(
            f"\nGAME OVER  {data.get('player_1')}={data.get('score_1')}  "
            f"{data.get('player_2')}={data.get('score_2')}  "
            f"winner={data.get('winner')}\n"
        )
