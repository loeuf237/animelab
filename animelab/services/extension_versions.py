"""Extension build codes are ordered integers; display names are not identities."""
import re


def version_code(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and 0 <= value <= 2**63 - 1:
        return value
    if isinstance(value, str) and re.fullmatch(r'\d{1,19}', value):
        return version_code(int(value))
    return None


def newer(available, installed, available_code=None, installed_code=None):
    remote, local = version_code(available_code), version_code(installed_code)
    if remote is not None and local is not None:
        return remote > local
    # Legacy installations did not retain code. Compare numeric components until
    # the first verified install supplies it; never lexicographically order names.
    if not available or not installed or available == installed:
        return False
    if re.fullmatch(r'\d+(?:\.\d+)*', str(available)) and re.fullmatch(r'\d+(?:\.\d+)*', str(installed)):
        a, b = tuple(map(int, str(available).split('.'))), tuple(map(int, str(installed).split('.')))
        length = max(len(a), len(b))
        return a + (0,) * (length-len(a)) > b + (0,) * (length-len(b))
    return False  # Unknown ordering requires an explicit reinstall, not a guessed upgrade.
