"""Module B : profilage des processus critiques et des plus gourmands."""

import re

import psutil

from syswatch.models import Processus

OCTETS_PAR_MO = 1024**2

# Fichiers ouverts : « descripteurs » sous Linux, « handles » sous Windows
ATTRIBUT_FICHIERS = "num_handles" if psutil.WINDOWS else "num_fds"
ATTRIBUTS = [
    "pid",
    "name",
    "status",
    "cpu_percent",
    "memory_info",
    "num_threads",
    ATTRIBUT_FICHIERS,
]


def lister_processus() -> list[Processus]:
    """Lit les informations de tous les processus.

    Les valeurs inaccessibles (processus système, droits insuffisants)
    valent None : psutil ne lève pas d'erreur dans ce cas.

    Returns:
        Un objet Processus par processus en cours d'exécution.
    """
    resultat = []
    for proc in psutil.process_iter(ATTRIBUTS):
        info = proc.info
        if info["pid"] == 0:  # « processus inactif » de Windows : pas un vrai
            continue
        memoire = info["memory_info"]
        resultat.append(
            Processus(
                pid=info["pid"],
                name=info["name"] or "?",
                status=info["status"] or "?",
                cpu_pct=info["cpu_percent"] or 0.0,
                rss_mb=round(memoire.rss / OCTETS_PAR_MO, 1) if memoire else 0.0,
                num_threads=info["num_threads"],
                open_files=info[ATTRIBUT_FICHIERS],
            )
        )
    return resultat


def selectionner(
    processus: list[Processus], motifs: list[str], top: int
) -> list[Processus]:
    """Garde les processus surveillés et les plus gourmands.

    Args:
        processus: Tous les processus.
        motifs: Expressions régulières des noms à surveiller (ex. "python").
        top: Nombre de processus à garder pour le top CPU et pour le top RAM.

    Returns:
        Les processus surveillés, le top CPU et le top RAM, sans doublon.
    """
    regex = [re.compile(motif, re.IGNORECASE) for motif in motifs]
    surveilles = [p for p in processus if any(r.search(p.name) for r in regex)]
    top_cpu = sorted(processus, key=lambda p: p.cpu_pct, reverse=True)[:top]
    top_ram = sorted(processus, key=lambda p: p.rss_mb, reverse=True)[:top]
    # Un dictionnaire indexé par PID supprime les doublons
    selection = {p.pid: p for p in [*surveilles, *top_cpu, *top_ram]}
    return list(selection.values())
