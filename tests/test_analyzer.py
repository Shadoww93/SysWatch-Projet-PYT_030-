"""Tests du module D : seuils, fuites mémoire, SLA et filtrage."""

from collections import deque

from syswatch.analyzer import (
    DetecteurFuites,
    detecter_disques,
    detecter_services,
    detecter_sla,
    est_strictement_croissante,
    filtrer_nouveaux,
)
from syswatch.models import EtatService, Partition, Processus


def test_suite_croissante() -> None:
    assert est_strictement_croissante([1.0, 2.0, 3.0]) is True
    assert est_strictement_croissante(deque([1.0, 2.0, 2.0])) is False


def proc(rss: float) -> Processus:
    return Processus(42, "app", "running", 1.0, rss, 4, 10)


def test_fuite_detectee_puis_historique_vide() -> None:
    detecteur = DetecteurFuites(nb_releves=3)
    assert detecteur.analyser([proc(100.0)]) == []
    assert detecteur.analyser([proc(110.0)]) == []
    incidents = detecteur.analyser([proc(120.0)])
    assert len(incidents) == 1
    assert incidents[0].category == "fuite_memoire"
    assert detecteur.analyser([proc(130.0)]) == []  # historique remis à zéro


def test_pas_de_fuite_si_memoire_stable() -> None:
    detecteur = DetecteurFuites(nb_releves=3)
    for rss in (100.0, 110.0, 110.0, 120.0):
        assert detecteur.analyser([proc(rss)]) == []


def test_seuil_disque() -> None:
    partitions = [Partition("C:\\", 100.0, 90.0, 90.0), Partition("D:\\", 100, 50, 50)]
    incidents = detecter_disques(partitions, 85)
    assert [i.resource_name for i in incidents] == ["C:\\"]


def etat(sain: bool, jours_ssl: int | None) -> EtatService:
    return EtatService("api", "https://api", 200, 50.0, sain, jours_ssl, None)


def test_service_en_panne_et_certificat() -> None:
    incidents = detecter_services([etat(False, 10)], seuil_ssl_jours=15)
    assert [(i.category, i.severity) for i in incidents] == [
        ("service", "CRITICAL"),
        ("ssl", "WARNING"),
    ]


def test_service_sain_certificat_valide() -> None:
    assert detecter_services([etat(True, 200)], seuil_ssl_jours=15) == []


def test_sla_sous_objectif() -> None:
    incidents = detecter_sla({"api": 95.0, "web": 100.0}, objectif_pct=99.0)
    assert [i.resource_name for i in incidents] == ["api"]


def test_filtrage_des_incidents_deja_signales() -> None:
    actifs: set[str] = set()
    probleme = detecter_disques([Partition("C:\\", 100, 90, 90.0)], 85)
    assert len(filtrer_nouveaux(probleme, actifs)) == 1  # nouveau
    assert filtrer_nouveaux(probleme, actifs) == []  # déjà signalé
    assert filtrer_nouveaux([], actifs) == []  # problème résolu
    assert len(filtrer_nouveaux(probleme, actifs)) == 1  # il revient
