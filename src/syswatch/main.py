"""SysWatch : point d'entrée de l'agent de supervision."""

import logging
import os
import signal
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import psutil

from syswatch.analyzer import (
    DetecteurFuites,
    detecter_disques,
    detecter_services,
    detecter_sla,
    filtrer_nouveaux,
)
from syswatch.collector import CollecteurHote, mesurer_partitions
from syswatch.config import ConfigurationError, charger_config
from syswatch.database import connecter, inserer, purger, sla_par_service
from syswatch.healthchecks import verifier_services
from syswatch.logging_config import configurer_journalisation
from syswatch.models import Incident
from syswatch.processes import lister_processus, selectionner

CHEMIN_CONFIG = os.environ.get("SYSWATCH_CONFIG", "config.json")

logger = logging.getLogger(__name__)

# Drapeau partagé : levé par Ctrl+C (SIGINT) ou SIGTERM pour arrêter la boucle
arret_demande = threading.Event()


def demander_arret(numero: int, _cadre: object) -> None:
    """Gestionnaire des signaux SIGINT et SIGTERM : demande l'arrêt propre.

    Args:
        numero: Numéro du signal reçu.
        _cadre: Cadre d'exécution (non utilisé, imposé par le module signal).
    """
    logger.info("Signal %s reçu : arrêt en cours", signal.Signals(numero).name)
    arret_demande.set()


class Agent:
    """Enchaîne la collecte, les tests de santé, les incidents et la purge."""

    def __init__(
        self,
        config: dict[str, Any],
        conn: sqlite3.Connection,
        executeur: ThreadPoolExecutor,
    ) -> None:
        """Prépare les collecteurs et l'état des incidents.

        Args:
            config: Configuration complète (config.json).
            conn: Connexion à la base SQLite.
            executeur: Groupe de threads pour les tests de santé.
        """
        self.config = config
        self.conn = conn
        self.executeur = executeur
        self.collecteur = CollecteurHote()
        self.detecteur_fuites = DetecteurFuites(config["thresholds"]["leak_readings"])
        self.incidents_disques: set[str] = set()
        self.incidents_services: set[str] = set()

    def collecter_systeme(self) -> None:
        """Modules A, B et D : mesures de l'hôte, processus et seuils."""
        reglages = self.config["processes"]
        seuils = self.config["thresholds"]
        horodatage = int(time.time())

        mesure, coeurs = self.collecteur.mesurer()
        partitions = mesurer_partitions()
        processus = selectionner(
            lister_processus(), reglages["watch"], reglages["top_count"]
        )

        inserer(self.conn, "host_metrics", horodatage, [mesure])
        inserer(self.conn, "cpu_cores", horodatage, coeurs)
        inserer(self.conn, "disk_partitions", horodatage, partitions)
        inserer(self.conn, "process_metrics", horodatage, processus)

        incidents = filtrer_nouveaux(
            detecter_disques(partitions, seuils["disk_pct"]), self.incidents_disques
        )
        incidents += self.detecteur_fuites.analyser(processus)
        self.enregistrer_incidents(horodatage, incidents)
        logger.info(
            "CPU %.1f %% | RAM %.1f %% | %d processus suivis",
            mesure.cpu_pct,
            mesure.ram_pct,
            len(processus),
        )

    def verifier_sante(self) -> None:
        """Modules C et D : tests de santé, certificats et SLA."""
        reglages = self.config["healthchecks"]
        seuils = self.config["thresholds"]
        horodatage = int(time.time())

        etats = verifier_services(
            reglages["services"],
            reglages["timeout_sec"],
            reglages["user_agent"],
            self.executeur,
        )
        inserer(self.conn, "service_health", horodatage, etats)
        slas = sla_par_service(self.conn, horodatage - seuils["sla_window_sec"])

        problemes = detecter_services(etats, seuils["ssl_days"])
        problemes += detecter_sla(slas, seuils["sla_target_pct"])
        self.enregistrer_incidents(
            horodatage, filtrer_nouveaux(problemes, self.incidents_services)
        )
        for etat in etats:
            logger.info(
                "Service %s : %s (%s ms, SLA %s %%)",
                etat.service_name,
                "UP" if etat.is_healthy else "DOWN",
                etat.response_time_ms,
                slas.get(etat.service_name),
            )

    def purger_donnees(self) -> None:
        """Supprime les données plus anciennes que la durée de rétention."""
        purger(self.conn, self.config["database"]["retention_days"])

    def enregistrer_incidents(self, horodatage: int, incidents: list[Incident]) -> None:
        """Journalise puis enregistre en base les nouveaux incidents.

        Args:
            horodatage: Instant de détection (secondes Unix).
            incidents: Incidents à enregistrer.
        """
        for incident in incidents:
            logger.warning("Incident %s : %s", incident.severity, incident.description)
        inserer(self.conn, "system_incidents", horodatage, incidents)

    def executer_tache(self, tache: Callable[[], None]) -> None:
        """Exécute une tâche sans arrêter l'agent si elle échoue.

        Args:
            tache: Méthode à exécuter (collecte, tests de santé ou purge).
        """
        try:
            tache()
        except (psutil.Error, OSError, sqlite3.Error):
            logger.exception("Échec de la tâche %s", tache.__name__)

    def executer(self) -> None:
        """Boucle principale : chaque tâche a son propre intervalle."""
        taches = [
            (self.config["collector"]["interval_sec"], self.collecter_systeme),
            (self.config["healthchecks"]["interval_sec"], self.verifier_sante),
            (self.config["database"]["purge_interval_sec"], self.purger_donnees),
        ]
        # Premier passage après 1 s : psutil a besoin d'un point de comparaison
        prochains = [time.monotonic() + 1 for _ in taches]

        while not arret_demande.is_set():
            for numero, (intervalle, tache) in enumerate(taches):
                if arret_demande.is_set():
                    break
                if time.monotonic() >= prochains[numero]:
                    prochains[numero] = time.monotonic() + intervalle
                    self.executer_tache(tache)
            arret_demande.wait(0.5)  # pause courte : Ctrl+C reste réactif


def main() -> None:
    """Charge la configuration, puis lance l'agent jusqu'à son arrêt."""
    #
    # Main entry point
    #
    try:
        config = charger_config(CHEMIN_CONFIG)
    except ConfigurationError as exc:
        logger.critical("Démarrage impossible : %s", exc)
        raise SystemExit(1) from exc

    configurer_journalisation(config["logging"])
    signal.signal(signal.SIGINT, demander_arret)
    signal.signal(signal.SIGTERM, demander_arret)
    logger.info("SysWatch started (Ctrl+C pour arrêter)")

    conn = connecter(config["database"]["path"])
    try:
        nb_threads = config["healthchecks"]["max_workers"]
        with ThreadPoolExecutor(max_workers=nb_threads) as executeur:
            Agent(config, conn, executeur).executer()
    finally:
        conn.close()  # fermeture propre de la base, même après une erreur
        logger.info("SysWatch stopped")


if __name__ == "__main__":
    #
    # main() call if module is directly loaded
    #
    main()
