"""Tests des calculs de métriques système et de la sélection des processus."""

from types import SimpleNamespace

from syswatch.collector import calculer_debits_disque, calculer_taux, memoire_cache_mo
from syswatch.models import Processus
from syswatch.processes import selectionner

MO = 1024**2


def test_taux_normal() -> None:
    assert calculer_taux(100, 300, 2) == 100.0


def test_taux_compteur_remis_a_zero() -> None:
    assert calculer_taux(500, 100, 2) == 0.0


def test_taux_duree_nulle() -> None:
    assert calculer_taux(100, 300, 0) == 0.0


def test_debits_disque() -> None:
    avant = SimpleNamespace(read_bytes=0, write_bytes=0, read_count=0, write_count=0)
    apres = SimpleNamespace(
        read_bytes=10 * MO, write_bytes=5 * MO, read_count=100, write_count=50
    )
    assert calculer_debits_disque(avant, apres, 5) == (2.0, 1.0, 20.0, 10.0)


def test_debits_disque_indisponibles() -> None:
    assert calculer_debits_disque(None, None, 5) == (0.0, 0.0, 0.0, 0.0)


def test_cache_linux() -> None:
    memoire = SimpleNamespace(cached=100 * MO, buffers=28 * MO)
    assert memoire_cache_mo(memoire) == 128.0


def test_cache_absent_sous_windows() -> None:
    assert memoire_cache_mo(SimpleNamespace()) is None


def processus(pid: int, nom: str, cpu: float, ram: float) -> Processus:
    return Processus(pid, nom, "running", cpu, ram, 1, 10)


def test_selection_surveilles_et_top() -> None:
    tous = [
        processus(1, "nginx", 0.1, 10.0),
        processus(2, "chrome.exe", 50.0, 20.0),
        processus(3, "java", 1.0, 900.0),
        processus(4, "bash", 0.0, 1.0),
    ]
    selection = selectionner(tous, ["nginx"], top=1)
    assert {p.pid for p in selection} == {1, 2, 3}  # nginx + top CPU + top RAM


def test_selection_sans_doublon() -> None:
    tous = [processus(1, "python.exe", 90.0, 900.0)]
    assert len(selectionner(tous, ["python"], top=5)) == 1
