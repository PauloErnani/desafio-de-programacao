"""Estado imutável de uma hipótese; nunca inventar stats ocultos como observações.

O backend de simulação deve produzir estes snapshots após resolver o turno.
Uma crença contém várias hipóteses sobre os quatro membros selecionados pelo rival.
"""

from dataclasses import dataclass
from math import isfinite

from poke_env.battle import PokemonType


@dataclass(frozen=True, slots=True)
class Fighter:
    hp: float  # Fração de HP em [0, 1], zero implica nocaute.
    types: tuple[PokemonType, ...]
    speed: float  # Stat efetivo COM boosts/paralisia, SEM Tailwind/Trick Room.
    grounded: bool = True  # O simulador resolve Levitate, Air Balloon, Gravity etc.

    def __post_init__(self) -> None:
        if not isfinite(self.hp) or not 0 <= self.hp <= 1:
            raise ValueError("HP deve ser uma fração finita entre 0 e 1")
        if not isfinite(self.speed) or self.speed <= 0:
            raise ValueError("Speed deve ser finita e positiva")
        if not 1 <= len(self.types) <= 2:
            raise ValueError("O snapshot requer um ou dois tipos defensivos")


@dataclass(frozen=True, slots=True)
class Side:
    team: tuple[Fighter, ...]  # Quatro selecionados, incluindo os já nocauteados.
    active: tuple[int, ...]  # Índices nos slots ativos, até dois.
    tailwind_turns: int = 0
    transformation_available: bool = False

    def __post_init__(self) -> None:
        if len(self.team) != 4:
            raise ValueError("VGC requer snapshots dos quatro Pokémon selecionados")
        if len(self.active) > 2 or len(set(self.active)) != len(self.active):
            raise ValueError("Slots ativos duplicados ou em excesso")
        if any(i < 0 or i >= len(self.team) for i in self.active):
            raise ValueError("Índice ativo fora do time")
        if self.tailwind_turns < 0:
            raise ValueError("Duração de Tailwind negativa")

    @property
    def alive_active(self) -> tuple[Fighter, ...]:
        return tuple(self.team[i] for i in self.active if self.team[i].hp > 0)


@dataclass(frozen=True, slots=True)
class Board:
    ours: Side
    theirs: Side
    weather: str = ""  # sunnyday, raindance, sandstorm, snow...
    terrain: str = ""  # electricterrain, grassyterrain, psychicterrain...
    trick_room_turns: int = 0
    outcome: int | None = None  # +1 vitória, -1 derrota, 0 empate; None não terminal.

    def __post_init__(self) -> None:
        if self.outcome not in (None, -1, 0, 1) or self.trick_room_turns < 0:
            raise ValueError("Resultado ou duração de Trick Room inválido")
