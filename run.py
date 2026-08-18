import asyncio
import json
import sys
import time
import traceback
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
from snake_ai import parse_board, find_positions, order_bodies, choose_direction

# Bump this whenever run.py changes. Printed at startup so it's obvious
# from the terminal output alone which version is actually running --
# useful since downloaded copies tend to pile up with the same filename.
BUILD = "2026-08-18.r6-logsdir"

# Where match logs get written. Created automatically if it doesn't exist.
LOGS_DIR = Path(__file__).resolve().parent / 'logs'

# A running text log of events received / actions sent per game, written to
# logs/game_<game_id>.log when the match ends.
HISTORY = {}

# Each snake's head position as of the *previous* turn we saw, per game_id:
# {game_id: {'A': (r,c) or None, 'B': (r,c) or None}}. This is what lets us
# know a snake's neck with certainty instead of guessing it from one frame
# (see snake_ai.order_bodies for why that guess can be fatally wrong).
PREV_HEADS = {}

SHOW_BOARD = '--gui' in sys.argv or '--board' in sys.argv


def log_event(game_id, message):
    HISTORY.setdefault(game_id, []).append('< ' + json.dumps(message))


def log_action(game_id, message):
    HISTORY.setdefault(game_id, []).append('> ' + json.dumps(message))


def write_game_log(game_id):
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        path = LOGS_DIR / f"game_{game_id}.log"
        with open(path, "w") as f:
            f.write("\n".join(HISTORY.get(game_id, [])) + "\n")
        print(f"saved {path}")
    except OSError as e:
        print(f"could not write game log: {e}")


async def send(websocket, action, data):
    message = json.dumps(
        {
            'action': action,
            'data': data,
        }
    )
    print(message)
    await websocket.send(message)


async def start(auth_token):
    uri = "wss://server.codechallenge.net.ar/ws?token={}".format(auth_token)
    # uri = "ws://localhost:5000/ws?token={}".format(auth_token)
    while True:
        try:
            print('connection to {}'.format(uri))
            async with websockets.connect(uri) as websocket:
                print('connection READY!')
                await play(websocket)
        except KeyboardInterrupt:
            print('Exiting...')
            break
        except Exception as e:
            print(f'connection error! {type(e).__name__}: {e}')
            traceback.print_exc()
            time.sleep(3)


async def play(websocket):
    while True:
        try:
            request = await websocket.recv()
            print(f"< {request}")
            request_data = json.loads(request)

            event = request_data.get('event')

            if event == 'update_user_list':
                pass

            # IMPORTANT: log any error/rejection event the server might send back.
            # This is our best way to confirm/adjust the exact action schema
            # (e.g. whether it's "direction", "dir", "move" as a string, etc).
            if event in ('error', 'invalid_action', 'invalid_move'):
                game_id = request_data.get('data', {}).get('game_id')
                if game_id:
                    log_event(game_id, request_data)
                print(f"!!! SERVER REJECTED ACTION: {request_data}")

            if event == 'game_over':
                game_id = request_data['data'].get('game_id')
                if game_id:
                    log_event(game_id, request_data)
                    write_game_log(game_id)
                    PREV_HEADS.pop(game_id, None)
                if SHOW_BOARD:
                    print_match_result(request_data['data'])

            if event == 'challenge':
                await send(
                    websocket,
                    'accept_challenge',
                    {
                        'challenge_id': request_data['data']['challenge_id'],
                    },
                )

            if event == 'your_turn':
                log_event(request_data['data']['game_id'], request_data)
                await process_your_turn(websocket, request_data)

        except KeyboardInterrupt:
            print('Exiting...')
            break
        except Exception as e:
            print('error {}'.format(str(e)))
            break  # force login again


# ---------------------------------------------------------------------------
# Terminal board view
#
# The previous version of this file drove a tkinter window (BoardViewer)
# to show the board live. tkinter needs a local display server, which most
# dev containers / remote environments (including the one this bot runs
# in) don't have -- so `--gui` either crashed or silently did nothing.
# This renders the same information as colored text directly in the
# terminal, which works everywhere the bot itself works. Pass --board (or
# --gui, kept as an alias) to turn it on.
# ---------------------------------------------------------------------------

_RESET = '\033[0m'
_DIM = '\033[2m'
_BOLD = '\033[1m'
_CYAN = '\033[38;5;80m'
_CYAN_BG = '\033[48;5;23m'
_AMBER = '\033[38;5;215m'
_AMBER_BG = '\033[48;5;94m'
_GOLD = '\033[38;5;220m'
_GREY = '\033[38;5;238m'


def render_board_ansi(grid, rows, cols, side):
    lines = []
    for r in range(rows):
        row_chars = []
        for c in range(cols):
            ch = grid[r][c]
            if ch == '*':
                row_chars.append(f'{_GOLD}{_BOLD}◆{_RESET}')
            elif ch == ' ':
                row_chars.append(f'{_GREY}·{_RESET}')
            elif ch == 'A':
                row_chars.append(f'{_CYAN_BG}{_BOLD} A {_RESET}')
                continue
            elif ch == 'a':
                row_chars.append(f'{_CYAN}▓{_RESET}')
            elif ch == 'B':
                row_chars.append(f'{_AMBER_BG}{_BOLD} B {_RESET}')
                continue
            elif ch == 'b':
                row_chars.append(f'{_AMBER}▓{_RESET}')
            else:
                row_chars.append(ch)
        lines.append(''.join(row_chars))
    return '\n'.join(lines)


def print_turn_board(data, grid):
    rows, cols = data['rows'], data['cols']
    side = data['side']
    me = 'A' if side == 'A' else 'B'
    opp = 'B' if side == 'A' else 'A'
    print(f"\n{_BOLD}game {data['game_id'][:8]}  turn rem={data.get('remaining_moves')}{_RESET}")
    label = (
        f"{_CYAN}{_BOLD}{data.get('player_1')}{_RESET} {data.get('score_1')}"
        f"   vs   "
        f"{_AMBER}{_BOLD}{data.get('player_2')}{_RESET} {data.get('score_2')}"
    )
    print(label)
    print(render_board_ansi(grid, rows, cols, side))


def print_match_result(data):
    winner = data.get('winner')
    print(
        f"\n{_BOLD}GAME OVER{_RESET}  "
        f"{data.get('player_1')}={data.get('score_1')}  "
        f"{data.get('player_2')}={data.get('score_2')}  "
        f"winner={winner}\n"
    )


# ---------------------------------------------------------------------------
# Turn handling
# ---------------------------------------------------------------------------

async def process_your_turn(websocket, request_data):
    await process_move(websocket, request_data)


async def process_move(websocket, request_data):
    data = request_data['data']
    side = data['side']  # 'A' or 'B'
    board_str = data['board']
    rows = data['rows']
    cols = data['cols']

    grid = parse_board(board_str, rows, cols)
    board_info = find_positions(grid, rows, cols)

    game_id = data['game_id']
    board_info = order_bodies(board_info, PREV_HEADS.get(game_id))

    if SHOW_BOARD:
        print_turn_board(data, grid)

    me_head = side
    opp_head = 'B' if side == 'A' else 'A'
    me_body = me_head.lower()
    opp_body = opp_head.lower()

    if me_head not in board_info['heads']:
        print("WARNING: could not find our own head on the board, sending 'up'")
        direction = 'up'
    else:
        direction = choose_direction(
            board_info, rows, cols, me_head, me_body, opp_head, opp_body,
            data.get('remaining_moves'),
        )

    # Remember this turn's heads so next turn's order_bodies() can use them
    # as the (unambiguous) neck position for each snake.
    PREV_HEADS[game_id] = dict(board_info['heads'])

    move = {
        'game_id': data['game_id'],
        'turn_token': data['turn_token'],
        'direction': direction,
    }
    log_action(move['game_id'], {'action': 'move', 'data': move})
    await send(websocket, 'move', move)


if __name__ == '__main__':
    print(f"run.py build: {BUILD}")
    if len(sys.argv) >= 2:
        auth_token = sys.argv[1]
        asyncio.run(start(auth_token))
    else:
        print('please provide your auth_token')