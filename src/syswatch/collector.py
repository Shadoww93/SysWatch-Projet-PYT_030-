"""Module A : collecte des métriques système (CPU, mémoire, disques)."""

import logging
import socket
import time
from typing import Any

import psutil

from syswatch.models import MesureHote, Partition, UsageCoeur

logger = logging.getLogger(__name__)

OCTETS_PAR_MO = 1024**2
OCTETS_PAR_GO = 1024**3


def octets_en_mo(octets: float) -> float:
    """Convertit des octets en mégaoctets (arrondi à 0,1)."""
    return round(octets / OCTETS_PAR_MO, 1)


def octets_en_go(octets: float) -> float:
    """Convertit des octets en gigaoctets (arrondi à 0,01)."""
    return round(octets / OCTETS_PAR_GO, 2)


def calculer_taux(precedent: float, actuel: float, duree_sec: float) -> float:
    """Calcule la variation par seconde entre deux compteurs cumulés.

    Args:
        precedent: Valeur du compteur au relevé précédent.
        actuel: Valeur du compteur au relevé actuel.
        duree_sec: Temps écoulé entre les deux relevés, en secondes.

    Returns:
        La variation par seconde, ou 0.0 si la durée est nulle ou si le
        compteur a été remis à zéro (redémarrage, débordement).
    """
    if duree_sec <= 0 or actuel < precedent:
        return 0.0
    return (actuel - precedent) / duree_sec


def calculer_debits_disque(
    precedent: Any, actuel: Any, duree_sec: float
) -> tuple[float, float, float, float]:
    """Calcule les débits (Mo/s) et les IOPS du disque entre deux relevés.

    Args:
        precedent: Compteurs psutil.disk_io_counters() précédents, ou None.
        actuel: Compteurs actuels, ou None.
        duree_sec: Temps écoulé entre les deux relevés, en secondes.

    Returns:
        (lecture en Mo/s, écriture en Mo/s, IOPS en lecture, IOPS en écriture).
    """
    if precedent is None or actuel is None:  # compteurs disque indisponibles
        return 0.0, 0.0, 0.0, 0.0
    lecture = calculer_taux(precedent.read_bytes, actuel.read_bytes, duree_sec)
    ecriture = calculer_taux(precedent.write_bytes, actuel.write_bytes, duree_sec)
    iops_lecture = calculer_taux(precedent.read_count, actuel.read_count, duree_sec)
    iops_ecriture = calculer_taux(precedent.write_count, actuel.write_count, duree_sec)
    return (
        round(lecture / OCTETS_PAR_MO, 3),
        round(ecriture / OCTETS_PAR_MO, 3),
        round(iops_lecture, 1),
        round(iops_ecriture, 1),
    )


def lire_compteurs_disque() -> Any:
    """Lit les compteurs d'entrées/sorties disque cumulés.

    Returns:
        Les compteurs psutil, ou None si aucun disque n'est détecté.
    """
    try:
        return psutil.disk_io_counters()
    except RuntimeError:  # aucun disque physique (conteneur, machine virtuelle)
        return None


def lire_charge_moyenne() -> tuple[float | None, float | None, float | None]:
    """Lit la charge moyenne (load average) sur 1, 5 et 15 minutes.

    Returns:
        Les trois valeurs, ou (None, None, None) si le système ne les fournit
        pas.
    """
    try:
        charge_1, charge_5, charge_15 = psutil.getloadavg()
    except (AttributeError, OSError):  # repli propre : charge non disponible
        return None, None, None
    return round(charge_1, 2), round(charge_5, 2), round(charge_15, 2)


def memoire_cache_mo(memoire: Any) -> float | None:
    """Mémoire utilisée en cache et en tampons.

    Args:
        memoire: Résultat de psutil.virtual_memory().

    Returns:
        Le cache + les tampons en Mo, ou None si le système (Windows) ne
        fournit pas ces valeurs.
    """
    cache = getattr(memoire, "cached", None)
    if cache is None:
        return None
    return octets_en_mo(cache + getattr(memoire, "buffers", 0))


def mesurer_partitions() -> list[Partition]:
    """Mesure l'occupation de chaque partition montée.

    Returns:
        Une mesure par partition lisible (les lecteurs vides sont ignorés).
    """
    partitions = []
    for partition in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except OSError:  # lecteur vide (CD-ROM), accès refusé...
            logger.debug("Partition ignorée : %s", partition.mountpoint)
            continue
        partitions.append(
            Partition(
                mountpoint=partition.mountpoint,
                total_gb=octets_en_go(usage.total),
                used_gb=octets_en_go(usage.used),
                usage_pct=usage.percent,
            )
        )
    return partitions


class CollecteurHote:
    """Collecte les métriques globales de la machine.

    Garde en mémoire les compteurs disque du relevé précédent : un débit se
    calcule toujours par différence entre deux relevés.
    """

    def __init__(self) -> None:
        """Prend un premier relevé, qui sert de point de comparaison."""
        self._disque_precedent = lire_compteurs_disque()
        self._instant_precedent = time.monotonic()
        # Appels « à blanc » : psutil mesure ensuite l'activité CPU
        # écoulée depuis l'appel précédent.
        psutil.cpu_percent()
        psutil.cpu_percent(percpu=True)
        psutil.cpu_times_percent()

    def mesurer(self) -> tuple[MesureHote, list[UsageCoeur]]:
        """Mesure CPU, mémoire, swap et disque depuis le relevé précédent.

        Returns:
            La mesure globale de l'hôte et l'utilisation de chaque cœur.
        """
        maintenant = time.monotonic()
        disque = lire_compteurs_disque()
        lecture, ecriture, iops_lecture, iops_ecriture = calculer_debits_disque(
            self._disque_precedent, disque, maintenant - self._instant_precedent
        )
        self._disque_precedent = disque
        self._instant_precedent = maintenant

        temps_cpu = psutil.cpu_times_percent()
        memoire = psutil.virtual_memory()
        charge_1, charge_5, charge_15 = lire_charge_moyenne()

        mesure = MesureHote(
            hostname=socket.gethostname(),
            cpu_pct=psutil.cpu_percent(),
            load_1m=charge_1,
            ram_used_mb=octets_en_mo(memoire.used),
            ram_pct=memoire.percent,
            swap_pct=psutil.swap_memory().percent,
            disk_read_mb_s=lecture,
            disk_write_mb_s=ecriture,
            cpu_user_pct=temps_cpu.user,
            cpu_system_pct=temps_cpu.system,
            cpu_iowait_pct=getattr(temps_cpu, "iowait", None),  # absent sous Windows
            load_5m=charge_5,
            load_15m=charge_15,
            ram_total_mb=octets_en_mo(memoire.total),
            ram_available_mb=octets_en_mo(memoire.available),
            ram_cached_mb=memoire_cache_mo(memoire),
            disk_read_iops=iops_lecture,
            disk_write_iops=iops_ecriture,
        )
        coeurs = [
            UsageCoeur(core=numero, cpu_pct=pourcentage)
            for numero, pourcentage in enumerate(psutil.cpu_percent(percpu=True))
        ]
        return mesure, coeurs
