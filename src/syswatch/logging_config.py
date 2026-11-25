"""Journalisation : console + fichier rotatif app.log."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


def configurer_journalisation(config: dict[str, Any]) -> None:
    """Envoie les journaux vers la console et vers un fichier rotatif.

    Args:
        config: Section "logging" de config.json (file, level, format,
            max_bytes, backup_count).
    """
    chemin = Path(config["file"])
    chemin.parent.mkdir(parents=True, exist_ok=True)  # crée logs/ si besoin

    fichier = RotatingFileHandler(
        chemin,
        maxBytes=config["max_bytes"],
        backupCount=config["backup_count"],
        encoding="utf-8",
    )
    logging.basicConfig(
        level=config["level"],
        format=config["format"],
        handlers=[logging.StreamHandler(), fichier],
        force=True,
    )
