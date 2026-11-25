"""Chargement de la configuration externe (config.json)."""

import json
from pathlib import Path
from typing import Any

SECTIONS_OBLIGATOIRES = (
    "database",
    "logging",
    "collector",
    "processes",
    "healthchecks",
    "thresholds",
)


class ConfigurationError(Exception):
    """Configuration absente, invalide ou incomplète."""


def charger_config(chemin: str | Path) -> dict[str, Any]:
    """Charge et vérifie le fichier de configuration JSON.

    Args:
        chemin: Chemin du fichier config.json.

    Returns:
        La configuration sous forme de dictionnaire.

    Raises:
        ConfigurationError: Si le fichier est absent, invalide ou incomplet.
    """
    try:
        with open(chemin, encoding="utf-8") as fichier:
            config = json.load(fichier)
    except FileNotFoundError as exc:
        raise ConfigurationError(f"Fichier introuvable : {chemin}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"JSON invalide dans {chemin} (ligne {exc.lineno}) : {exc.msg}"
        ) from exc

    manquantes = [nom for nom in SECTIONS_OBLIGATOIRES if nom not in config]
    if manquantes:
        raise ConfigurationError(f"Sections manquantes : {', '.join(manquantes)}")

    return config
