import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.game_state import GameState, DIRECTIONS
from snake.strategy import SnakeStrategy, Evaluator


def _empty_state(rows=10, cols=10, heads=None, food=None, pickups=None,
                  multipliers=None):
    heads = heads or {'A': (5, 5), 'B': (0, 0)}
    return GameState(rows, cols, heads, bodies={'a': [], 'b': []},
                      food=food or {}, pickups=pickups or [],
                      multipliers=multipliers or {'A': 1, 'B': 1})


def test_simulate_correct_digit_grows_and_scores():
    state = _empty_state(food={(5, 6): 1})  # target is 1 (only digit present)
    new_state, reward = state.simulate('A', 'B', 'right')
    assert new_state is not None
    assert reward == 100.0
    assert new_state.bodies['a'] == [(5, 5)]  # old head becomes the new neck segment
    print('test_simulate_correct_digit_grows_and_scores: OK')


def test_simulate_wrong_digit_penalizes_but_survives():
    # digits 1 and 3 present -> target is 1 (predecessor 9 absent).
    # Stepping onto the 3 is "wrong digit": survives, -500, no growth.
    state = _empty_state(food={(5, 6): 3, (5, 4): 1})
    new_state, reward = state.simulate('A', 'B', 'right')
    assert new_state is not None
    assert reward == -500.0
    assert new_state.bodies['a'] == []  # started empty, no growth -> stays empty
    assert (5, 6) not in new_state.food
    print('test_simulate_wrong_digit_penalizes_but_survives: OK')


def test_simulate_pickup_scores_flat_and_bumps_multiplier_no_growth():
    state = _empty_state(pickups=[(5, 6)])
    new_state, reward = state.simulate('A', 'B', 'right')
    assert new_state is not None
    assert reward == 50.0
    assert new_state.multipliers['A'] == 2
    assert new_state.bodies['a'] == []  # X does not grow the snake
    assert (5, 6) not in new_state.pickups
    print('test_simulate_pickup_scores_flat_and_bumps_multiplier_no_growth: OK')


def test_multiplier_scales_correct_digit_reward_only():
    state = _empty_state(food={(5, 6): 9}, multipliers={'A': 3, 'B': 1})
    _new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == 9 * 100 * 3
    print('test_multiplier_scales_correct_digit_reward_only: OK')


def test_bot_prefers_correct_digit_over_wrong_digit_when_both_reachable():
    # Correct target digit is 1 (only 1 present -> pred 9 absent). A
    # wrong digit 5 sits one step away in another direction; the correct
    # one should win even though "any food" heuristics would be tempted
    # by proximity alone.
    heads = {'A': (5, 5), 'B': (0, 0)}
    food = {(5, 6): 1, (5, 4): 5}
    state = GameState(11, 11, heads, {'a': [], 'b': []}, food, [])
    strategy = SnakeStrategy('A', 'B')
    direction = strategy.choose_direction(state)
    assert direction == 'right', direction
    print('test_bot_prefers_correct_digit_over_wrong_digit_when_both_reachable: OK')


def test_bot_avoids_wrong_digit_when_a_safe_alternative_exists():
    # Boxed so 'right' (wrong digit) is one option and 'up' (empty,
    # heading toward the correct digit further away) is clearly safer.
    heads = {'A': (5, 5), 'B': (0, 0)}
    food = {(5, 6): 7, (2, 5): 3}  # target is 3 (pred 2 absent), 7 is wrong
    state = GameState(11, 11, heads, {'a': [], 'b': []}, food, [])
    strategy = SnakeStrategy('A', 'B')
    direction = strategy.choose_direction(state)
    assert direction != 'right', "should not walk into a wrong digit when a safer move exists"
    print('test_bot_avoids_wrong_digit_when_a_safe_alternative_exists: OK')


def test_evaluator_scores_target_digit_higher_with_bigger_multiplier():
    heads = {'A': (5, 5), 'B': (9, 9)}
    food = {(5, 8): 9}  # only digit -> target 9, 3 steps away
    low = GameState(11, 11, heads, {'a': [], 'b': []}, food, [],
                    multipliers={'A': 1, 'B': 1})
    high = GameState(11, 11, heads, {'a': [], 'b': []}, food, [],
                      multipliers={'A': 5, 'B': 1})
    ev = Evaluator('A', 'B')
    assert ev.evaluate(high) > ev.evaluate(low)
    print('test_evaluator_scores_target_digit_higher_with_bigger_multiplier: OK')


if __name__ == '__main__':
    test_simulate_correct_digit_grows_and_scores()
    test_simulate_wrong_digit_penalizes_but_survives()
    test_simulate_pickup_scores_flat_and_bumps_multiplier_no_growth()
    test_multiplier_scales_correct_digit_reward_only()
    test_bot_prefers_correct_digit_over_wrong_digit_when_both_reachable()
    test_bot_avoids_wrong_digit_when_a_safe_alternative_exists()
    test_evaluator_scores_target_digit_higher_with_bigger_multiplier()
    print('ALL STRATEGY TESTS PASSED')
