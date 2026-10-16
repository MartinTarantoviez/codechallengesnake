import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from snake.ordering import (
    order_body_heuristic, order_body_from_neck, tail_of, BodyOrderer,
)
from snake.game_state import GameState


def test_tail_basic():
    head = (5, 5)
    body = {(5, 4), (5, 3), (5, 2)}
    assert tail_of(order_body_heuristic(head, body)) == (5, 2)

    assert tail_of(order_body_heuristic((0, 0), {(0, 1)})) == (0, 1)
    assert tail_of(order_body_heuristic((0, 0), set())) is None

    head = (2, 2)
    body = {(2, 1), (1, 1), (1, 2), (1, 3)}
    assert tail_of(order_body_heuristic(head, body)) == (1, 3)
    print('test_tail_basic: OK')


# The exact ambiguous shape that used to kill the bot for real: body
# {(6,6),(7,6),(7,7)}, head (6,7). Both (6,6) and (7,7) touch the head.
_AMBIGUOUS_COIL_HEAD = (6, 7)
_AMBIGUOUS_COIL_BODY = {(6, 6), (7, 6), (7, 7)}


def _ambiguous_coil_bodies():
    return BodyOrderer.order_all(
        heads={'A': _AMBIGUOUS_COIL_HEAD, 'B': (9, 8)},
        bodies={'a': _AMBIGUOUS_COIL_BODY, 'b': {(10, 7), (10, 8)}},
        prev_heads={'A': (6, 6), 'B': (9, 9)},
    )


def test_regression_game_4d70dada_orders_the_ambiguous_coil_correctly():
    # With the true previous head known, this must resolve correctly
    # (neck=(6,6), tail=(7,7)), not guess the other way around.
    ordered = order_body_from_neck((6, 6), _AMBIGUOUS_COIL_BODY)
    assert ordered == [(6, 6), (7, 6), (7, 7)]
    assert tail_of(ordered) == (7, 7)
    assert _ambiguous_coil_bodies()['a'] == [(6, 6), (7, 6), (7, 7)]
    print('test_regression_game_4d70dada_orders_the_ambiguous_coil_correctly: OK')


def test_regression_game_4d70dada_rejects_moving_into_the_neck():
    bodies = _ambiguous_coil_bodies()
    state = GameState(15, 15, {'A': _AMBIGUOUS_COIL_HEAD, 'B': (9, 8)}, bodies,
                       food={}, pickups=[])
    new_state, reward = state.simulate('A', 'B', 'left')
    # v7: no longer illegal/fatal, but it must still be correctly
    # recognized as a crash into the neck (reward -500, stays put) --
    # not a free, legal shift as a wrong tail guess would wrongly allow.
    assert new_state is not None and reward == -500.0
    assert new_state.heads['A'] == _AMBIGUOUS_COIL_HEAD, \
        "moving into the neck should crash (stay put), but wasn't recognized as one"
    print('test_regression_game_4d70dada_rejects_moving_into_the_neck: OK')


# Real match regression (2026-10-10): a 22-cell body coiled through a
# narrow corridor, where the greedy (non-backtracking) walker used to
# commit to the wrong branch at (9,5) -- a mid-path pinch, not one next
# to the neck -- and dead-end after only 6 cells. The engine then
# silently stopped treating the other 16 cells as solid at all.
_COILED_CORRIDOR_NECK = (10, 5)
_COILED_CORRIDOR_BODY = {
    (8, 4), (8, 5), (9, 4), (9, 5), (9, 6), (10, 4), (10, 5), (10, 6),
    (10, 7), (11, 7), (11, 8), (12, 6), (12, 7), (12, 8), (13, 7),
    (13, 8), (14, 7), (14, 8), (15, 7), (15, 8), (16, 7), (16, 8),
}


def test_regression_coiled_corridor_body_resolves_every_cell():
    ordered = order_body_from_neck(_COILED_CORRIDOR_NECK, _COILED_CORRIDOR_BODY)
    assert len(ordered) == len(_COILED_CORRIDOR_BODY)
    assert set(ordered) == _COILED_CORRIDOR_BODY
    print('test_regression_coiled_corridor_body_resolves_every_cell: OK')


def test_order_bodies_no_history_falls_back():
    bodies = BodyOrderer.order_all(
        heads={'A': (5, 5), 'B': (0, 0)},
        bodies={'a': {(5, 4), (5, 3)}, 'b': set()},
        prev_heads=None,
    )
    assert bodies['a'] == [(5, 4), (5, 3)]
    assert bodies['b'] == []
    print('test_order_bodies_no_history_falls_back: OK')


if __name__ == '__main__':
    test_tail_basic()
    test_regression_game_4d70dada_orders_the_ambiguous_coil_correctly()
    test_regression_game_4d70dada_rejects_moving_into_the_neck()
    test_regression_coiled_corridor_body_resolves_every_cell()
    test_order_bodies_no_history_falls_back()
    print('ALL ORDERING TESTS PASSED')
