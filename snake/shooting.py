"""
ShootPlanner: v9's shooting is a real alternative to moving -- this
decides whether a shot is worth its flat SHOT_COST (5000) right now.

A shot is only ever suggested when it's a clean, meaningfully damaging
hit (see MIN_CUT_CELLS) AND the resulting 2-ply score still beats the
best ordinary move. That score is the shot's own -SHOT_COST reward,
Evaluator's usual (conservative, nearest-cell-only) pull toward
whatever's reachable -- scored the exact same way a move would be, via
`score_fn` -- PLUS an explicit, optimistic estimate of the cut itself:
every cut cell becomes shot food worth up to 100*multiplier if WE reach
it first (see CUT_CELL_VALUE/CUT_VALUE_MULT_CAP), which Evaluator's own
pull term deliberately doesn't sum over every reachable cell the way
this one-off estimate does -- without it, no realistic cut ever clears
a cost as steep as SHOT_COST and the bot would simply never shoot.
"""

from .game_state import SHOT_COST

MIN_CUT_CELLS = 3
CUT_CELL_VALUE = 100.0
CUT_VALUE_MULT_CAP = 2.0


def _cells_cut(state, new_state, other_letter):
    body_letter = other_letter.lower()
    before = len(state.bodies.get(body_letter, []))
    after = len(new_state.bodies.get(body_letter, []))
    return max(0, before - after)


def _cut_value(state, me, cells_cut):
    my_mult = state.multipliers.get(me, 1)
    return cells_cut * CUT_CELL_VALUE * min(my_mult, CUT_VALUE_MULT_CAP)


def _best_shot(state, me, opp, shoot_moves, score_fn):
    best_dir, best_score = None, float('-inf')
    for d, new_state, reward in shoot_moves:
        cut = _cells_cut(state, new_state, opp)
        if cut < MIN_CUT_CELLS:
            continue
        score = score_fn(new_state, reward) + _cut_value(state, me, cut)
        if score > best_score:
            best_score, best_dir = score, d
    return best_dir, best_score


class ShootPlanner:
    def __init__(self, me, opp):
        self.me = me
        self.opp = opp

    def suggest(self, state, my_score, score_fn, best_move_score):
        """Returns a direction to shoot if it's worth it, else None.
        `score_fn(new_state, reward)` scores a resulting state exactly
        like a move would (SnakeStrategy._score_my_move)."""
        if my_score < SHOT_COST:
            return None
        shoot_moves = state.shoot_moves(self.me, self.opp)
        best_dir, best_score = _best_shot(state, self.me, self.opp, shoot_moves, score_fn)
        if best_dir is not None and best_score > best_move_score:
            return best_dir
        return None
