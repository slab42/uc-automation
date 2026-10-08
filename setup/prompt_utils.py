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


def prompt_delete_mode(prompt_text='Delete these items?'):
    """
    Ask how to proceed with a deletion: (N/y/i).

    Returns:
        str: 'n' (cancel, default), 'y' (delete all), or 'i' (confirm each individually)
    """
    while True:
        response = input(f'{prompt_text} (N/y/i) [i = individually]: ').strip().lower()
        if response in ('', 'n', 'no'):
            return 'n'
        if response in ('y', 'yes'):
            return 'y'
        if response in ('i', 'individual', 'individually'):
            return 'i'
        print("Invalid input. Please enter 'n', 'y', or 'i'.")


def prompt_use_multiple(count, noun='clusters', default=False):
    """
    Ask "N <noun> found. Use multiple <noun>?" unless multi-cluster is disabled.

    Multi-cluster is disabled with `multi_cluster = false` under [SETTINGS] in
    .env/credentials.env. When disabled, returns False without prompting so the
    script proceeds straight to single cluster/router selection.
    """
    from setup.env_loader import CredentialsLoader
    if not CredentialsLoader().is_multi_cluster_enabled():
        return False
    return prompt_yes_no(f'{count} {noun} found. Use multiple {noun}?', default=default)
