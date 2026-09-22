import asyncio
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.client import GameLogger, MatchClient


def run(coro):
    return asyncio.run(coro)


class FakeBot:
    def __init__(self, direction='up'):
        self.direction = direction
        self.forgotten = []

    def choose_move(self, data):
        return self.direction

    def forget_game(self, game_id):
        self.forgotten.append(game_id)


class FakeWebSocket:
    """Stands in for a websockets connection: queued incoming messages,
    recorded outgoing ones, and works as its own async context manager
    (matching how `async with websockets.connect(uri) as ws` is used)."""

    def __init__(self, incoming=None, raise_after=Exception('fake connection closed')):
        self.sent = []
        self._incoming = list(incoming or [])
        self._raise_after = raise_after

    async def recv(self):
        if self._incoming:
            return self._incoming.pop(0)
        raise self._raise_after

    async def send(self, message):
        self.sent.append(message)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


# ---------------------------------------------------------------------------
# GameLogger
# ---------------------------------------------------------------------------

def test_game_logger_writes_history_to_a_file():
    with tempfile.TemporaryDirectory() as tmp:
        logger = GameLogger(logs_dir=Path(tmp))
        logger.log_event('g1', {'event': 'your_turn', 'data': {}})
        logger.log_action('g1', {'action': 'move', 'data': {'direction': 'up'}})
        logger.write('g1')
        content = (Path(tmp) / 'game_g1.log').read_text()
        assert content.startswith('< ')
        assert '> ' in content
        print('test_game_logger_writes_history_to_a_file: OK')


def test_game_logger_forget_clears_history():
    logger = GameLogger(logs_dir=Path(tempfile.gettempdir()))
    logger.log_event('g1', {'event': 'x'})
    logger.forget('g1')
    assert logger._history.get('g1') is None
    print('test_game_logger_forget_clears_history: OK')


def test_game_logger_write_handles_oserror_gracefully():
    # An unwritable logs_dir (a file, not a directory) makes mkdir raise
    # OSError -- write() must swallow it, not crash the bot.
    with tempfile.TemporaryDirectory() as tmp:
        blocked = Path(tmp) / 'blocked'
        blocked.write_text('not a directory')
        logger = GameLogger(logs_dir=blocked)
        logger.log_event('g1', {'event': 'x'})
        logger.write('g1')  # must not raise
        print('test_game_logger_write_handles_oserror_gracefully: OK')


# ---------------------------------------------------------------------------
# MatchClient: event handling (no network)
# ---------------------------------------------------------------------------

def test_handle_event_your_turn_sends_a_move():
    bot = FakeBot(direction='left')
    client = MatchClient(bot, logger=GameLogger(logs_dir=Path(tempfile.gettempdir())))
    ws = FakeWebSocket()
    request = {'event': 'your_turn',
               'data': {'game_id': 'g1', 'turn_token': 't1', 'side': 'A',
                        'rows': 5, 'cols': 5, 'board': '|A    |'}}
    run(client._handle_event(ws, request))
    sent = json.loads(ws.sent[-1])
    assert sent['action'] == 'move'
    assert sent['data']['direction'] == 'left'
    print('test_handle_event_your_turn_sends_a_move: OK')


def test_handle_event_challenge_accepts_it():
    client = MatchClient(FakeBot())
    ws = FakeWebSocket()
    request = {'event': 'challenge', 'data': {'challenge_id': 'c1'}}
    run(client._handle_event(ws, request))
    sent = json.loads(ws.sent[-1])
    assert sent == {'action': 'accept_challenge', 'data': {'challenge_id': 'c1'}}
    print('test_handle_event_challenge_accepts_it: OK')


def test_handle_event_error_logs_and_does_not_crash():
    logger = GameLogger(logs_dir=Path(tempfile.gettempdir()))
    client = MatchClient(FakeBot(), logger=logger)
    ws = FakeWebSocket()
    request = {'event': 'invalid_move', 'data': {'game_id': 'g1'}}
    run(client._handle_event(ws, request))
    assert logger._history['g1'][-1].startswith('< ')
    print('test_handle_event_error_logs_and_does_not_crash: OK')


def test_handle_event_game_over_writes_log_and_forgets_bot_state():
    with tempfile.TemporaryDirectory() as tmp:
        logger = GameLogger(logs_dir=Path(tmp))
        bot = FakeBot()
        client = MatchClient(bot, logger=logger)
        ws = FakeWebSocket()
        request = {'event': 'game_over',
                   'data': {'game_id': 'g1', 'player_1': 'x', 'score_1': 10,
                            'player_2': 'y', 'score_2': 5, 'winner': 'x'}}
        run(client._handle_event(ws, request))
        assert (Path(tmp) / 'game_g1.log').exists()
        assert bot.forgotten == ['g1']
        print('test_handle_event_game_over_writes_log_and_forgets_bot_state: OK')


def test_handle_event_game_over_prints_board_when_show_board_true():
    client = MatchClient(FakeBot(), show_board=True)
    ws = FakeWebSocket()
    request = {'event': 'game_over',
               'data': {'game_id': None, 'player_1': 'x', 'score_1': 1,
                        'player_2': 'y', 'score_2': 2, 'winner': 'y'}}
    run(client._handle_event(ws, request))  # must not raise
    print('test_handle_event_game_over_prints_board_when_show_board_true: OK')


def test_handle_event_unknown_event_is_a_no_op():
    client = MatchClient(FakeBot())
    ws = FakeWebSocket()
    run(client._handle_event(ws, {'event': 'list_users', 'data': {}}))
    assert ws.sent == []
    print('test_handle_event_unknown_event_is_a_no_op: OK')


def test_challenge_user_sends_challenge_action():
    client = MatchClient(FakeBot())
    ws = FakeWebSocket()
    run(client.challenge_user(ws, 'someone'))
    sent = json.loads(ws.sent[-1])
    assert sent == {'action': 'challenge', 'data': {'opponent': 'someone'}}
    print('test_challenge_user_sends_challenge_action: OK')


def test_play_processes_messages_until_the_connection_breaks():
    bot = FakeBot(direction='down')
    client = MatchClient(bot, logger=GameLogger(logs_dir=Path(tempfile.gettempdir())))
    your_turn = json.dumps({'event': 'your_turn',
                             'data': {'game_id': 'g1', 'turn_token': 't1', 'side': 'A',
                                      'rows': 5, 'cols': 5, 'board': '|A    |'}})
    ws = FakeWebSocket(incoming=[your_turn])
    run(client._play(ws))  # second recv() raises -> loop breaks cleanly
    sent = json.loads(ws.sent[-1])
    assert sent['data']['direction'] == 'down'
    print('test_play_processes_messages_until_the_connection_breaks: OK')


def test_play_stops_on_keyboard_interrupt():
    client = MatchClient(FakeBot())
    ws = FakeWebSocket(raise_after=KeyboardInterrupt())
    run(client._play(ws))  # must return, not raise
    print('test_play_stops_on_keyboard_interrupt: OK')


# ---------------------------------------------------------------------------
# MatchClient.run_forever (websockets.connect mocked out entirely)
# ---------------------------------------------------------------------------

def test_run_forever_sends_pending_challenge_then_stops():
    your_turn = json.dumps({'event': 'your_turn',
                             'data': {'game_id': 'g1', 'turn_token': 't1', 'side': 'A',
                                      'rows': 5, 'cols': 5, 'board': '|A    |'}})
    first_ws = FakeWebSocket(incoming=[your_turn])  # _play ends via plain Exception
    connect_calls = {'n': 0}

    def fake_connect(uri):
        connect_calls['n'] += 1
        if connect_calls['n'] == 1:
            return first_ws
        raise KeyboardInterrupt()  # ends run_forever's outer loop

    client = MatchClient(FakeBot(), logger=GameLogger(logs_dir=Path(tempfile.gettempdir())),
                          pending_challenge='rival')
    with patch('snake.client.websockets.connect', side_effect=fake_connect):
        run(client.run_forever('ws://fake'))

    challenge_msg = json.loads(first_ws.sent[0])
    assert challenge_msg == {'action': 'challenge', 'data': {'opponent': 'rival'}}
    assert connect_calls['n'] == 2
    print('test_run_forever_sends_pending_challenge_then_stops: OK')


def test_run_forever_retries_after_a_connection_error():
    calls = {'n': 0}

    def fake_connect(uri):
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('connection refused')
        raise KeyboardInterrupt()

    client = MatchClient(FakeBot())
    with patch('snake.client.websockets.connect', side_effect=fake_connect), \
         patch('snake.client.time.sleep') as fake_sleep:
        run(client.run_forever('ws://fake'))

    assert calls['n'] == 2
    fake_sleep.assert_called_once_with(3)
    print('test_run_forever_retries_after_a_connection_error: OK')


ALL_TESTS = [
    test_game_logger_writes_history_to_a_file,
    test_game_logger_forget_clears_history,
    test_game_logger_write_handles_oserror_gracefully,
    test_handle_event_your_turn_sends_a_move,
    test_handle_event_challenge_accepts_it,
    test_handle_event_error_logs_and_does_not_crash,
    test_handle_event_game_over_writes_log_and_forgets_bot_state,
    test_handle_event_game_over_prints_board_when_show_board_true,
    test_handle_event_unknown_event_is_a_no_op,
    test_challenge_user_sends_challenge_action,
    test_play_processes_messages_until_the_connection_breaks,
    test_play_stops_on_keyboard_interrupt,
    test_run_forever_sends_pending_challenge_then_stops,
    test_run_forever_retries_after_a_connection_error,
]


if __name__ == '__main__':
    for t in ALL_TESTS:
        t()
    print(f'\nALL {len(ALL_TESTS)} CLIENT TESTS PASSED')
