"""Ponto explícito de integração entre observação poke-env e simulador futuro."""

from collections.abc import Callable, Hashable

from poke_env.battle import DoubleBattle
from poke_env.player.battle_order import DoubleBattleOrder

from vgc.search import BattleModel, Expectiminimax, SearchResult


class SearchPolicy[S: Hashable]:
    """O builder transforma a observação em crença imutável e modelo de transição.

    Ações na raiz usam `order.message` como ID. O backend não pode ler o time
    privado do adversário no servidor. Os descendentes geram suas próprias ações.
    Esta ponte síncrona serve a protótipos de busca curta; para buscas pesadas,
    prepare o snapshot no loop e execute o motor em um pool de processos, com
    deadline dentro do worker. Cancelar só o await não encerra trabalho CPU.
    """

    def __init__(
        self,
        build: Callable[[DoubleBattle, tuple[str, ...]], tuple[BattleModel[S, str], S]],
        *,
        seconds: float = 0.1,
        max_depth: int = 2,
    ) -> None:
        self.build = build
        self.seconds = seconds
        self.max_depth = max_depth
        self.last_result: SearchResult[str] | None = None

    def choose(self, battle: DoubleBattle, orders: list[DoubleBattleOrder]) -> DoubleBattleOrder:
        by_message = {order.message: order for order in orders}
        model, state = self.build(battle, tuple(by_message))
        if set(model.actions(state, opponent=False)) != set(by_message):
            raise ValueError("O modelo deve preservar todas as ações legais na raiz")
        result = Expectiminimax(model, seconds=self.seconds, max_depth=self.max_depth).choose(state)
        self.last_result = result
        return by_message[result.action]
