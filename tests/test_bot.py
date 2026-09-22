import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.bot import SnakeBot
from snake.game_state import DIRECTIONS

LOG_DIR = Path(__file__).resolve().parent
LOG_PATHS = [
    LOG_DIR / 'game_e2f368d6-a600-11f1-90e9-a2aaa38452dc.log',
    LOG_DIR / 'game_e38bd346-a600-11f1-90e9-a2aaa38452dc.log',
]


def load_turns(path):
    turns = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line.startswith('< '):
                continue
            payload = json.loads(line[2:])
            if payload.get('event') == 'your_turn':
                turns.append(payload['data'])
    return turns


def run_against_match(path):
    turns = load_turns(path)
    print(f'Loaded {len(turns)} turns from {path.name}')
    bot = SnakeBot()
    errors = 0
    total_time = 0.0

    for i, data in enumerate(turns):
        t0 = time.time()
        try:
            direction = bot.choose_move(data)
        except Exception as e:
            print(f'  turn {i}: EXCEPTION {e!r}')
            errors += 1
            continue
        total_time += time.time() - t0
        assert direction in DIRECTIONS, direction

    avg_ms = 1000 * total_time / max(1, len(turns))
    print(f'Ran SnakeBot.choose_move on {len(turns)} real board states, '
          f'{errors} errors, avg {avg_ms:.2f} ms/turn')
    assert errors == 0


def test_real_matches_legacy_format():
    for path in LOG_PATHS:
        if path.exists():
            run_against_match(path)
        else:
            print(f'(skipping missing log {path})')


def test_forget_game_clears_history():
    bot = SnakeBot()
    data = {
        'game_id': 'g1', 'side': 'A', 'rows': 5, 'cols': 5,
        'board': '|A    |\n|     |\n|     |\n|     |\n|     |',
        'remaining_moves': 100,
    }
    bot.choose_move(data)
    assert 'g1' in bot._prev_heads
    bot.forget_game('g1')
    assert 'g1' not in bot._prev_heads
    print('test_forget_game_clears_history: OK')


def test_choose_move_returns_up_when_own_head_missing_from_board():
    bot = SnakeBot()
    data = {
        'game_id': 'g_missing', 'side': 'A', 'rows': 5, 'cols': 5,
        'board': '|     |\n|     |\n|  B  |\n|     |\n|     |',
        'remaining_moves': 100,
    }
    direction = bot.choose_move(data)
    print('test_choose_move_returns_up_when_own_head_missing_from_board:',
          'OK' if direction == 'up' else 'FAILED')
    assert direction == 'up'


def test_choose_move_reads_v4_multipliers_from_turn_data():
    bot = SnakeBot()
    data = {
        'game_id': 'g_mult', 'side': 'A', 'rows': 6, 'cols': 6,
        'board': '|A     |\n|      |\n|      |\n|      |\n|      |\n|     B|',
        'remaining_moves': 200, 'multiplier_1': 3, 'multiplier_2': 2,
    }
    direction = bot.choose_move(data)
    assert direction in DIRECTIONS
    assert bot._multipliers['g_mult'] == {'A': 3, 'B': 2}
    print('test_choose_move_reads_v4_multipliers_from_turn_data: OK')


if __name__ == '__main__':
    test_real_matches_legacy_format()
    test_forget_game_clears_history()
    test_choose_move_returns_up_when_own_head_missing_from_board()
    test_choose_move_reads_v4_multipliers_from_turn_data()
    print('ALL BOT INTEGRATION TESTS PASSED')
