import re
from typing import List

DIGITS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"

def base_n(num: int, radix: int) -> str:
    if num == 0:
        return "0"
    res = []
    while num > 0:
        res.append(DIGITS[num % radix])
        num //= radix
    return "".join(reversed(res))

def unpack(p: str, a: int, c: int, k: List[str]) -> str:
    lookup = {}
    for i in range(c):
        key = base_n(i, a)
        val = k[i] if i < len(k) and k[i] else key
        lookup[key] = val

    def replace_word(m):
        w = m.group(0)
        return lookup.get(w, w)

    return re.sub(r"\b[0-9a-zA-Z_]+\b", replace_word, p)

PACKER_PATTERN = re.compile(
    r"eval\s*\(\s*function\s*\(p,\s*a,\s*c,\s*k,\s*e,\s*d\s*\).*?\}\s*\(\s*['\"]"
    r"(.*?)"
    r"['\"]\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*['\"]([^'\"]*)['\"]\.split\s*\(\s*['\"]\|['\"]\s*\).*?\)\s*\)",
    re.DOTALL
)

def unpack_all(html: str) -> List[str]:
    """Extrait et dépaquette tous les blocs de JavaScript obfusqués via Dean Edwards packer."""
    results = []
    for match in PACKER_PATTERN.finditer(html):
        try:
            p = match.group(1)
            a = int(match.group(2))
            c = int(match.group(3))
            k = match.group(4).split("|")
            unpacked_text = unpack(p, a, c, k)
            results.append(unpacked_text)
        except Exception:
            continue
    return results

def try_unpack(html: str) -> str:
    """Tente de dépaqueter tous les scripts Dean Edwards packer trouvés dans le code HTML."""
    unpacked_blocks = unpack_all(html)
    if unpacked_blocks:
        return "\n".join(unpacked_blocks)
    return html
