"""Atualização Bayesiana sobre hipóteses conjuntas de sets e seleção adversária."""

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from math import exp, fsum, isfinite, log


@dataclass(frozen=True, slots=True)
class Belief[H: Hashable]:
    hypotheses: tuple[H, ...]
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.hypotheses or len(self.hypotheses) != len(self.weights):
            raise ValueError("Hipóteses e pesos devem ter o mesmo tamanho não nulo")
        if any(not isfinite(p) or p < 0 for p in self.weights):
            raise ValueError("Pesos devem ser finitos e não negativos")
        if abs(fsum(self.weights) - 1) > 1e-10:
            raise ValueError("Pesos devem somar 1")

    def update(self, likelihood: Callable[[H], float]) -> "Belief[H]":
        """P(h|o) ∝ P(o|h)P(h); log-sum-exp evita underflow no produto.

        Dano observado é um intervalo por arredondamento de HP. A verossimilhança
        soma os rolls compatíveis; ordem de ação restringe Speed após prioridade.
        OTS fixa moves/itens/habilidades revelados, sem revelar escolhas futuras.
        """
        logs = []
        for hypothesis, prior in zip(self.hypotheses, self.weights, strict=True):
            p = likelihood(hypothesis)
            if not isfinite(p) or not 0 <= p <= 1:
                raise ValueError("Verossimilhança inválida")
            logs.append(log(prior) + log(p) if prior > 0 and p > 0 else float("-inf"))
        shift = max(logs)
        if shift == float("-inf"):
            raise ValueError("Observação fora do suporte: amplie as hipóteses explicitamente")
        weights = tuple(exp(value - shift) for value in logs)
        total = fsum(weights)
        return Belief(self.hypotheses, tuple(w / total for w in weights))
