"""Player de duplas. Executar: python bot.py --help.

A rede assíncrona pertence ao poke-env; a política decide um PAR legal de ordens.
BattleModel/Expectiminimax são injetáveis por uma implementação de Policy.
"""

from poke_env.battle import AbstractBattle, DoubleBattle
from poke_env.player import Player
from poke_env.player.battle_order import BattleOrder, DoubleBattleOrder

from vgc.connection import DEFAULT_FORMAT
from vgc.policy import Policy, PressurePolicy


class VGCBot(Player):
    def __init__(self, *args, policy: Policy | None = None, **kwargs) -> None:
        kwargs.setdefault("battle_format", DEFAULT_FORMAT)
        self.policy = policy if policy is not None else PressurePolicy()
        super().__init__(*args, **kwargs)

    def choose_move(self, battle: AbstractBattle) -> BattleOrder:
        """Chamado a cada request, inclusive substituições após KO.

        valid_orders conhece PP, Disable, Taunt, trapping, alvos e force_switch.
        join_orders impede duas Megas/Teras ou trocar ambos para o mesmo reserva.
        Não assumir que sempre há dois Pokémon vivos ou duas ações de ataque.
        """
        if not isinstance(battle, DoubleBattle):
            raise TypeError("VGCBot aceita somente batalhas em duplas")
        if battle.wait:
            return self.choose_default_move()
        orders = DoubleBattleOrder.join_orders(*battle.valid_orders)
        if not orders:
            return self.choose_default_move()
        selected = self.policy.choose(battle, orders)
        if selected not in orders:
            raise ValueError("A política retornou um par ausente das ações legais")
        return selected


if __name__ == "__main__":
    # Import tardio evita que o módulo de conexão importe uma segunda cópia de bot.
    from vgc.connection import main

    main(VGCBot)
