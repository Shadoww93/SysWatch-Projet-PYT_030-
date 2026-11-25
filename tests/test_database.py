"""Tests des opérations CRUD sur la base SQLite (en mémoire)."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from syswatch.database import TABLES, connecter, inserer, purger, sla_par_service
from syswatch.models import EtatService, Partition

JOUR = 86_400


@pytest.fixture
def conn() -> Iterator[sqlite3.Connection]:
    """Fournit une base vide en mémoire à chaque test, puis la ferme."""
    connexion = connecter(":memory:")
    yield connexion
    connexion.close()


def etat(nom: str, sain: bool) -> EtatService:
    return EtatService(nom, "http://test", 200, 10.0, sain, None, None)


def test_tables_creees(conn: sqlite3.Connection) -> None:
    lignes = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    assert {ligne["name"] for ligne in lignes} == set(TABLES)


def test_mode_wal(tmp_path: Path) -> None:
    connexion = connecter(str(tmp_path / "test.db"))
    mode = connexion.execute("PRAGMA journal_mode").fetchone()[0]
    connexion.close()
    assert mode == "wal"


def test_inserer_et_lire(conn: sqlite3.Connection) -> None:
    inserer(conn, "disk_partitions", 1000, [Partition("C:\\", 500.0, 250.0, 50.0)])
    ligne = conn.execute("SELECT * FROM disk_partitions").fetchone()
    assert ligne["timestamp"] == 1000
    assert ligne["mountpoint"] == "C:\\"
    assert ligne["usage_pct"] == 50.0


def test_table_inconnue_refusee(conn: sqlite3.Connection) -> None:
    with pytest.raises(ValueError, match="Table inconnue"):
        inserer(conn, "users; DROP TABLE host_metrics", 1000, [etat("a", True)])


def test_liste_vide_sans_erreur(conn: sqlite3.Connection) -> None:
    inserer(conn, "service_health", 1000, [])
    assert conn.execute("SELECT COUNT(*) FROM service_health").fetchone()[0] == 0


def test_sla_par_service(conn: sqlite3.Connection) -> None:
    resultats = [etat("api", True)] * 3 + [etat("api", False)]
    inserer(conn, "service_health", 1000, resultats)
    assert sla_par_service(conn, depuis=0) == {"api": 75.0}


def test_purge(conn: sqlite3.Connection) -> None:
    maintenant = 100 * JOUR
    partition = Partition("C:\\", 500.0, 250.0, 50.0)
    inserer(conn, "disk_partitions", maintenant - 8 * JOUR, [partition])  # 8 jours
    inserer(conn, "disk_partitions", maintenant - 1 * JOUR, [partition])  # 1 jour
    assert purger(conn, 7, maintenant) == 1
    assert conn.execute("SELECT COUNT(*) FROM disk_partitions").fetchone()[0] == 1
