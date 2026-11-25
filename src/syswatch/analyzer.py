"""Module D : seuils, fuites mémoire et SLA."""

from collections import deque
from collections.abc import Iterable
from itertools import pairwise

from syswatch.models import EtatService, Incident, Partition, Processus


def detecter_disques(partitions: list[Partition], seuil_pct: float) -> list[Incident]:
    """Signale les partitions remplies au-delà du seuil.

    Args:
        partitions: Partitions mesurées.
        seuil_pct: Taux d'occupation maximal (ex. 85).

    Returns:
        Un incident par partition trop remplie.
    """
    return [
        Incident(
            category="disque",
            severity="WARNING",
            resource_name=partition.mountpoint,
            metric_value=partition.usage_pct,
            threshold_value=seuil_pct,
            description=(
                f"Partition {partition.mountpoint} remplie à {partition.usage_pct} %"
            ),
        )
        for partition in partitions
        if partition.usage_pct > seuil_pct
    ]


def detecter_services(etats: list[EtatService], seuil_ssl_jours: int) -> list[Incident]:
    """Signale les services en panne et les certificats bientôt expirés.

    Args:
        etats: Résultats des tests de santé.
        seuil_ssl_jours: Nombre de jours minimal avant expiration (ex. 15).

    Returns:
        Les incidents détectés.
    """
    incidents = []
    for etat in etats:
        if not etat.is_healthy:
            incidents.append(
                Incident(
                    category="service",
                    severity="CRITICAL",
                    resource_name=etat.service_name,
                    metric_value=0,
                    threshold_value=1,
                    description=f"{etat.service_name} indisponible : {etat.error_msg}",
                )
            )
        if etat.ssl_days_left is not None and etat.ssl_days_left < seuil_ssl_jours:
            incidents.append(
                Incident(
                    category="ssl",
                    severity="WARNING",
                    resource_name=etat.service_name,
                    metric_value=etat.ssl_days_left,
                    threshold_value=seuil_ssl_jours,
                    description=(
                        f"Certificat de {etat.service_name} expire dans "
                        f"{etat.ssl_days_left} jour(s)"
                    ),
                )
            )
    return incidents


def detecter_sla(slas: dict[str, float], objectif_pct: float) -> list[Incident]:
    """Signale les services dont le SLA passe sous l'objectif.

    Args:
        slas: SLA en pourcentage, par nom de service.
        objectif_pct: SLA minimal attendu (ex. 99.0).

    Returns:
        Un incident par service sous l'objectif.
    """
    return [
        Incident(
            category="sla",
            severity="WARNING",
            resource_name=nom,
            metric_value=sla,
            threshold_value=objectif_pct,
            description=f"SLA de {nom} à {sla} % (objectif {objectif_pct} %)",
        )
        for nom, sla in slas.items()
        if sla < objectif_pct
    ]


def est_strictement_croissante(valeurs: Iterable[float]) -> bool:
    """Indique si chaque valeur est strictement supérieure à la précédente.

    Args:
        valeurs: Suite de valeurs, dans l'ordre chronologique.

    Returns:
        True si la suite ne fait qu'augmenter.
    """
    return all(avant < apres for avant, apres in pairwise(valeurs))


class DetecteurFuites:
    """Détecte les processus dont la mémoire augmente sans arrêt."""

    def __init__(self, nb_releves: int) -> None:
        """Prépare un historique vide.

        Args:
            nb_releves: Nombre de hausses consécutives qui signalent une fuite.
        """
        self.nb_releves = nb_releves
        self._historiques: dict[int, deque[float]] = {}

    def analyser(self, processus: list[Processus]) -> list[Incident]:
        """Ajoute un relevé par processus et signale les hausses continues.

        Une fuite est signalée quand la mémoire RSS a augmenté à chacun des
        `nb_releves` derniers relevés. L'historique est alors vidé, pour ne
        pas signaler la même fuite à chaque relevé.

        Args:
            processus: Processus mesurés lors de ce relevé.

        Returns:
            Un incident par fuite détectée.
        """
        incidents = []
        for proc in processus:
            historique = self._historiques.setdefault(
                proc.pid, deque(maxlen=self.nb_releves)
            )
            historique.append(proc.rss_mb)
            if len(historique) == self.nb_releves and est_strictement_croissante(
                historique
            ):
                incidents.append(
                    Incident(
                        category="fuite_memoire",
                        severity="WARNING",
                        resource_name=f"{proc.name} (PID {proc.pid})",
                        metric_value=proc.rss_mb,
                        threshold_value=self.nb_releves,
                        description=(
                            f"RSS de {proc.name} en hausse sur {self.nb_releves} "
                            f"relevés : {historique[0]} -> {proc.rss_mb} Mo"
                        ),
                    )
                )
                historique.clear()

        # On oublie les processus qui ont disparu
        pids_actuels = {proc.pid for proc in processus}
        for pid in list(self._historiques):
            if pid not in pids_actuels:
                del self._historiques[pid]
        return incidents


def cle_incident(incident: Incident) -> str:
    """Identifiant d'un incident : sa catégorie et la ressource concernée."""
    return f"{incident.category}:{incident.resource_name}"


def filtrer_nouveaux(incidents: list[Incident], actifs: set[str]) -> list[Incident]:
    """Ne garde que les incidents qui viennent d'apparaître.

    Sans ce filtre, un disque plein serait signalé toutes les 5 secondes.

    Args:
        incidents: Problèmes détectés lors de ce relevé.
        actifs: Clés des problèmes déjà signalés. L'ensemble est mis à jour :
            un problème résolu en sort, et sera signalé à nouveau s'il
            revient.

    Returns:
        Les incidents nouveaux.
    """
    cles = {cle_incident(incident) for incident in incidents}
    nouveaux = [i for i in incidents if cle_incident(i) not in actifs]
    actifs.clear()
    actifs.update(cles)
    return nouveaux
