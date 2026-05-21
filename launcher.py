"""
Launcher script for running game automation with GUI or CLI.
Usage:
    python launcher.py <game_name> [--gui]

Examples:
    python launcher.py bd2          # Run BD2 in CLI mode
    python launcher.py bd2 --gui    # Run BD2 with Webview GUI
"""
import sys
import argparse
from pathlib import Path

# Add src to path
src_dir = Path(__file__).parent / 'src'
sys.path.insert(0, str(src_dir))

from src.games.bd2.bd2 import BD2
from src.games.cherrytale.cherrytale import CherryTale
from src.gui.webview_gui import run_with_webview, run_cli


# Registry of available games
GAMES = {
    'bd2': BD2,
    'cherrytale': CherryTale,
    # Add more games here as you create them
    # 'game_name': GameClass,
}


def list_games():
    """List all available games"""
    print("\nAvailable games:")
    print("-" * 40)
    for name in GAMES.keys():
        print(f"  - {name}")
    print("-" * 40)


def main():
    parser = argparse.ArgumentParser(
        description="Game Automation Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python launcher.py bd2          # Run BD2 in CLI mode
  python launcher.py bd2 --gui    # Run BD2 with Webview GUI
  python launcher.py --list       # List all available games
        """
    )
    
    parser.add_argument(
        'game',
        nargs='?',
        help='Name of the game to run'
    )
    parser.add_argument(
        '--gui',
        action='store_true',
        help='Run with Webview GUI interface'
    )
    parser.add_argument(
        '--list', '-l',
        action='store_true',
        help='List all available games'
    )
    
    args = parser.parse_args()
    
    # List games
    if args.list:
        list_games()
        return
    
    # Check game name
    if not args.game:
        print("Error: Please specify a game name or use --list")
        list_games()
        sys.exit(1)
    
    game_name = args.game.lower()
    
    if game_name not in GAMES:
        print(f"Error: Unknown game '{game_name}'")
        list_games()
        sys.exit(1)
    
    game_class = GAMES[game_name]
    
    # Run game
    try:
        if args.gui:
            print(f"Starting {game_name.upper()} with Webview GUI...")
            run_with_webview(game_class, f"{game_name.upper()} Automation")
        else:
            print(f"Starting {game_name.upper()} in CLI mode...")
            print("Press 'q' to stop\n")
            run_cli(game_class)
    except KeyboardInterrupt:
        print("\nStopped by user")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
