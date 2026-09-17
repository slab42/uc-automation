#!/usr/bin/env python3
"""
Standardized prompt utilities for UC automation scripts.
Provides consistent yes/no prompts across all scripts.
"""


def prompt_yes_no(prompt_text, default=True):
    """
    Display a yes/no prompt with consistent formatting.

    Format: "Your question? (Y/n)" if default is True
            "Your question? (y/N)" if default is False

    Args:
        prompt_text (str): The question/prompt text (without the yes/no part)
        default (bool): Default answer if user just presses Enter (default: True)

    Returns:
        bool: True if user enters y/yes/Y/YES or presses Enter with default=True
              False if user enters n/no/N/NO or presses Enter with default=False
    """
    default_char = 'Y' if default else 'N'
    other_char = 'n' if default else 'y'
    prompt_suffix = f' ({default_char}/{other_char}): '

    while True:
        response = input(prompt_text + prompt_suffix).strip().lower()

        if response == '':
            return default
        elif response in ('y', 'yes'):
            return True
        elif response in ('n', 'no'):
            return False
        else:
            print(f"Invalid input. Please enter 'y' or 'n'.")
