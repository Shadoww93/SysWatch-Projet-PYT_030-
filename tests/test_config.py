"""Tests du chargement (parsing) de la configuration."""

import json
from pathlib import Path

import pytest

from syswatch.config import SECTIONS_OBLIGATOIRES, ConfigurationError, charger_config


def ecrire(chemin: Path, contenu: str) -> Path:
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def test_config_valide(tmp_path: Path) -> None:
    contenu = {section: {} for section in SECTIONS_OBLIGATOIRES}
    chemin = ecrire(tmp_path / "config.json", json.dumps(contenu))
    assert charger_config(chemin) == contenu


def test_fichier_absent(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="introuvable"):
        charger_config(tmp_path / "absent.json")


def test_json_invalide(tmp_path: Path) -> None:
    chemin = ecrire(tmp_path / "config.json", "{ pas du json")
    with pytest.raises(ConfigurationError, match="JSON invalide"):
        charger_config(chemin)


def test_section_manquante(tmp_path: Path) -> None:
    chemin = ecrire(tmp_path / "config.json", json.dumps({"database": {}}))
    with pytest.raises(ConfigurationError, match="Sections manquantes"):
        charger_config(chemin)


def test_config_du_projet_valide() -> None:
    config = charger_config(Path(__file__).parent.parent / "config.json")
    assert config["collector"]["interval_sec"] == 5
