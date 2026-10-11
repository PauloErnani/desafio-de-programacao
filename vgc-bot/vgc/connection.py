"""Configuração de conexão; senhas apenas em variável de ambiente."""

import argparse
import asyncio
import os
from pathlib import Path

from poke_env.player import Player
from poke_env.ps_client import (
    AccountConfiguration,
    LocalhostServerConfiguration,
    ShowdownServerConfiguration,
)

DEFAULT_FORMAT = "gen9championsvgc2026regmc"


def main(player_class: type[Player]) -> None:
    parser = argparse.ArgumentParser(description="Bot inicial VGC: pressão heurística em duplas")
    parser.add_argument("--team", type=Path, required=True, help="Export Showdown do time de seis")
    parser.add_argument("--format", default=DEFAULT_FORMAT)
    parser.add_argument("--server", choices=("local", "showdown"), default="local")
    parser.add_argument("--username", help="Conta; senha opcional em SHOWDOWN_PASSWORD")
    parser.add_argument("--opponent", required=True, help="Conta da qual aceitar desafios")
    parser.add_argument("--battles", type=int, default=1)
    args = parser.parse_args()
    if "vgc" not in args.format.lower():
        parser.error("Este projeto aceita apenas formatos VGC; use o ID do Showdown")
    if args.battles <= 0:
        parser.error("--battles deve ser positivo")
    if not args.team.is_file():
        parser.error("Arquivo --team não encontrado")
    if os.environ.get("SHOWDOWN_PASSWORD") and not args.username:
        parser.error("Informe --username para usar SHOWDOWN_PASSWORD")

    async def run() -> None:
        player = player_class(
            account_configuration=(
                AccountConfiguration(args.username, os.environ.get("SHOWDOWN_PASSWORD"))
                if args.username
                else None
            ),
            battle_format=args.format,
            team=args.team.read_text(encoding="utf-8"),
            server_configuration=(
                LocalhostServerConfiguration
                if args.server == "local"
                else ShowdownServerConfiguration
            ),
            max_concurrent_battles=1,
            accept_open_team_sheet=True,
        )
        try:
            await player.accept_challenges(args.opponent, n_challenges=args.battles)
        finally:
            await player.ps_client.stop_listening()

    asyncio.run(run())
