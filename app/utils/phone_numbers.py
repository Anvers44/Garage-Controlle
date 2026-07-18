"""Normalisation des numéros de téléphone.

La normalisation est une règle **métier** (elle vit ici, pas dans le driver).
Objectif principal : ramener les numéros algériens à leur forme nationale
``0XXXXXXXXX`` afin de comparer de façon fiable un numéro entrant à la
whitelist, quel que soit son format d'origine (``+213…``, ``00213…``, espaces…).
"""

from __future__ import annotations

import re
from typing import Optional

# Préfixe international par défaut (Algérie).
DEFAULT_COUNTRY_CODE = "213"
NATIONAL_PREFIX = "0"


def normalize_number(
    raw: Optional[str],
    country_code: str = DEFAULT_COUNTRY_CODE,
    national_prefix: str = NATIONAL_PREFIX,
) -> str:
    """Retourne la forme normalisée d'un numéro.

    Règles appliquées :

    - Suppression des espaces, tirets, points et parenthèses.
    - ``00<cc>`` et ``+<cc>`` → ``<national_prefix>`` (ex : ``+213661…`` → ``0661…``).
    - ``<cc>...`` (sans ``+`` ni ``0`` initial) → ``<national_prefix>...``.
    - Un numéro déjà national (commençant par ``0``) est conservé tel quel.

    Args:
        raw: numéro brut tel que reçu du réseau (peut être ``None``).
        country_code: indicatif pays sans ``+`` (``"213"`` par défaut).
        national_prefix: préfixe national (``"0"`` par défaut).

    Returns:
        Le numéro normalisé, ou une chaîne vide si ``raw`` est vide/None.
    """
    if not raw:
        return ""

    # Ne conserver que ``+`` et les chiffres.
    cleaned = re.sub(r"[^\d+]", "", raw.strip())
    if not cleaned:
        return ""

    # 00<cc> -> +<cc>
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    # +<cc>... -> national_prefix...
    if cleaned.startswith("+" + country_code):
        rest = cleaned[len("+" + country_code):]
        return national_prefix + rest

    # +<autre indicatif> : on retire simplement le '+' (numéro étranger).
    if cleaned.startswith("+"):
        return cleaned[1:]

    # <cc>... sans '+' ni '0' initial -> national_prefix...
    if cleaned.startswith(country_code) and not cleaned.startswith(national_prefix):
        rest = cleaned[len(country_code):]
        return national_prefix + rest

    return cleaned


def numbers_match(a: Optional[str], b: Optional[str]) -> bool:
    """Compare deux numéros après normalisation."""
    return bool(a) and bool(b) and normalize_number(a) == normalize_number(b)
