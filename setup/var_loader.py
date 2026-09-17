"""
Load customer-specific variables from .var files.

Scripts that require customer variables define them in .var files (INI format).
This module handles:
  - Checking for existing .var file
  - Creating from .var.EXAMPLE if missing
  - Prompting user for interactive entry or manual editing
  - Validating and returning loaded variables
"""

import os
import sys
import configparser
from pathlib import Path
from setup.prompt_utils import prompt_yes_no


def get_var_file_path(script_name):
    """
    Get the path to the .var file for a script.

    Args:
        script_name: Script name (e.g., 'check_router_mem_status.py')

    Returns:
        Path object for the .var file in .var/ directory
    """
    script_base = Path(script_name).stem
    project_root = Path(__file__).parent.parent
    var_dir = project_root / ".var"
    return var_dir / f"{script_base}.var"


def get_var_example_path(script_name):
    """
    Get the path to the .var.EXAMPLE file for a script.

    Args:
        script_name: Script name (e.g., 'check_router_mem_status.py')

    Returns:
        Path object for the .var.EXAMPLE file in .var/examples/ directory
    """
    script_base = Path(script_name).stem
    project_root = Path(__file__).parent.parent
    example_dir = project_root / ".var" / "examples"
    return example_dir / f"{script_base}.var.EXAMPLE"


def load_var_file(var_file_path):
    """
    Load variables from a .var file (INI format).

    Args:
        var_file_path: Path to the .var file

    Returns:
        Dict of variables, or None if file doesn't exist
    """
    if not var_file_path.exists():
        return None

    config = configparser.ConfigParser()
    config.read(var_file_path)

    if not config.has_section('variables'):
        return None

    return dict(config.items('variables'))


def show_variables_page(variables, page=0, items_per_page=9):
    """
    Display one page of variables as a numbered menu.

    Args:
        variables: Dict of variables
        page: Current page number (0-indexed)
        items_per_page: Number of items per page

    Returns:
        Tuple of (displayed_items, total_pages, current_page)
        where displayed_items is list of (menu_num, key, value) tuples
    """
    items = list(variables.items())
    total_pages = (len(items) + items_per_page - 1) // items_per_page

    # Clamp page to valid range
    if page >= total_pages:
        page = total_pages - 1
    if page < 0:
        page = 0

    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = items[start_idx:end_idx]

    displayed = []
    for i, (key, value) in enumerate(page_items, 1):
        displayed.append((i, key, value))

    return displayed, total_pages, page


def edit_variable(variables, key, current_value):
    """
    Prompt user to edit a single variable.

    Args:
        variables: Dict of variables (will be modified in-place)
        key: Variable name to edit
        current_value: Current value
    """
    print(f"\n{'='*80}")
    print(f"Edit: {key}")
    print(f"{'='*80}")
    print(f"Current value: {current_value}")
    new_value = input(f"New value [{current_value}]: ").strip()

    if new_value:
        variables[key] = new_value
        print(f"✓ Updated: {key} = {new_value}")
    else:
        print(f"✓ Unchanged: {key} = {current_value}")


def display_variables_menu(variables, var_file_path, page=0):
    """
    Display interactive menu for editing variables.

    Args:
        variables: Dict of variables (will be modified in-place)
        var_file_path: Path to the .var file (for display)
        page: Starting page number

    Returns:
        True if user saved (pressed 'x'), False if user canceled
    """
    items_per_page = 9

    while True:
        displayed, total_pages, current_page = show_variables_page(
            variables, page, items_per_page
        )

        print(f"\n{'='*80}")
        print(f"Customer Variables - {var_file_path}")
        if total_pages > 1:
            print(f"Page {current_page + 1}/{total_pages}")
        print(f"{'='*80}\n")

        for menu_num, key, value in displayed:
            print(f"  {menu_num}. {key:30} = {value}")

        print()
        if total_pages > 1:
            print("  n - next page")
            print("  p - previous page")
        print("  x - save and exit")
        print()

        choice = input("Select variable to edit (1-9), or command (n/p/x): ").strip().lower()

        if choice == 'x':
            return True
        elif choice == 'n' and total_pages > 1:
            if current_page < total_pages - 1:
                page = current_page + 1
            continue
        elif choice == 'p' and total_pages > 1:
            if current_page > 0:
                page = current_page - 1
            continue
        elif choice.isdigit():
            selection = int(choice)
            if 1 <= selection <= len(displayed):
                _, key, current_value = displayed[selection - 1]
                edit_variable(variables, key, current_value)
                page = current_page  # Stay on same page after edit
            else:
                print(f"Invalid selection: {selection}")
        else:
            print(f"Invalid choice: {choice}")


def validate_variables_with_user(variables, var_file_path, skip_prompts=False):
    """
    Display loaded variables and ask if they are correct.
    If not, allow user to edit via interactive menu.

    Args:
        variables: Dict of loaded variables (will be modified if user edits)
        var_file_path: Path to the .var file (for display)
        skip_prompts: If True, skip validation prompt and accept defaults

    Returns:
        True if user confirmed or finished editing, False if user canceled
    """
    print(f"\n{'='*80}")
    print(f"Customer Variables Loaded from: {var_file_path}")
    print(f"{'='*80}\n")

    for key, value in variables.items():
        print(f"  {key} = {value}")

    print()

    if skip_prompts:
        print("Using default variables (skip prompts mode)\n")
        return True

    response = prompt_yes_no("Are these values correct?", default=True)

    if response:
        return True
    else:
        # User wants to edit, show interactive menu
        print("\nEntering edit mode...\n")
        return display_variables_menu(variables, var_file_path)


def create_var_file_interactive(script_name, example_path, var_file_path, logger=None, skip_prompts=False):
    """
    Guide user through creating a .var file from the example.

    Args:
        script_name: Script name for display
        example_path: Path to the .var.EXAMPLE file
        var_file_path: Path where to create the .var file
        logger: Optional logger for recording actions
        skip_prompts: If True, use example values without prompting

    Returns:
        Dict of variables, or None if user cancels
    """
    print(f"\n{'='*80}")
    print("Customer Variables Configuration")
    print(f"{'='*80}")
    print(f"No .var file found for {script_name}")
    print(f"\nExample file location: {example_path}\n")

    if not example_path.exists():
        print(f"ERROR: Example file not found at {example_path}")
        if logger:
            logger.error(f"var_loader: example file not found at {example_path}")
        return None

    # Read example file to show structure
    example_config = configparser.ConfigParser()
    example_config.read(example_path)

    if not example_config.has_section('variables'):
        print("ERROR: Example file has no [variables] section")
        if logger:
            logger.error(f"var_loader: example file missing [variables] section")
        return None

    example_vars = dict(example_config.items('variables'))

    if skip_prompts:
        # Use example values directly without prompting
        print("Using default variables from example (skip prompts mode)")
        print("\nDefault variables:")
        for key, value in example_vars.items():
            print(f"  {key} = {value}")

        save_var_file(example_vars, var_file_path, logger)
        print(f"\n✓ Variables saved to: {var_file_path}\n")
        if logger:
            logger.info(f"var_loader: created .var file from example (skip prompts mode) at {var_file_path}")
        return example_vars

    print("Example variables:")
    for key, value in example_vars.items():
        print(f"  {key} = {value}")

    print(f"\n{'='*80}")
    print("How would you like to set up your variables?")
    print("1. Enter values interactively (prompted for each variable)")
    print("2. Edit the .var file manually (opens for editing)")
    print(f"{'='*80}\n")

    choice = input("Select (1 or 2) [default: 1]: ").strip() or "1"

    if choice == "1":
        # Interactive mode
        return prompt_for_variables_interactive(script_name, example_vars, var_file_path, logger)
    elif choice == "2":
        # Manual mode
        create_var_file_from_example(example_path, var_file_path, logger)
        print(f"\nPlease edit the .var file at:")
        print(f"  {var_file_path}")
        print(f"\nRun the script again after editing.")
        if logger:
            logger.info(f"var_loader: user chose manual edit mode. Created .var file at {var_file_path}")
        return None
    else:
        print("Invalid choice")
        return None


def prompt_for_variables_interactive(script_name, example_vars, var_file_path, logger=None):
    """
    Prompt user for each variable value interactively.

    Args:
        script_name: Script name for display
        example_vars: Dict of example variables
        var_file_path: Path where to save the .var file
        logger: Optional logger

    Returns:
        Dict of entered variables
    """
    print(f"\n{'='*80}")
    print(f"Enter values for {script_name} customer variables")
    print(f"{'='*80}\n")

    variables = {}
    for key, default_value in example_vars.items():
        prompt_text = f"{key} [{default_value}]: "
        user_input = input(prompt_text).strip()
        variables[key] = user_input if user_input else default_value

    # Save to .var file
    save_var_file(variables, var_file_path, logger)

    print(f"\n✓ Variables saved to: {var_file_path}\n")
    if logger:
        logger.info(f"var_loader: saved .var file at {var_file_path}")

    return variables


def create_var_file_from_example(example_path, var_file_path, logger=None):
    """
    Create a .var file as a copy of the example file.

    Args:
        example_path: Path to the .var.EXAMPLE file
        var_file_path: Path where to create the .var file
        logger: Optional logger
    """
    # Ensure .var directory exists
    var_file_path.parent.mkdir(parents=True, exist_ok=True)

    # Copy example to .var file
    with open(example_path, 'r') as src:
        content = src.read()

    with open(var_file_path, 'w') as dst:
        dst.write(content)

    if logger:
        logger.debug(f"var_loader: created .var file from example at {var_file_path}")


def save_var_file(variables, var_file_path, logger=None):
    """
    Save variables to a .var file in INI format.

    Args:
        variables: Dict of variables to save
        var_file_path: Path where to save the .var file
        logger: Optional logger
    """
    var_file_path.parent.mkdir(parents=True, exist_ok=True)

    config = configparser.ConfigParser()
    config['variables'] = variables

    with open(var_file_path, 'w') as f:
        config.write(f)

    if logger:
        logger.debug(f"var_loader: saved .var file at {var_file_path}")


def load_customer_variables(script_name, logger=None, skip_prompts=False):
    """
    Load customer variables for a script.

    Workflow:
      1. Check if .var file exists
      2. If yes: load, display, validate with user
      3. If no: show example, ask user to create, then prompt for values

    Args:
        script_name: Script name or __name__ of calling script
        logger: Optional logger for recording actions
        skip_prompts: If True, skip all user prompts and accept defaults

    Returns:
        Dict of variables, empty dict if canceled/manual edit mode
    """
    # Extract script name from __name__ or path
    if script_name == '__main__':
        script_name = sys.argv[0]
    script_name = Path(script_name).name

    var_file_path = get_var_file_path(script_name)
    example_path = get_var_example_path(script_name)

    if logger:
        logger.info(f"var_loader: loading variables for {script_name}")

    # Try to load existing .var file
    variables = load_var_file(var_file_path)

    if variables:
        # File exists, validate with user
        if logger:
            logger.info(f"var_loader: found .var file at {var_file_path}")

        if validate_variables_with_user(variables, var_file_path, skip_prompts=skip_prompts):
            # User saved after potentially editing variables
            save_var_file(variables, var_file_path, logger)
            print(f"\n✓ Variables saved to: {var_file_path}\n")
            return variables
        else:
            # User canceled the menu
            return {}
    else:
        # No .var file, guide user through creation
        if logger:
            logger.info(f"var_loader: no .var file found, starting creation workflow")

        return create_var_file_interactive(script_name, example_path, var_file_path, logger, skip_prompts=skip_prompts) or {}
