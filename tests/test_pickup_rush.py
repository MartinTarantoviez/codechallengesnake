import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.game_state import GameState
from snake.pickup_rush import PickupPlanner, MIN_REMAINING_TO_RUSH, SAFETY_MARGIN
from snake.strategy import SnakeStrategy


def test_pickup_target_none_when_no_pickups():
    state = GameState(9, 9, {'A': (0, 0), 'B': (8, 8)}, {'a': [], 'b': []}, {}, [])
    planner = PickupPlanner('A', 'B')
    assert planner._pickup_target(state) is None
    print('test_pickup_target_none_when_no_pickups: OK')


def test_pickup_target_none_in_endgame():
    state = GameState(9, 9, {'A': (0, 0), 'B': (8, 8)}, {'a': [], 'b': []}, {},
                       [(0, 3)], remaining_moves=MIN_REMAINING_TO_RUSH - 1)
    planner = PickupPlanner('A', 'B')
    assert planner._pickup_target(state) is None
    print('test_pickup_target_none_in_endgame: OK')


def test_pickup_target_none_when_head_missing():
    state = GameState(9, 9, {'B': (8, 8)}, {'a': [], 'b': []}, {}, [(0, 3)])
    planner = PickupPlanner('A', 'B')
    assert planner._pickup_target(state) is None
    print('test_pickup_target_none_when_head_missing: OK')


def test_pickup_target_picks_the_only_reachable_one():
    state = GameState(9, 9, {'A': (0, 0), 'B': (8, 8)}, {'a': [], 'b': []}, {},
                       [(0, 3)], remaining_moves=200)
    planner = PickupPlanner('A', 'B')
    assert planner._pickup_target(state) == (0, 3)
    print('test_pickup_target_picks_the_only_reachable_one: OK')


def test_pickup_target_skips_pickup_opponent_wins_race():
    # opponent (B) sits right next to the pickup, we're far away.
    state = GameState(9, 9, {'A': (8, 0), 'B': (0, 4)}, {'a': [], 'b': []}, {},
                       [(0, 3)], remaining_moves=200)
    planner = PickupPlanner('A', 'B')
    assert planner._pickup_target(state) is None
    print('test_pickup_target_skips_pickup_opponent_wins_race: OK')


def test_pickup_target_skips_pickup_with_no_opportunity_left():
    # reachable, winnable, but there aren't enough remaining moves left
    # to make the detour worth anything (horizon - dist <= 0).
    state = GameState(9, 9, {'A': (0, 0), 'B': (8, 8)}, {'a': [], 'b': []}, {},
                       [(0, 8)], remaining_moves=MIN_REMAINING_TO_RUSH + 2)
    planner = PickupPlanner('A', 'B')
    assert planner._pickup_target(state) is None
    print('test_pickup_target_skips_pickup_with_no_opportunity_left: OK')


def test_pickup_target_no_opponent_head_still_works():
    state = GameState(9, 9, {'A': (0, 0)}, {'a': [], 'b': []}, {},
                       [(0, 3)], remaining_moves=200)
    planner = PickupPlanner('A', 'B')
    assert planner._pickup_target(state) == (0, 3)
    print('test_pickup_target_no_opponent_head_still_works: OK')


def test_step_toward_routes_around_wrong_digit():
    # Two candidate first steps toward the pickup at (0,4): 'right' walks
    # straight into a wrong digit cell (3, when target is 1), 'down' goes
    # the long way around but avoids it -- step_toward must prefer the
    # route that avoids the wrong digit even though it's not a wall.
    state = GameState(5, 5, {'A': (0, 0), 'B': (4, 4)}, {'a': [], 'b': []},
                       {(0, 1): 3, (0, 2): 1}, [(0, 4)], remaining_moves=200)
    planner = PickupPlanner('A', 'B')
    legal_moves = state.legal_moves('A', 'B')
    step = planner._step_toward(state, (0, 4), legal_moves)
    assert step != 'right', "should route around the wrong-digit cell, not through it"
    print('test_step_toward_routes_around_wrong_digit: OK')


def test_step_toward_none_when_target_unreachable():
    # pickup sealed off entirely by opponent's body -> no route exists.
    state = GameState(5, 5, {'A': (0, 0), 'B': (4, 4)}, {'a': [], 'b': [(0, 1), (1, 0)]},
                       {}, [(4, 0)], remaining_moves=200)
    planner = PickupPlanner('A', 'B')
    legal_moves = state.legal_moves('A', 'B')
    step = planner._step_toward(state, (4, 0), legal_moves)
    assert step is None
    print('test_step_toward_none_when_target_unreachable: OK')


def test_pickup_target_skips_pickup_unreachable_by_us():
    # pickup sealed off from our head entirely by opponent's body. Both
    # blocking cells must NOT be the last element of the body list --
    # walls_for() frees each snake's own tail (it vacates on a
    # non-growing move), so a 3-segment body with an unrelated tail cell
    # keeps both real blockers solid.
    state = GameState(5, 5, {'A': (4, 4), 'B': (0, 0)},
                       {'a': [], 'b': [(3, 4), (4, 3), (2, 4)]},
                       {}, [(0, 4)], remaining_moves=200)
    planner = PickupPlanner('A', 'B')
    assert planner._pickup_target(state) is None
    print('test_pickup_target_skips_pickup_unreachable_by_us: OK')


def test_pickup_target_skips_pickup_with_zero_opportunity():
    # reachable, winnable, but distance == horizon exactly -> opportunity
    # is 0, not > 0, so it must still be skipped (a tall thin 2-column
    # grid keeps the opponent far from the pickup while still 50 steps
    # from us, so this isolates the opportunity check from the race check).
    state = GameState(60, 2, {'A': (0, 0), 'B': (0, 1)}, {'a': [], 'b': []},
                       {}, [(50, 0)], remaining_moves=50)
    planner = PickupPlanner('A', 'B')
    assert planner._pickup_target(state) is None
    print('test_pickup_target_skips_pickup_with_zero_opportunity: OK')


def test_suggest_returns_none_when_target_exists_but_unroutable():
    # digit 6 (wrong -- target ends up 5) seals both of the pickup's only
    # two neighbors as soft obstacles for _step_toward, while the real
    # (wall-only) BFS _pickup_target uses still finds it reachable and
    # worth targeting -- so suggest() must fall through to None when the
    # route search comes up empty.
    state = GameState(3, 3, {'A': (0, 0), 'B': (2, 0)}, {'a': [], 'b': []},
                       {(0, 1): 6, (1, 2): 6, (2, 2): 5}, [(0, 2)],
                       remaining_moves=200)
    planner = PickupPlanner('A', 'B')
    legal_moves = state.legal_moves('A', 'B')
    scored = [(d, 0.0) for d, _s, _r in legal_moves]
    assert planner._pickup_target(state) == (0, 2)  # sanity: it IS targeted
    assert planner.suggest(state, legal_moves, scored, 0.0) is None
    print('test_suggest_returns_none_when_target_exists_but_unroutable: OK')

def test_suggest_returns_none_without_a_target():
    state = GameState(9, 9, {'A': (0, 0), 'B': (8, 8)}, {'a': [], 'b': []}, {}, [])
    planner = PickupPlanner('A', 'B')
    legal_moves = state.legal_moves('A', 'B')
    scored = [(d, 0.0) for d, _s, _r in legal_moves]
    assert planner.suggest(state, legal_moves, scored, 0.0) is None
    print('test_suggest_returns_none_without_a_target: OK')


def test_suggest_declines_when_below_safety_margin():
    state = GameState(9, 9, {'A': (0, 0), 'B': (8, 8)}, {'a': [], 'b': []}, {},
                       [(0, 3)], remaining_moves=200)
    planner = PickupPlanner('A', 'B')
    legal_moves = state.legal_moves('A', 'B')
    step_dir = planner._step_toward(state, (0, 3), legal_moves)
    # Force every move's score far below the step direction's score.
    scored = [(d, -1000.0) for d, _s, _r in legal_moves]
    best_score = 500.0  # some other move scored way better than the pickup route
    assert planner.suggest(state, legal_moves, scored, best_score) is None
    assert step_dir is not None  # sanity: a route did exist, it's just declined
    print('test_suggest_declines_when_below_safety_margin: OK')


def test_suggest_accepts_within_safety_margin():
    state = GameState(9, 9, {'A': (0, 0), 'B': (8, 8)}, {'a': [], 'b': []}, {},
                       [(0, 3)], remaining_moves=200)
    planner = PickupPlanner('A', 'B')
    legal_moves = state.legal_moves('A', 'B')
    step_dir = planner._step_toward(state, (0, 3), legal_moves)
    best_score = 0.0
    scored = [(d, best_score if d == step_dir else -5.0) for d, _s, _r in legal_moves]
    assert planner.suggest(state, legal_moves, scored, best_score) == step_dir
    print('test_suggest_accepts_within_safety_margin: OK')


def test_strategy_end_to_end_commits_to_reachable_pickup():
    # No food at all, just a reachable pickup a few steps away: with
    # nothing else competing for attention, SnakeStrategy should head
    # straight for it.
    state = GameState(9, 9, {'A': (4, 4), 'B': (8, 8)}, {'a': [], 'b': []},
                       {}, [(4, 7)], remaining_moves=200)
    direction = SnakeStrategy('A', 'B').choose_direction(state)
    assert direction == 'right'
    print('test_strategy_end_to_end_commits_to_reachable_pickup: OK')


if __name__ == '__main__':
    test_pickup_target_none_when_no_pickups()
    test_pickup_target_none_in_endgame()
    test_pickup_target_none_when_head_missing()
    test_pickup_target_picks_the_only_reachable_one()
    test_pickup_target_skips_pickup_opponent_wins_race()
    test_pickup_target_skips_pickup_with_no_opportunity_left()
    test_pickup_target_skips_pickup_unreachable_by_us()
    test_pickup_target_skips_pickup_with_zero_opportunity()
    test_pickup_target_no_opponent_head_still_works()
    test_step_toward_routes_around_wrong_digit()
    test_step_toward_none_when_target_unreachable()
    test_suggest_returns_none_without_a_target()
    test_suggest_returns_none_when_target_exists_but_unroutable()
    test_suggest_declines_when_below_safety_margin()
    test_suggest_accepts_within_safety_margin()
    test_strategy_end_to_end_commits_to_reachable_pickup()
    print('ALL PICKUP_RUSH TESTS PASSED')
