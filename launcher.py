"""
Game Automation Launcher.

Auto-discovers games under ``src/games/<name>/<name>.py`` and exposes them via
both an interactive menu (no args) and explicit CLI flags.

Usage:
    python launcher.py                       # Interactive menu
    python launcher.py --list                # List available games
    python launcher.py <game>                # Run a game in CLI mode
    python launcher.py <game> --gui          # Run a game with the webview GUI

Examples:
    python launcher.py bd2
    python launcher.py bd2 --gui
    python launcher.py cherrytale
"""
from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Dict, Optional, Type

# Make ``src/`` importable when running this script directly.
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.utils import log_error, log_info, log_success, log_warning  # noqa: E402


def scan_games() -> Dict[str, Dict[str, str]]:
    """Discover available games under ``src/games``.

    A game is any directory ``src/games/<name>/`` that contains a
    ``<name>.py`` module file. The ``template`` directory is skipped.
    """
    games_dir = _PROJECT_ROOT / "src" / "games"
    games: Dict[str, Dict[str, str]] = {}
    if not games_dir.exists():
        log_error(f"Games directory not found: {games_dir}")
        return games

    for item in sorted(games_dir.iterdir()):
        if not item.is_dir() or item.name.startswith("__") or item.name == "template":
            continue
        game_file = item / f"{item.name}.py"
        if not game_file.exists():
            continue
        games[item.name] = {
            "module_path": f"src.games.{item.name}.{item.name}",
            "display_name": item.name.upper(),
        }
    return games


def load_game_class(game_info: Dict[str, str]) -> Optional[Type]:
    """Load the game class named after the game directory (case-insensitive)."""
    try:
        module = importlib.import_module(game_info["module_path"])
    except Exception as e:
        log_error(f"Could not import {game_info['module_path']}: {e}", exc_info=True)
        return None

    target = game_info["display_name"].lower()
    for attr in dir(module):
        if attr.lower() == target:
            return getattr(module, attr)
    log_error(f"No class matching '{target}' found in {game_info['module_path']}")
    return None


def _run_cli(game_class: Type) -> None:
    game = game_class()
    game.start()


def _run_gui(game_class: Type, title: str) -> None:
    # Import lazily so the launcher works in CLI-only environments.
    from src.gui.webview_gui import run_with_webview
    run_with_webview(game_class, title)


def run_game(game_class: Type, title: str, gui: bool) -> None:
    try:
        if gui:
            log_success(f"Starting {title} with Webview GUI...")
            _run_gui(game_class, title)
        else:
            log_success(f"Starting {title} (CLI). Press 'q' to stop.")
            _run_cli(game_class)
    except KeyboardInterrupt:
        log_info("Stopped by user")
    except Exception as e:
        log_error(f"Error running automation: {e}", exc_info=True)
    finally:
        log_info("Automation ended")


def list_games(games: Dict[str, Dict[str, str]]) -> None:
    print("\nAvailable games:")
    print("-" * 40)
    if not games:
        print("  (none)")
    else:
        for name, info in games.items():
            print(f"  - {name}  ({info['display_name']})")
    print("-" * 40)


def interactive_menu(games: Dict[str, Dict[str, str]]) -> None:
    if not games:
        log_error("No games found in src/games. Add a game directory and try again.")
        return

    while True:
        print("\n" + "=" * 50)
        print("       ADB GAME AUTOMATION")
        print("=" * 50)
        print("\nAvailable games:")
        print("-" * 50)
        names = list(games.keys())
        for idx, name in enumerate(names, 1):
            print(f"  {idx}. {games[name]['display_name']}")
        print("-" * 50)
        print("  0. Exit")
        print("=" * 50)

        try:
            choice = input("\nSelect a game (number, append 'g' for GUI, e.g. '1g'): ").strip()
        except (KeyboardInterrupt, EOFError):
            log_info("\nExiting...")
            return

        if choice == "0":
            log_info("Exiting...")
            return

        gui = choice.lower().endswith("g")
        if gui:
            choice = choice[:-1]

        try:
            idx = int(choice) - 1
        except ValueError:
            log_warning("Please enter a valid number.")
            continue
        if not 0 <= idx < len(names):
            log_warning("Invalid choice. Please try again.")
            continue

        info = games[names[idx]]
        game_class = load_game_class(info)
        if game_class is None:
            log_error(f"Failed to load {info['display_name']}")
            continue
        run_game(game_class, f"{info['display_name']} Automation", gui)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Game Automation Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python launcher.py                  # Interactive menu\n"
            "  python launcher.py --list           # List games\n"
            "  python launcher.py bd2              # Run BD2 in CLI mode\n"
            "  python launcher.py bd2 --gui        # Run BD2 with GUI\n"
        ),
    )
    parser.add_argument("game", nargs="?", help="Name of the game to run")
    parser.add_argument("--gui", action="store_true", help="Run with the webview GUI")
    parser.add_argument("--list", "-l", action="store_true", help="List available games")
    args = parser.parse_args()

    games = scan_games()

    if args.list:
        list_games(games)
        return 0

    if not args.game:
        # No game specified: interactive menu.
        interactive_menu(games)
        return 0

    name = args.game.lower()
    if name not in games:
        log_error(f"Unknown game '{args.game}'.")
        list_games(games)
        return 1

    info = games[name]
    game_class = load_game_class(info)
    if game_class is None:
        return 1
    run_game(game_class, f"{info['display_name']} Automation", args.gui)
    return 0


if __name__ == "__main__":
    sys.exit(main())
