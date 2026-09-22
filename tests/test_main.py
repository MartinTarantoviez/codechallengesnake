import asyncio
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.main import build_arg_parser, _main_async, main, PROD_URI, LOCAL_URI


def run(coro):
    return asyncio.run(coro)


def test_arg_parser_requires_auth_token():
    parser = build_arg_parser()
    args = parser.parse_args(['tok123'])
    assert args.auth_token == 'tok123'
    assert args.show_board is False
    assert args.local is False
    assert args.challenge is None
    print('test_arg_parser_requires_auth_token: OK')


def test_arg_parser_board_flag_and_alias():
    parser = build_arg_parser()
    assert parser.parse_args(['tok', '--board']).show_board is True
    assert parser.parse_args(['tok', '--gui']).show_board is True
    print('test_arg_parser_board_flag_and_alias: OK')


def test_arg_parser_local_and_challenge_flags():
    parser = build_arg_parser()
    args = parser.parse_args(['tok', '--local', '--challenge', 'rival'])
    assert args.local is True
    assert args.challenge == 'rival'
    print('test_arg_parser_local_and_challenge_flags: OK')


def test_main_async_builds_production_uri_by_default():
    parser = build_arg_parser()
    args = parser.parse_args(['mytoken'])
    captured = {}

    async def fake_run_forever(self, uri):
        captured['uri'] = uri

    with patch('snake.main.MatchClient.run_forever', new=fake_run_forever):
        run(_main_async(args))
    assert captured['uri'] == PROD_URI.format('mytoken')
    print('test_main_async_builds_production_uri_by_default: OK')


def test_main_async_builds_local_uri_when_requested():
    parser = build_arg_parser()
    args = parser.parse_args(['mytoken', '--local'])
    captured = {}

    async def fake_run_forever(self, uri):
        captured['uri'] = uri

    with patch('snake.main.MatchClient.run_forever', new=fake_run_forever):
        run(_main_async(args))
    assert captured['uri'] == LOCAL_URI.format('mytoken')
    print('test_main_async_builds_local_uri_when_requested: OK')


def test_main_async_passes_show_board_and_challenge_through():
    parser = build_arg_parser()
    args = parser.parse_args(['mytoken', '--board', '--challenge', 'rival'])
    captured = {}

    async def fake_run_forever(self, uri):
        captured['show_board'] = self.show_board
        captured['pending_challenge'] = self.pending_challenge

    with patch('snake.main.MatchClient.run_forever', new=fake_run_forever):
        run(_main_async(args))
    assert captured['show_board'] is True
    assert captured['pending_challenge'] == 'rival'
    print('test_main_async_passes_show_board_and_challenge_through: OK')


def test_main_parses_argv_and_runs():
    async def fake_run_forever(self, uri):
        pass

    with patch('snake.main.MatchClient.run_forever', new=fake_run_forever), \
         patch('sys.argv', ['snake.main', 'mytoken']):
        main()  # must not raise
    print('test_main_parses_argv_and_runs: OK')


ALL_TESTS = [
    test_arg_parser_requires_auth_token,
    test_arg_parser_board_flag_and_alias,
    test_arg_parser_local_and_challenge_flags,
    test_main_async_builds_production_uri_by_default,
    test_main_async_builds_local_uri_when_requested,
    test_main_async_passes_show_board_and_challenge_through,
    test_main_parses_argv_and_runs,
]


if __name__ == '__main__':
    for t in ALL_TESTS:
        t()
    print(f'\nALL {len(ALL_TESTS)} MAIN TESTS PASSED')
