import logging

import pytest
from poke_env.battle import Battle, DoubleBattle, Move, Pokemon
from poke_env.player.battle_order import DoubleBattleOrder, PassBattleOrder

from bot import VGCBot


@pytest.fixture
def bot():
    # Sem socket: valida a API real da versão fixada do poke-env.
    return VGCBot(start_listening=False)


@pytest.fixture
def battle():
    state = DoubleBattle("battle-test", "tester", logging.getLogger("test"), gen=9)
    state._player_role = "p1"
    state._opponent_role = "p2"
    state._active_pokemon = {
        "p1a": Pokemon(gen=9, species="charizard"),
        "p1b": Pokemon(gen=9, species="pikachu"),
    }
    state._opponent_active_pokemon = {
        "p2a": Pokemon(gen=9, species="venusaur"),
        "p2b": Pokemon(gen=9, species="blastoise"),
    }
    for mon in (*state._active_pokemon.values(), *state._opponent_active_pokemon.values()):
        mon.switch_in()
    state._available_moves = [
        [Move("flamethrower", gen=9), Move("protect", gen=9)],
        [Move("thunderbolt", gen=9), Move("tailwind", gen=9)],
    ]
    state._available_switches = [[Pokemon(gen=9, species="garchomp")]] * 2
    return state


def test_joint_legal_targets_and_shared_resources(bot, battle):
    battle._can_mega_evolve = [True, True]
    battle._can_tera = [True, True]  # Outro formato: request controla legalidade.
    orders = DoubleBattleOrder.join_orders(*battle.valid_orders)
    assert orders
    for order in orders:
        a, b = order.first_order, order.second_order
        assert not (a.mega and b.mega)
        assert not (a.terastallize and b.terastallize)
        assert not (isinstance(a.order, Pokemon) and a.order is b.order)
    chosen = bot.choose_move(battle)
    assert chosen in orders
    assert chosen.first_order.move_target == 1  # Flamethrower -> Venusaur.
    assert chosen.second_order.move_target == 2  # Thunderbolt -> Blastoise.


def test_both_forced_switch_one_reserve(bot, battle):
    battle._force_switch = [True, True]
    chosen = bot.choose_move(battle)
    singles = [chosen.first_order, chosen.second_order]
    assert sum(isinstance(s, PassBattleOrder) for s in singles) == 1
    assert sum(isinstance(s.order, Pokemon) for s in singles) == 1


def test_one_forced_switch_other_slot_passes(bot, battle):
    battle._force_switch = [False, True]
    chosen = bot.choose_move(battle)
    assert isinstance(chosen.first_order, PassBattleOrder)
    assert isinstance(chosen.second_order.order, Pokemon)


def test_spread_friendly_fire_penalized(bot, battle):
    battle._available_moves = [
        [Move("earthquake", gen=9), Move("earthpower", gen=9)],
        [Move("protect", gen=9)],
    ]
    battle._available_switches = [[], []]
    # Ally Pikachu é vulnerável a Ground; pressão de Earthquake inclui esse custo.
    assert bot.choose_move(battle).first_order.order.id == "earthpower"


def test_wait_and_wrong_battle_type(bot, battle):
    battle._wait = True
    assert bot.choose_move(battle).message == "/choose default"
    with pytest.raises(TypeError, match="duplas"):
        bot.choose_move(Battle("single", "tester", logging.getLogger("test"), gen=9))


def test_search_bridge_maps_back_to_legal_joint_order(bot, battle):
    from vgc.bridge import SearchPolicy
    from vgc.search import Outcome

    class OneTurnModel:
        def __init__(self, actions):
            self.legal = actions

        def actions(self, state, *, opponent):
            return ("response",) if opponent else self.legal

        def outcomes(self, state, ours, theirs):
            return (Outcome(1.0, 0.5 if ours == self.legal[-1] else -0.5),)

        def terminal(self, state):
            return state != "root"

        def evaluate(self, state):
            return state

    bot.policy = SearchPolicy(lambda _, orders: (OneTurnModel(orders), "root"), max_depth=1)
    orders = DoubleBattleOrder.join_orders(*battle.valid_orders)
    assert bot.choose_move(battle) == orders[-1]
    assert bot.policy.last_result.value == 0.5
