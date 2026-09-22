import argparse
import asyncio

from .bot import SnakeBot
from .client import MatchClient

BUILD = "2026-09-21.oop-v3v4-rules"

PROD_URI = "wss://server.codechallenge.net.ar/ws?token={}"
LOCAL_URI = "ws://localhost:5000/ws?token={}"


def build_arg_parser():
    parser = argparse.ArgumentParser(description="Snake CodeChallenge bot")
    parser.add_argument('auth_token', help="your bot's auth token")
    parser.add_argument('--board', '--gui', dest='show_board',
                         action='store_true',
                         help="print a colored board to the terminal each turn")
    parser.add_argument('--local', action='store_true',
                         help="connect to ws://localhost:5000 instead of production")
    parser.add_argument('--challenge', metavar='USERNAME', default=None,
                         help="attempt to challenge this username on connect "
                              "(unconfirmed protocol shape -- see client.py)")
    return parser


async def _main_async(args):
    uri_template = LOCAL_URI if args.local else PROD_URI
    uri = uri_template.format(args.auth_token)
    bot = SnakeBot()
    client = MatchClient(bot, show_board=args.show_board,
                         pending_challenge=args.challenge)
    await client.run_forever(uri)


def main():
    print(f"run.py build: {BUILD}")
    parser = build_arg_parser()
    args = parser.parse_args()
    asyncio.run(_main_async(args))


if __name__ == '__main__':
    main()
