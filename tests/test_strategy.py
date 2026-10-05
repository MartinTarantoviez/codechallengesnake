import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.game_state import GameState, DIRECTIONS
from snake.strategy import SnakeStrategy, Evaluator


def _empty_state(rows=10, cols=10, heads=None, food=None, pickups=None,
                  multipliers=None, walls=None, tail_food=None):
    heads = heads or {'A': (5, 5), 'B': (0, 0)}
    return GameState(rows, cols, heads, bodies={'a': [], 'b': []},
                      food=food or {}, pickups=pickups or [],
                      multipliers=multipliers or {'A': 1, 'B': 1}, walls=walls,
                      tail_food=tail_food)


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


def test_simulate_pickup_scores_flat_and_bumps_multiplier():
    state = _empty_state(pickups=[(5, 6)])
    new_state, reward = state.simulate('A', 'B', 'right')
    assert new_state is not None
    assert reward == 50.0
    assert new_state.multipliers['A'] == 2
    print('test_simulate_pickup_scores_flat_and_bumps_multiplier: OK')


def test_simulate_pickup_does_not_grow_and_is_removed():
    state = _empty_state(pickups=[(5, 6)])
    new_state, _reward = state.simulate('A', 'B', 'right')
    assert new_state.bodies['a'] == []  # X does not grow the snake
    assert (5, 6) not in new_state.pickups
    print('test_simulate_pickup_does_not_grow_and_is_removed: OK')


def test_multiplier_scales_correct_digit_reward_only():
    state = _empty_state(food={(5, 6): 9}, multipliers={'A': 3, 'B': 1})
    _new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == 9 * 100 * 3
    print('test_multiplier_scales_correct_digit_reward_only: OK')


def test_simulate_eats_own_tail_food_grows_and_scores():
    state = _empty_state(tail_food={(5, 6): 'A'}, multipliers={'A': 2, 'B': 1})
    new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == 200.0  # 100 * multiplier 2, same economics as a digit=1
    assert new_state.bodies['a'] == [(5, 5)]  # grows, same as a correct digit
    assert (5, 6) not in new_state.tail_food
    print('test_simulate_eats_own_tail_food_grows_and_scores: OK')


def test_simulate_steps_on_others_tail_food_just_clears_it():
    # Marked 'B' -- A may not eat it (it's A's own shed tail from an
    # earlier crash); stepping on it is a plain survive move, no growth.
    state = _empty_state(tail_food={(5, 6): 'B'})
    new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == 0.0
    assert new_state.bodies['a'] == []  # no growth
    assert (5, 6) not in new_state.tail_food  # still cleared either way
    print('test_simulate_steps_on_others_tail_food_just_clears_it: OK')


def test_simulate_eating_target_digit_clears_every_copy():
    # v6: three copies of the target digit 1 are on the board; eating
    # the one at (5,6) must clear all of them, not just that cell.
    state = _empty_state(food={(5, 6): 1, (0, 0): 1, (9, 9): 1})
    new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == 100.0  # scores/grows once, for the landed copy only
    assert new_state.food == {}
    print('test_simulate_eating_target_digit_clears_every_copy: OK')


def test_simulate_wrong_digit_only_clears_the_one_copy_eaten():
    # target is 1 (only digit family present besides the wrong one);
    # two copies of the wrong digit 5 sit on the board -- eating one
    # must leave the other untouched.
    state = _empty_state(food={(5, 6): 5, (0, 0): 5, (5, 4): 1})
    new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == -500.0
    assert new_state.food == {(0, 0): 5, (5, 4): 1}
    print('test_simulate_wrong_digit_only_clears_the_one_copy_eaten: OK')


def test_simulate_crash_sheds_tail_as_opponent_tail_food():
    # Body longer than head+2 -- the shed cells must become tail food
    # only B may eat, dropped at their old positions.
    state = _empty_state(heads={'A': (5, 5), 'B': (0, 0)})
    state.bodies['a'] = [(5, 4), (5, 3), (5, 2), (5, 1)]
    new_state, reward = state.simulate('A', 'B', 'left')  # walks into the neck
    assert reward == -500.0
    assert new_state.heads['A'] == (5, 5)  # stays put
    assert new_state.bodies['a'] == [(5, 4), (5, 3)]  # kept: head + 2
    assert new_state.tail_food == {(5, 2): 'B', (5, 1): 'B'}
    print('test_simulate_crash_sheds_tail_as_opponent_tail_food: OK')


def test_simulate_wall_penalizes_and_snake_stays_put():
    # v7: a wall crash is now the same "stay put, shed tail" consequence
    # as any other crash -- an empty body sheds nothing, so only the
    # head position and reward matter here.
    state = _empty_state(walls={(5, 6)})
    new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == -500.0
    assert new_state.heads['A'] == (5, 5)
    assert new_state.bodies['a'] == []
    print('test_simulate_wall_penalizes_and_snake_stays_put: OK')


def test_wall_carries_over_into_the_next_simulated_state():
    # A move that doesn't touch the wall must still hand it down to the
    # resulting state, so the opponent's simulated reply (2-ply search)
    # sees it too instead of the wall silently vanishing after one step.
    state = _empty_state(walls={(5, 6)})
    new_state, _reward = state.simulate('A', 'B', 'up')  # moves away, doesn't hit it
    assert new_state.walls == {(5, 6)}
    print('test_wall_carries_over_into_the_next_simulated_state: OK')


def test_bot_avoids_wall_when_a_safe_alternative_exists():
    # Boxed so 'right' walks into the wall and 'up' is a clean escape.
    heads = {'A': (5, 5), 'B': (0, 0)}
    state = GameState(11, 11, heads, {'a': [], 'b': []}, {}, [],
                       walls={(5, 6)})
    strategy = SnakeStrategy('A', 'B')
    direction = strategy.choose_direction(state)
    assert direction != 'right', "should not walk into the wall when a safer move exists"
    print('test_bot_avoids_wall_when_a_safe_alternative_exists: OK')


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


def test_evaluator_pulls_toward_the_closest_copy_of_the_target_digit():
    # v6: several copies of the target digit can be on the board --
    # the evaluator must pull toward whichever is actually closest, not
    # just the first one a dict scan happens to find.
    heads = {'A': (5, 5), 'B': (9, 9)}
    far_only = {(5, 5 + 8): 1}
    near_and_far = {(5, 5 + 8): 1, (5, 5 + 2): 1}
    ev = Evaluator('A', 'B')
    far_score = ev.evaluate(GameState(11, 11, heads, {'a': [], 'b': []}, far_only, []))
    near_score = ev.evaluate(GameState(11, 11, heads, {'a': [], 'b': []}, near_and_far, []))
    assert near_score > far_score
    print('test_evaluator_pulls_toward_the_closest_copy_of_the_target_digit: OK')


def test_evaluator_pulls_toward_own_reachable_tail_food():
    heads = {'A': (5, 5), 'B': (9, 9)}
    ev = Evaluator('A', 'B')
    without = ev.evaluate(GameState(11, 11, heads, {'a': [], 'b': []}, {}, []))
    with_mine = ev.evaluate(GameState(11, 11, heads, {'a': [], 'b': []}, {}, [],
                                       tail_food={(5, 8): 'A'}))
    with_theirs = ev.evaluate(GameState(11, 11, heads, {'a': [], 'b': []}, {}, [],
                                         tail_food={(5, 8): 'B'}))
    assert with_mine > without
    assert with_theirs == without  # not yours to eat -- no pull either way
    print('test_evaluator_pulls_toward_own_reachable_tail_food: OK')


if __name__ == '__main__':
    test_simulate_correct_digit_grows_and_scores()
    test_simulate_wrong_digit_penalizes_but_survives()
    test_simulate_pickup_scores_flat_and_bumps_multiplier()
    test_simulate_pickup_does_not_grow_and_is_removed()
    test_multiplier_scales_correct_digit_reward_only()
    test_simulate_eats_own_tail_food_grows_and_scores()
    test_simulate_steps_on_others_tail_food_just_clears_it()
    test_simulate_eating_target_digit_clears_every_copy()
    test_simulate_wrong_digit_only_clears_the_one_copy_eaten()
    test_simulate_crash_sheds_tail_as_opponent_tail_food()
    test_simulate_wall_penalizes_and_snake_stays_put()
    test_wall_carries_over_into_the_next_simulated_state()
    test_bot_avoids_wall_when_a_safe_alternative_exists()
    test_bot_prefers_correct_digit_over_wrong_digit_when_both_reachable()
    test_bot_avoids_wrong_digit_when_a_safe_alternative_exists()
    test_evaluator_scores_target_digit_higher_with_bigger_multiplier()
    test_evaluator_pulls_toward_the_closest_copy_of_the_target_digit()
    test_evaluator_pulls_toward_own_reachable_tail_food()
    print('ALL STRATEGY TESTS PASSED')
