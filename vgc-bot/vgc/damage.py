"""Álgebra de dano exata DADOS rolls corretos; sem fórmula falsa de dano Gen 9.

Arredondamento em cada etapa, habilidade, item, clima, spread, crítico e regras
Champions pertencem ao backend. A interface aceita o contexto completo, não apenas
Attack/Defense. Não há implementação de simulador competitivo nesta base.
"""

from collections import defaultdict
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from math import fsum, isclose, isfinite
from typing import Protocol


class DamageCalculator(Protocol):
    def rolls(self, context: Hashable, *, critical: bool) -> tuple[int, ...]:
        """Retorna danos finais dos 16 rolls equiprováveis, condicionados a acertar.

        O contexto inclui mod/revisão, stats/boosts, habilidades, itens, campo,
        alvo, transformação e número real de alvos; serve também como chave de cache.
        Multihit exige distribuição própria de número de hits e rolls por hit.
        """
        ...


@dataclass(frozen=True, slots=True)
class DamageDistribution:
    mass: tuple[tuple[int, float], ...]

    def __post_init__(self) -> None:
        if not self.mass or any(
            not isinstance(d, int) or d < 0 or not isfinite(p) or p < 0 for d, p in self.mass
        ):
            raise ValueError("Danos inteiros não negativos e probabilidades finitas exigidos")
        if not isclose(fsum(p for _, p in self.mass), 1.0, abs_tol=1e-10, rel_tol=0):
            raise ValueError("A massa probabilística deve somar 1")

    @property
    def mean(self) -> float:
        return fsum(d * p for d, p in self.mass)

    def ko_probability(self, hp: int) -> float:
        if hp <= 0:
            raise ValueError("O alvo deve estar vivo")
        return fsum(p for d, p in self.mass if d >= hp)

    def independent_sum(self, other: "DamageDistribution") -> "DamageDistribution":
        """Convolução P(D1+D2=k), SOMENTE sob independência condicional.

        Não usar para Focus Sash, KO do atacante antes da ação, Protect compartilhado,
        redirecionamento ou mudança de alvo. Esses casos exigem simular o turno.
        """
        result: dict[int, float] = defaultdict(float)
        for d1, p1 in self.mass:
            for d2, p2 in other.mass:
                result[d1 + d2] += p1 * p2
        return DamageDistribution(tuple(sorted(result.items())))


def distribution(
    normal_rolls: Sequence[int],
    *,
    accuracy: float,
    critical_rolls: Sequence[int] | None = None,
    critical_probability: float = 0.0,
) -> DamageDistribution:
    """P(D=d)=(1-a)1[d=0]+a[(1-c)P(D=d|normal)+cP(D=d|crítico)].

    `accuracy` já deve incluir estágios, habilidades e campo; precisão base isolada
    é insuficiente. Críticos precisam de cálculo próprio: não basta multiplicar 1.5.
    Protect é uma ação do rival no modelo conjunto, não parte da precisão do golpe.
    """
    if not 0 <= accuracy <= 1 or not 0 <= critical_probability <= 1:
        raise ValueError("Precisão e chance de crítico devem estar em [0,1]")
    if critical_probability and critical_rolls is None:
        raise ValueError("Forneça rolls críticos quando sua probabilidade for positiva")
    result: dict[int, float] = defaultdict(float)
    result[0] = 1.0 - accuracy
    for rolls, chance in (
        (normal_rolls, 1 - critical_probability),
        (critical_rolls, critical_probability),
    ):
        if rolls is None:
            continue
        if len(rolls) != 16 or any(not isinstance(d, int) or d < 0 for d in rolls):
            raise ValueError("Forneça exatamente os 16 danos inteiros dos rolls 85..100")
        for damage in rolls:
            result[damage] += accuracy * chance / 16
    return DamageDistribution(tuple(sorted((d, p) for d, p in result.items() if p > 0)))
