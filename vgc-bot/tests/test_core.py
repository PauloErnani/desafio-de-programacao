from dataclasses import replace
from itertools import product
from random import Random

import pytest
from poke_env.battle import PokemonType as T

from vgc.belief import Belief
from vgc.damage import DamageDistribution, distribution
from vgc.evaluation import evaluate
from vgc.search import Expectiminimax, Outcome
from vgc.state import Board, Fighter, Side


def side(*, speed=100, hp=1.0, types=(T.NORMAL,), tailwind=0):
    mon = Fighter(hp, types, speed)
    return Side((mon,) * 4, (0, 1), tailwind_turns=tailwind)


def test_evaluation_terminal_symmetry_hp_and_speed():
    equal = Board(side(), side())
    assert evaluate(equal) == 0
    assert evaluate(Board(side(hp=0.5), side())) < 0
    assert evaluate(Board(side(speed=80, tailwind=4), side())) > 0
    assert evaluate(Board(side(speed=80, tailwind=4), side(), trick_room_turns=3)) < 0
    state = Board(side(types=(T.FIRE,)), side(types=(T.GRASS,)), weather="sunnyday")
    assert evaluate(state) == pytest.approx(
        -evaluate(replace(state, ours=state.theirs, theirs=state.ours))
    )
    assert -1 < evaluate(state) < 1
    assert evaluate(replace(state, outcome=-1)) == -1
    assert evaluate(replace(state, outcome=0)) == 0


def test_field_is_relative_and_grounding_matters():
    neutral = Board(side(), side())
    assert evaluate(neutral) == evaluate(replace(neutral, weather="sunnyday"))
    fire = Board(side(types=(T.FIRE,)), side())
    assert evaluate(replace(fire, weather="sunnyday")) > evaluate(fire)
    assert evaluate(replace(fire, weather="raindance")) < evaluate(fire)
    electric = side(types=(T.ELECTRIC,))
    aerial = replace(electric, team=tuple(replace(m, grounded=False) for m in electric.team))
    assert evaluate(Board(electric, aerial, terrain="electricterrain")) > 0


def test_damage_accuracy_crit_ko_and_convolution():
    # 100% acerto: dano 85..100. 90 HP cai em 11 dos 16 rolls.
    damage = distribution(tuple(range(85, 101)), accuracy=0.8)
    assert damage.mean == pytest.approx(0.8 * 92.5)
    assert damage.ko_probability(90) == pytest.approx(0.8 * 11 / 16)
    crit = distribution(
        (50,) * 16, accuracy=0.9, critical_rolls=(80,) * 16, critical_probability=0.1
    )
    assert crit.ko_probability(70) == pytest.approx(0.09)
    combined = distribution((50,) * 16, accuracy=0.8).independent_sum(
        distribution((50,) * 16, accuracy=0.9)
    )
    assert combined.ko_probability(100) == pytest.approx(0.72)
    assert distribution((50,) * 16, accuracy=0).mass == ((0, 1.0),)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"accuracy": 1.1},
        {"accuracy": float("nan")},
        {"accuracy": 1, "critical_probability": 0.1},
    ],
)
def test_damage_rejects_invalid_models(kwargs):
    with pytest.raises(ValueError):
        distribution((10,) * 16, **kwargs)
    with pytest.raises(ValueError):
        DamageDistribution(((1, 0.3),))


def test_bayes_preserves_hidden_state_uncertainty():
    belief = Belief(("fast", "bulky"), (0.25, 0.75))
    updated = belief.update(lambda h: 0.8 if h == "fast" else 0.2)
    assert updated.weights == pytest.approx((4 / 7, 3 / 7))
    with pytest.raises(ValueError, match="fora do suporte"):
        belief.update(lambda _: 0)
    assert Belief((1, 2), (0.5, 0.5)).update(lambda _: 1e-300).weights == (0.5, 0.5)


class MatrixGame:
    """Um turno simultâneo: linhas e colunas são pares de ações, não slots."""

    def __init__(self, matrix):
        self.matrix = matrix

    def actions(self, state, *, opponent):
        return tuple(range(len(self.matrix[0] if opponent else self.matrix)))

    def outcomes(self, state, ours, theirs):
        return tuple(Outcome(p, (value,)) for p, value in self.matrix[ours][theirs])

    def terminal(self, state):
        return state != "root"

    def evaluate(self, state):
        return state[0]


@pytest.mark.parametrize("seed", range(25))
def test_pruned_search_matches_exhaustive_ev(seed):
    rng = Random(seed)
    matrix = [
        [[(0.2, rng.uniform(-1, 1)), (0.8, rng.uniform(-1, 1))] for _ in range(4)] for _ in range(8)
    ]
    values = [min(sum(p * v for p, v in cell) for cell in row) for row in matrix]
    result = Expectiminimax(MatrixGame(matrix), max_depth=1, seconds=5).choose("root")
    assert result.value == pytest.approx(max(values))
    assert result.action == values.index(max(values))
    assert result.completed_depth == 1


def test_chance_node_must_not_prune_on_partial_bad_roll():
    # Segunda ação começa em -1 mas tem EV +.8: descartar no primeiro roll seria erro.
    game = MatrixGame([[[(1, 0)]], [[(0.1, -1), (0.9, 1)]]])
    result = Expectiminimax(game, max_depth=1).choose("root")
    assert result.action == 1
    assert result.value == pytest.approx(0.8)


def test_safe_chance_cutoff_and_mixed_strategy_limitation():
    game = MatrixGame([[[(1, 0.8)]], [[(0.5, -1), (0.5, 1)]]])
    result = Expectiminimax(game, max_depth=1).choose("root")
    assert result.value == 0.8
    assert result.cutoffs > 0
    # Matching pennies: garantia pura=-1, equilíbrio misto=0. Não confundir os dois.
    game = MatrixGame([[[(1, 1)], [(1, -1)]], [[(1, -1)], [(1, 1)]]])
    assert Expectiminimax(game).choose("root").value == -1


class TreeGame:
    def __init__(self):
        rng = Random(7)
        self.leaves = {history: rng.uniform(-1, 1) for history in product(range(8), repeat=2)}

    def actions(self, state, *, opponent):
        return (0, 1)

    def outcomes(self, state, ours, theirs):
        return tuple(Outcome(0.5, state + (ours * 4 + theirs * 2 + roll,)) for roll in (0, 1))

    def terminal(self, state):
        return len(state) == 2

    def evaluate(self, state):
        return self.leaves.get(state, 0)


def exhaustive(game, state, depth):
    if not depth or game.terminal(state):
        return game.evaluate(state)
    return max(
        min(
            sum(
                o.probability * exhaustive(game, o.state, depth - 1)
                for o in game.outcomes(state, a, b)
            )
            for b in game.actions(state, opponent=True)
        )
        for a in game.actions(state, opponent=False)
    )


def test_two_turn_search_and_budget_preserve_completed_depth():
    game = TreeGame()
    full = Expectiminimax(game, max_depth=2).choose(())
    assert full.value == pytest.approx(exhaustive(game, (), 2))
    one = Expectiminimax(game, max_depth=1).choose(())
    interrupted = Expectiminimax(game, max_depth=2, max_nodes=one.nodes + 1).choose(())
    assert interrupted.completed_depth == 1
    assert interrupted.value == one.value
    fallback = Expectiminimax(game, max_nodes=1).choose(())
    assert fallback.completed_depth == 0
    assert fallback.value is None


def test_invalid_probability_rejected():
    game = MatrixGame([[[(0.9, 0)]]])
    with pytest.raises(ValueError, match="normalizada"):
        Expectiminimax(game).choose("root")
