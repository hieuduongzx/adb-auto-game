import os
import sys
import importlib
from pathlib import Path

# Add src directory to Python path
src_dir = Path(__file__).parent / 'src'
sys.path.append(str(src_dir))

from utils import log_error, log_info, log_success, log_warning


def scan_games():
    """Scan src/games directory to find available games."""
    games_dir = Path(__file__).parent / 'src' / 'games'
    games = {}
    
    if not games_dir.exists():
        log_error(f"Games directory not found: {games_dir}")
        return games
    
    # Scan for game directories (excluding __pycache__ and files)
    for item in games_dir.iterdir():
        if item.is_dir() and not item.name.startswith('__') and item.name != 'template':
            game_name = item.name
            # Check if the game has a main module file
            game_file = item / f"{game_name}.py"
            if game_file.exists():
                games[game_name] = {
                    'module_path': f"src.games.{game_name}.{game_name}",
                    'display_name': game_name.upper(),
                    'class_name': None  # Will be determined on import
                }
                log_info(f"Found game: {game_name}")
    
    return games


def load_game_class(game_info):
    """Load the game class when user selects it."""
    try:
        module = importlib.import_module(game_info['module_path'])
        game_name = game_info['display_name'].lower()
        
        # Look for a class with the same name as the directory (case-insensitive match)
        class_name = None
        for attr_name in dir(module):
            if attr_name.lower() == game_name:
                class_name = attr_name
                break
        
        if class_name:
            return getattr(module, class_name)
        else:
            log_error(f"Could not find game class in module")
            return None
            
    except Exception as e:
        log_error(f"Could not load game module: {e}")
        return None


def display_menu(games):
    """Display game selection menu."""
    print("\n" + "=" * 50)
    print("       ADB GAME AUTOMATION")
    print("=" * 50)
    print("\nAvailable games:")
    print("-" * 50)
    
    game_list = list(games.keys())
    for idx, game_name in enumerate(game_list, 1):
        print(f"  {idx}. {games[game_name]['display_name']}")
    
    print("-" * 50)
    print(f"  0. Exit")
    print("=" * 50)
    
    return game_list


def run_game(game_class):
    """Run the selected game automation."""
    try:
        game = game_class()
        game.start()
    except KeyboardInterrupt:
        log_info("Automation stopped by user")
    except Exception as e:
        log_error(f"Error running automation: {e}", exc_info=True)
    finally:
        log_info("Automation ended")


def main():
    log_success("Starting Game Automation Launcher")
    
    # Scan for available games
    games = scan_games()
    
    if not games:
        log_error("No games found in src/games directory")
        return
    
    while True:
        # Display menu and get user choice
        game_list = display_menu(games)
        
        try:
            choice = input("\nSelect a game (number): ").strip()
            
            if choice == '0':
                log_info("Exiting...")
                break
            
            choice_idx = int(choice) - 1
            if 0 <= choice_idx < len(game_list):
                selected_game = game_list[choice_idx]
                game_info = games[selected_game]
                
                # Load the game class only when selected
                game_class = load_game_class(game_info)
                if game_class:
                    log_success(f"Starting {game_info['display_name']} automation")
                    run_game(game_class)
                else:
                    log_error(f"Failed to load {game_info['display_name']}")
            else:
                log_warning("Invalid choice. Please try again.")
        
        except ValueError:
            log_warning("Please enter a valid number.")
        except KeyboardInterrupt:
            log_info("\nExiting...")
            break


if __name__ == "__main__":
    main()
