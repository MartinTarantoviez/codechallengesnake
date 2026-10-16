import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.game_state import GameState, DIRECTIONS
from snake.strategy import SnakeStrategy, Evaluator
from snake.evaluator import _target_term, _PULL_MULTIPLIER_CAP


def _empty_state(rows=10, cols=10, heads=None, food=None, pickups=None,
                  multipliers=None, walls=None, tail_food=None,
                  big_bombs=(), small_bombs=()):
    heads = heads or {'A': (5, 5), 'B': (0, 0)}
    return GameState(rows, cols, heads, bodies={'a': [], 'b': []},
                      food=food or {}, pickups=pickups or [],
                      multipliers=multipliers or {'A': 1, 'B': 1}, walls=walls,
                      tail_food=tail_food, big_bombs=big_bombs, small_bombs=small_bombs)


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


def test_simulate_big_bomb_explodes_within_chebyshev_2():
    # Head (5,5) -> right -> (5,6). Bomb at (5,8): Chebyshev distance 2,
    # right at the edge of the 5x5 blast square -- still goes off.
    state = _empty_state(big_bombs=[(5, 8)])
    _new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == -500.0
    print('test_simulate_big_bomb_explodes_within_chebyshev_2: OK')


def test_simulate_small_bomb_explodes_within_chebyshev_1():
    # (5,6) to a small bomb at (5,7): distance 1, edge of its 3x3 square.
    state = _empty_state(small_bombs=[(5, 7)])
    _new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == -500.0
    print('test_simulate_small_bomb_explodes_within_chebyshev_1: OK')


def test_simulate_bomb_out_of_range_does_not_explode():
    state = _empty_state(big_bombs=[(5, 9)])  # distance 3 from (5,6) -- safe
    _new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == 0.0
    print('test_simulate_bomb_out_of_range_does_not_explode: OK')


def test_simulate_two_bombs_in_range_count_as_one_explosion():
    state = _empty_state(big_bombs=[(5, 8)], small_bombs=[(5, 7)])
    _new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == -500.0  # same flat penalty, not doubled
    print('test_simulate_two_bombs_in_range_count_as_one_explosion: OK')


def test_simulate_explosion_is_not_a_crash_move_still_happens_normally():
    # An explosion must NOT shed the tail or leave the snake in place --
    # "no es un choque: tu movimiento se hace igual ... conservás la cola".
    state = _empty_state(big_bombs=[(5, 8)])
    state.bodies['a'] = [(5, 4), (5, 3)]
    new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == -500.0
    assert new_state.heads['A'] == (5, 6)  # actually moved, unlike a crash
    assert new_state.bodies['a'] == [(5, 5), (5, 4)]  # tail kept, normal shift
    print('test_simulate_explosion_is_not_a_crash_move_still_happens_normally: OK')


def test_simulate_explosion_still_eats_whatever_is_on_the_landed_cell():
    # "comés lo que haya en la celda": the digit's own reward is still
    # replaced by the explosion penalty, but the cell is still consumed
    # (removed from food) and the snake still grows.
    state = _empty_state(food={(5, 6): 1}, big_bombs=[(5, 8)])
    new_state, reward = state.simulate('A', 'B', 'right')
    assert reward == -500.0
    assert new_state.bodies['a'] == [(5, 5)]  # still grew
    assert (5, 6) not in new_state.food  # still eaten
    print('test_simulate_explosion_still_eats_whatever_is_on_the_landed_cell: OK')


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


def test_bot_avoids_a_bomb_blast_square_when_a_safe_alternative_exists():
    # 'right' from (5,5) lands at (5,6), 2 cells from the big bomb at
    # (5,8) -- inside its 5x5 blast square. 'up' is a clean escape.
    heads = {'A': (5, 5), 'B': (0, 0)}
    state = GameState(11, 11, heads, {'a': [], 'b': []}, {}, [],
                       big_bombs=[(5, 8)])
    strategy = SnakeStrategy('A', 'B')
    direction = strategy.choose_direction(state)
    assert direction != 'right', "should not walk into the blast square when a safer move exists"
    print('test_bot_avoids_a_bomb_blast_square_when_a_safe_alternative_exists: OK')


def test_bot_does_not_crash_into_opponent_head_for_a_distant_high_multiplier_digit():
    # Same real-match shape as test_target_term_pull_is_capped_at_high_
    # multiplier above, but through the full search: 'down' crashes
    # head-on into B, 'right' is a free empty cell. A distant target
    # digit at a high multiplier used to make the crash score higher.
    heads = {'A': (5, 5), 'B': (6, 5)}
    food = {(5, 12): 9}
    state = GameState(11, 13, heads, {'a': [], 'b': []}, food, [],
                       multipliers={'A': 8, 'B': 1})
    direction = SnakeStrategy('A', 'B').choose_direction(state)
    assert direction != 'down', "should not crash into the opponent's head over a distant digit"
    print('test_bot_does_not_crash_into_opponent_head_for_a_distant_high_multiplier_digit: OK')


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


def test_target_term_pull_is_capped_at_high_multiplier():
    # Regression (2026-10-10): with an uncapped multiplier, a single
    # distant digit's pull (x8, 7 cells away) outweighed even a
    # guaranteed crash (-500) in a real match, wiping a 44,000+ point
    # lead to 0 under the v7 first-crash rule. The pull term must stay
    # bounded past _PULL_MULTIPLIER_CAP even though the real reward for
    # actually eating the digit (game_state.py) keeps scaling with the
    # true multiplier -- only the heuristic nudge is capped.
    state = _empty_state(food={(0, 7): 3})
    dist_me, dist_opp = {(0, 7): 7}, {}
    at_cap = _target_term(state, 3, dist_me, dist_opp, _PULL_MULTIPLIER_CAP, 0.25)
    far_above_cap = _target_term(state, 3, dist_me, dist_opp, 8, 0.25)
    assert far_above_cap == at_cap
    print('test_target_term_pull_is_capped_at_high_multiplier: OK')


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


def test_evaluator_penalizes_sitting_in_a_blast_square():
    heads = {'A': (5, 5), 'B': (9, 9)}
    ev = Evaluator('A', 'B')
    clear = ev.evaluate(GameState(11, 11, heads, {'a': [], 'b': []}, {}, []))
    near_big = ev.evaluate(GameState(11, 11, heads, {'a': [], 'b': []}, {}, [],
                                      big_bombs=[(6, 6)]))  # Chebyshev 1
    near_small = ev.evaluate(GameState(11, 11, heads, {'a': [], 'b': []}, {}, [],
                                        small_bombs=[(6, 6)]))  # Chebyshev 1
    far_big = ev.evaluate(GameState(11, 11, heads, {'a': [], 'b': []}, {}, [],
                                     big_bombs=[(9, 5)]))  # Chebyshev 4, out of range
    assert near_big < clear
    assert near_small < clear
    assert far_big == clear
    print('test_evaluator_penalizes_sitting_in_a_blast_square: OK')


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
    test_simulate_big_bomb_explodes_within_chebyshev_2()
    test_simulate_small_bomb_explodes_within_chebyshev_1()
    test_simulate_bomb_out_of_range_does_not_explode()
    test_simulate_two_bombs_in_range_count_as_one_explosion()
    test_simulate_explosion_is_not_a_crash_move_still_happens_normally()
    test_simulate_explosion_still_eats_whatever_is_on_the_landed_cell()
    test_simulate_wall_penalizes_and_snake_stays_put()
    test_wall_carries_over_into_the_next_simulated_state()
    test_bot_avoids_wall_when_a_safe_alternative_exists()
    test_bot_avoids_a_bomb_blast_square_when_a_safe_alternative_exists()
    test_bot_does_not_crash_into_opponent_head_for_a_distant_high_multiplier_digit()
    test_bot_prefers_correct_digit_over_wrong_digit_when_both_reachable()
    test_bot_avoids_wrong_digit_when_a_safe_alternative_exists()
    test_evaluator_scores_target_digit_higher_with_bigger_multiplier()
    test_target_term_pull_is_capped_at_high_multiplier()
    test_evaluator_pulls_toward_the_closest_copy_of_the_target_digit()
    test_evaluator_pulls_toward_own_reachable_tail_food()
    test_evaluator_penalizes_sitting_in_a_blast_square()
    print('ALL STRATEGY TESTS PASSED')
