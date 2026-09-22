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


def test_regression_game_4d70dada():
    # The exact ambiguous shape that used to kill the bot for real: body
    # {(6,6),(7,6),(7,7)}, head (6,7). Both (6,6) and (7,7) touch the
    # head. With the true previous head known, this must resolve
    # correctly (neck=(6,6), tail=(7,7)) and reject moving into the neck.
    head = (6, 7)
    body = {(6, 6), (7, 6), (7, 7)}

    ordered = order_body_from_neck((6, 6), body)
    assert ordered == [(6, 6), (7, 6), (7, 7)]
    assert tail_of(ordered) == (7, 7)

    bodies = BodyOrderer.order_all(
        heads={'A': head, 'B': (9, 8)},
        bodies={'a': body, 'b': {(10, 7), (10, 8)}},
        prev_heads={'A': (6, 6), 'B': (9, 9)},
    )
    assert bodies['a'] == [(6, 6), (7, 6), (7, 7)]

    state = GameState(15, 15, {'A': head, 'B': (9, 8)}, bodies,
                       food={}, pickups=[])
    new_state, _reward = state.simulate('A', 'B', 'left')
    assert new_state is None, "moving into the neck should be illegal, but wasn't"
    print('test_regression_game_4d70dada: OK')


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
    test_regression_game_4d70dada()
    test_order_bodies_no_history_falls_back()
    print('ALL ORDERING TESTS PASSED')
