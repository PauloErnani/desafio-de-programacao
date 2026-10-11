"""Heurística limitada, antissimétrica e independente do transporte WebSocket."""

from functools import lru_cache
from math import tanh

from poke_env.battle import PokemonType
from poke_env.data import GenData

from vgc.state import Board, Fighter, Side


@lru_cache(maxsize=4096)
def effectiveness(attack: PokemonType, defense: tuple[PokemonType, ...]) -> float:
    """Afinidade de tipos; habilidades e imunidades especiais cabem ao simulador."""
    return attack.damage_multiplier(
        defense[0],
        defense[1] if len(defense) == 2 else None,
        type_chart=GenData.from_gen(9).type_chart,
    )


def matchup(attacker: Fighter, defender: Fighter) -> float:
    # É uma feature de cobertura STAB, não dano: o melhor tipo pode não ter golpe.
    return max(effectiveness(t, defender.types) for t in attacker.types) / 4.0


def field_affinity(side: Side, weather: str, terrain: str) -> float:
    """Benefício aproximado do campo, condicionado aos membros ativos.

    Clima/terreno são compartilhados: não concedemos bônus simplesmente por existir
    chuva. A diferença entre os benefícios de cada lado entra na avaliação.
    Habilidades, itens, supressão de clima e efeitos defensivos ficam para o backend.
    """
    total = 0.0
    terrain_types = {
        "electricterrain": PokemonType.ELECTRIC,
        "grassyterrain": PokemonType.GRASS,
        "psychicterrain": PokemonType.PSYCHIC,
    }
    for mon in side.alive_active:
        sun = float(PokemonType.FIRE in mon.types) - float(PokemonType.WATER in mon.types)
        if weather == "sunnyday":
            total += 0.5 * sun
        elif weather == "raindance":
            total -= 0.5 * sun
        if mon.grounded and terrain_types.get(terrain) in mon.types:
            total += 0.3
    return total / 2.0


def evaluate(board: Board) -> float:
    """V(s) = tanh(1.6 H + 1.2 N + .5 T + .5 S + .3 F + .1 R).

    H: diferença de HP médio dos quatro selecionados; N: sobreviventes / 4;
    T: cobertura de tipos; S: fração líquida de confrontos de velocidade favoráveis;
    F: afinidade de campo; R: recurso de transformação preservado.

    Pesos são priors de engenharia para calibrar em dados, não uma solução ótima.
    tanh limita V em [-1,1], pré-condição das podas de expectativa. Terminais
    prevalecem sobre material: vencer com 1 HP continua valendo +1.
    """
    if board.outcome is not None:
        return float(board.outcome)
    ours, theirs = board.ours, board.theirs
    hp = (sum(m.hp for m in ours.team) - sum(m.hp for m in theirs.team)) / 4
    alive = (sum(m.hp > 0 for m in ours.team) - sum(m.hp > 0 for m in theirs.team)) / 4
    pairs = [(a, b) for a in ours.alive_active for b in theirs.alive_active]
    typing = speed = 0.0
    for a, b in pairs:
        typing += matchup(a, b) - matchup(b, a)
        a_speed = a.speed * (2 if ours.tailwind_turns else 1)
        b_speed = b.speed * (2 if theirs.tailwind_turns else 1)
        # Empates contribuem zero; Trick Room INVERTE o benefício do Tailwind.
        advantage = (a_speed > b_speed) - (a_speed < b_speed)
        speed += -advantage if board.trick_room_turns else advantage
    typing /= max(1, len(pairs))
    speed /= max(1, len(pairs))
    field = field_affinity(ours, board.weather, board.terrain) - field_affinity(
        theirs, board.weather, board.terrain
    )
    resource = float(ours.transformation_available) - float(theirs.transformation_available)
    return tanh(1.6 * hp + 1.2 * alive + 0.5 * typing + 0.5 * speed + 0.3 * field + 0.1 * resource)
