"""Expectiminimax de ações conjuntas, com poda por limites de expectativa.

Cada a=(a1,a2) e b=(b1,b2) é escolhido ANTES de resolver o turno. A enumeração
MAX/MIN calcula a garantia max_a min_b E[V], sem dar ao rival observação da ação.
Ela é conservadora e só cobre estratégias puras. Equilíbrio misto exige resolver
a matriz de pagamentos (programação linear), descrito no README.
"""

from collections.abc import Hashable
from dataclasses import dataclass
from math import fsum, isclose, isfinite
from time import monotonic
from typing import Protocol


@dataclass(frozen=True, slots=True)
class Outcome[S]:
    probability: float
    state: S


class BattleModel[S: Hashable, A: Hashable](Protocol):
    """Contrato para simulador + crença. Não usar DoubleBattle mutável como estado.

    S deve ser um estado de informação/crença: a mesma ação é escolhida em todas
    as hipóteses indistinguíveis. Inclua turnos de campo, PP, Protect consecutivo,
    boosts, recursos, sets hipotéticos e histórico relevante na chave do estado.
    """

    def actions(self, state: S, *, opponent: bool) -> tuple[A, ...]: ...

    def outcomes(self, state: S, ours: A, theirs: A) -> tuple[Outcome[S], ...]:
        """Resolve AS QUATRO ações e agrupa sucessores equivalentes.

        Trocas, transformação, prioridade, velocidade dinâmica, speed ties,
        Protect, redirecionamento, precisão, rolls, críticos, efeitos secundários
        e fim de turno pertencem ao backend. Probabilidades devem somar 1.
        Reposições forçadas são fases explícitas; não consumem um turno de ataque.
        """
        ...

    def evaluate(self, state: S) -> float:
        """Valor finito em [-1,1], da perspectiva fixa do bot."""
        ...

    def terminal(self, state: S) -> bool: ...


class SearchLimit(Exception):
    """Orçamento cooperativo atingido; preservar a última profundidade completa."""


@dataclass(frozen=True, slots=True)
class SearchResult[A]:
    action: A
    value: float | None  # None: nenhum nível terminou; ação de fallback.
    completed_depth: int
    nodes: int
    cutoffs: int


class Expectiminimax[S: Hashable, A: Hashable]:
    def __init__(
        self,
        model: BattleModel[S, A],
        *,
        max_depth: int = 2,
        seconds: float = 1.0,
        max_nodes: int = 100_000,
    ) -> None:
        if max_depth < 1 or not isfinite(seconds) or seconds <= 0 or max_nodes < 1:
            raise ValueError("Profundidade, tempo e nós devem ser positivos")
        self.model = model
        self.max_depth = max_depth
        self.seconds = seconds
        self.max_nodes = max_nodes
        self.nodes = self.cutoffs = 0
        self.deadline = 0.0
        self.cache: dict[tuple[S, int], tuple[float, A | None]] = {}

    def choose(self, state: S) -> SearchResult[A]:
        if self.model.terminal(state):
            raise ValueError("Estado terminal não admite decisão")
        self.nodes = self.cutoffs = 0
        self.cache.clear()
        self.deadline = monotonic() + self.seconds
        actions = self.model.actions(state, opponent=False)
        if not actions:
            raise ValueError("Estado não terminal deve fornecer ao menos uma ação legal")
        best = SearchResult(actions[0], None, 0, 0, 0)
        for depth in range(1, self.max_depth + 1):
            try:
                value, action = self._value(state, depth)
            except SearchLimit:
                break
            assert action is not None
            best = SearchResult(action, value, depth, self.nodes, self.cutoffs)
        return SearchResult(best.action, best.value, best.completed_depth, self.nodes, self.cutoffs)

    def _tick(self) -> None:
        if self.nodes >= self.max_nodes or monotonic() >= self.deadline:
            raise SearchLimit
        self.nodes += 1

    def _value(self, state: S, depth: int) -> tuple[float, A | None]:
        self._tick()
        key = (state, depth)
        if key in self.cache:
            return self.cache[key]
        if depth == 0 or self.model.terminal(state):
            value = self.model.evaluate(state)
            if not isfinite(value) or not -1 <= value <= 1:
                raise ValueError("Avaliação fora dos limites usados na poda")
            return value, None
        ours = self.model.actions(state, opponent=False)
        theirs = self.model.actions(state, opponent=True)
        if not ours or not theirs:
            raise ValueError("Modele pass/reposições como ações explícitas")
        alpha, best_action = -1.0, ours[0]
        for action in ours:
            beta = 1.0  # Menor pagamento desta linha, dado o pior par adversário.
            for response in theirs:
                outcomes = self.model.outcomes(state, action, response)
                probabilities = [o.probability for o in outcomes]
                if (
                    not outcomes
                    or any(not isfinite(p) or p < 0 for p in probabilities)
                    or not isclose(fsum(probabilities), 1, rel_tol=0, abs_tol=1e-10)
                ):
                    raise ValueError("Transições devem formar uma distribuição normalizada")
                partial = mass = 0.0
                rejected = False
                for outcome in outcomes:
                    if outcome.probability == 0:
                        continue
                    # Cada filho probabilístico precisa de valor EXATO. Propagar
                    # alpha/beta do pai aqui como no minimax clássico seria incorreto.
                    value, _ = self._value(outcome.state, depth - 1)
                    partial += outcome.probability * value
                    mass += outcome.probability
                    upper = partial + max(0.0, 1.0 - mass)  # U=+1 para massa restante.
                    if upper <= alpha:
                        self.cutoffs += 1
                        rejected = True
                        break
                if rejected:
                    # Existe uma resposta cujo EV não supera a ação incumbente.
                    # Basta para eliminar a linha; não armazenar `partial` como EV.
                    break
                beta = min(beta, partial)
                if beta <= alpha:
                    self.cutoffs += 1
                    break
            else:
                # Só uma linha completamente avaliada pode melhorar o incumbente.
                if beta > alpha:
                    alpha, best_action = beta, action
        # Linhas cortadas não podem melhorar alpha. Logo o máximo é exato; apenas
        # resultados completos entram no cache, jamais buscas interrompidas.
        self.cache[key] = (alpha, best_action)
        return alpha, best_action
