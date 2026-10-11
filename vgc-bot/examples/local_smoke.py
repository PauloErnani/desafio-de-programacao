"""Uma partida de integração local; não é benchmark de força competitiva.

Com servidor em localhost:8000 e noguestsecurity=true:
    python examples/local_smoke.py
"""

import asyncio
from pathlib import Path

from poke_env.player import RandomPlayer
from poke_env.ps_client import LocalhostServerConfiguration

from bot import VGCBot
from vgc.connection import DEFAULT_FORMAT


async def main() -> None:
    team = Path(__file__).with_name("team.txt").read_text(encoding="utf-8")
    config = dict(
        battle_format=DEFAULT_FORMAT,
        team=team,
        server_configuration=LocalhostServerConfiguration,
        accept_open_team_sheet=True,
    )
    bot, opponent = VGCBot(**config), RandomPlayer(**config)
    try:
        await asyncio.wait_for(bot.battle_against(opponent, n_battles=1), timeout=90)
        assert bot.n_finished_battles == opponent.n_finished_battles == 1
        battle = next(iter(bot.battles.values()))
        assert battle.turn > 0
        print(f"PASS: {DEFAULT_FORMAT}, {battle.turn} turnos, batalha concluída")
    finally:
        await asyncio.gather(bot.ps_client.stop_listening(), opponent.ps_client.stop_listening())


if __name__ == "__main__":
    asyncio.run(main())
