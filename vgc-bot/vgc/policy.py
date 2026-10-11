"""Política inicial executável: pressão heurística, NÃO busca com dano simulado.

Ela permite validar transporte/legalidade e obter um baseline mensurável enquanto
um backend Champions implementa BattleModel. Os escores não são HP nem P(vitória).
"""

from typing import Protocol

from poke_env.battle import DoubleBattle, Field, Move, Pokemon, SideCondition, Target
from poke_env.player.battle_order import DoubleBattleOrder, SingleBattleOrder


class Policy(Protocol):
    def choose(
        self, battle: DoubleBattle, orders: list[DoubleBattleOrder]
    ) -> DoubleBattleOrder: ...


class PressurePolicy:
    def choose(self, battle: DoubleBattle, orders: list[DoubleBattleOrder]) -> DoubleBattleOrder:
        # Cada ação individual aparece em muitos pares; calculá-la uma vez reduz
        # trabalho O(m*n*(custo de score)) para O((m+n)*custo + m*n).
        scores: dict[tuple[int, str], float] = {}
        for order in orders:
            for slot, single in enumerate((order.first_order, order.second_order)):
                key = (slot, single.message)
                if key not in scores:
                    scores[key] = self._score(battle, slot, single)

        def joint(order: DoubleBattleOrder) -> float:
            singles = (order.first_order, order.second_order)
            value = sum(scores[(i, single.message)] for i, single in enumerate(singles))
            # Proteger ambos sem dano residual é muitas vezes perder iniciativa.
            if all(isinstance(s.order, Move) and s.order.is_protect_move for s in singles):
                value -= 0.3
            return value

        return max(orders, key=joint)

    @staticmethod
    def _score(battle: DoubleBattle, slot: int, order: SingleBattleOrder) -> float:
        actor = battle.active_pokemon[slot]
        command = order.order
        foes = [p for p in battle.opponent_active_pokemon if p is not None and not p.fainted]
        if isinstance(command, Pokemon):
            # Troca avalia pressão defensiva de STAB, não sets supostamente conhecidos.
            def exposure(mon: Pokemon) -> float:
                return sum(max(mon.damage_multiplier(t) for t in foe.types) for foe in foes)

            if battle.force_switch[slot] or actor is None:
                return command.current_hp_fraction - 0.2 * exposure(command)
            return 0.15 * (exposure(actor) - exposure(command)) - 0.35
        if not isinstance(command, Move) or actor is None:
            return 0.0  # pass/default do protocolo.
        if command.is_protect_move:
            # Sem posterior comportamental esta é somente uma preferência pequena;
            # não alegamos prever Protect ou sua chance consecutiva de sucesso.
            return 0.08 * (1 - actor.current_hp_fraction) if actor.protect_counter == 0 else -0.2
        if command.id == "tailwind":
            return 0.45 if SideCondition.TAILWIND not in battle.side_conditions else -0.3
        if command.id == "trickroom":
            speed_gap = sum(
                (foe.base_stats["spe"] > actor.base_stats["spe"])
                - (foe.base_stats["spe"] < actor.base_stats["spe"])
                for foe in foes
            )
            return 0.2 * speed_gap * (-1 if Field.TRICK_ROOM in battle.fields else 1)
        if command.base_power <= 0:
            return 0.01  # Outros status exigem modelo de transição.
        targets: list[tuple[Pokemon, float]] = []
        if order.move_target > 0:
            target = battle.opponent_active_pokemon[order.move_target - 1]
            if target is not None:
                targets.append((target, 1.0))
        elif order.move_target < 0:
            target = battle.active_pokemon[-order.move_target - 1]
            if target is not None:
                targets.append((target, -1.0))
        elif command.target in (Target.ALL_ADJACENT, Target.ALL_ADJACENT_FOES):
            targets.extend((foe, 1.0) for foe in foes)
            ally = battle.active_pokemon[1 - slot]
            if command.target == Target.ALL_ADJACENT and ally is not None and not ally.fainted:
                targets.append((ally, -1.0))
        elif command.target == Target.RANDOM_NORMAL:
            targets.extend((foe, 1 / len(foes)) for foe in foes)
        # Precisão base multiplica pressão: isso não substitui a PMF de dano.
        stab = 1.5 if command.type in actor.types else 1.0
        pressure = command.base_power / 100 * command.accuracy * stab
        if command.target in (Target.ALL_ADJACENT, Target.ALL_ADJACENT_FOES) and len(targets) > 1:
            pressure *= 0.75
        # Mega/Tera são variantes LEGAIS enumeradas pelo poke-env. Sem simulação
        # da nova forma não há bônus inventado: empate prefere preservar o recurso.
        return pressure * sum(sign * target.damage_multiplier(command) for target, sign in targets)
