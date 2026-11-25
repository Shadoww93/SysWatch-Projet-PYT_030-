"""Accès à la base SQLite : création, insertions, SLA et purge."""

import logging
import sqlite3
import time
from collections.abc import Sequence
from dataclasses import astuple, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SECONDES_PAR_JOUR = 86_400

TABLES = (
    "host_metrics",
    "cpu_cores",
    "disk_partitions",
    "process_metrics",
    "service_health",
    "system_incidents",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS host_metrics (
    id               INTEGER PRIMARY KEY,
    timestamp        INTEGER NOT NULL,
    hostname         TEXT    NOT NULL,
    cpu_pct          REAL    NOT NULL,
    load_1m          REAL,
    ram_used_mb      REAL    NOT NULL,
    ram_pct          REAL    NOT NULL,
    swap_pct         REAL    NOT NULL,
    disk_read_mb_s   REAL    NOT NULL,
    disk_write_mb_s  REAL    NOT NULL,
    cpu_user_pct     REAL    NOT NULL,
    cpu_system_pct   REAL    NOT NULL,
    cpu_iowait_pct   REAL,
    load_5m          REAL,
    load_15m         REAL,
    ram_total_mb     REAL    NOT NULL,
    ram_available_mb REAL    NOT NULL,
    ram_cached_mb    REAL,
    disk_read_iops   REAL    NOT NULL,
    disk_write_iops  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_host_ts ON host_metrics (timestamp);

CREATE TABLE IF NOT EXISTS cpu_cores (
    id        INTEGER PRIMARY KEY,
    timestamp INTEGER NOT NULL,
    core      INTEGER NOT NULL,
    cpu_pct   REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cores_ts ON cpu_cores (timestamp);

CREATE TABLE IF NOT EXISTS disk_partitions (
    id         INTEGER PRIMARY KEY,
    timestamp  INTEGER NOT NULL,
    mountpoint TEXT    NOT NULL,
    total_gb   REAL    NOT NULL,
    used_gb    REAL    NOT NULL,
    usage_pct  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_partitions_ts ON disk_partitions (timestamp);
CREATE INDEX IF NOT EXISTS idx_partitions_point_ts
    ON disk_partitions (mountpoint, timestamp);

CREATE TABLE IF NOT EXISTS process_metrics (
    id          INTEGER PRIMARY KEY,
    timestamp   INTEGER NOT NULL,
    pid         INTEGER NOT NULL,
    name        TEXT    NOT NULL,
    status      TEXT    NOT NULL,
    cpu_pct     REAL    NOT NULL,
    rss_mb      REAL    NOT NULL,
    num_threads INTEGER,
    open_files  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_processus_ts ON process_metrics (timestamp);

CREATE TABLE IF NOT EXISTS service_health (
    id               INTEGER PRIMARY KEY,
    timestamp        INTEGER NOT NULL,
    service_name     TEXT    NOT NULL,
    url              TEXT    NOT NULL,
    status_code      INTEGER,
    response_time_ms REAL,
    is_healthy       INTEGER NOT NULL CHECK (is_healthy IN (0, 1)),
    ssl_days_left    INTEGER,
    error_msg        TEXT
);
CREATE INDEX IF NOT EXISTS idx_sante_ts ON service_health (timestamp);
CREATE INDEX IF NOT EXISTS idx_sante_service_ts
    ON service_health (service_name, timestamp);

CREATE TABLE IF NOT EXISTS system_incidents (
    id              INTEGER PRIMARY KEY,
    timestamp       INTEGER NOT NULL,
    category        TEXT    NOT NULL,
    severity        TEXT    NOT NULL CHECK (severity IN ('WARNING', 'CRITICAL')),
    resource_name   TEXT    NOT NULL,
    metric_value    REAL    NOT NULL,
    threshold_value REAL    NOT NULL,
    description     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_incidents_ts ON system_incidents (timestamp);
CREATE INDEX IF NOT EXISTS idx_incidents_categorie_ts
    ON system_incidents (category, timestamp);
"""


def connecter(chemin: str) -> sqlite3.Connection:
    """Ouvre la base, active le mode WAL et crée les tables si besoin.

    Args:
        chemin: Chemin du fichier SQLite, ou ":memory:" pour les tests.

    Returns:
        La connexion ouverte.
    """
    Path(chemin).parent.mkdir(parents=True, exist_ok=True)  # crée data/ si besoin
    conn = sqlite3.connect(chemin)
    conn.row_factory = sqlite3.Row
    mode = conn.execute("PRAGMA journal_mode=WAL;").fetchone()[0]
    conn.executescript(SCHEMA)
    logger.info("Base %s ouverte (journal_mode=%s)", chemin, mode)
    return conn


def inserer(
    conn: sqlite3.Connection, table: str, horodatage: int, lignes: Sequence[Any]
) -> None:
    """Insère une liste d'objets (dataclasses) dans une table.

    Les colonnes utilisées sont "timestamp" suivie des noms des champs de la
    dataclass, qui sont exactement les noms des colonnes de la table.

    Args:
        conn: Connexion SQLite.
        table: Nom de la table (doit faire partie de TABLES).
        horodatage: Instant de la mesure (secondes Unix).
        lignes: Objets à insérer, tous du même type.

    Raises:
        ValueError: Si la table n'est pas une table connue.
    """
    if table not in TABLES:
        raise ValueError(f"Table inconnue : {table}")
    if not lignes:
        return

    colonnes = ["timestamp", *(champ.name for champ in fields(lignes[0]))]
    marqueurs = ", ".join("?" for _ in colonnes)
    requete = f"INSERT INTO {table} ({', '.join(colonnes)}) VALUES ({marqueurs})"
    valeurs = [(horodatage, *astuple(ligne)) for ligne in lignes]
    with conn:
        conn.executemany(requete, valeurs)


def sla_par_service(conn: sqlite3.Connection, depuis: int) -> dict[str, float]:
    """Calcule le taux de disponibilité (SLA) de chaque service.

    Args:
        conn: Connexion SQLite.
        depuis: Début de la période de calcul (secondes Unix).

    Returns:
        Le SLA en pourcentage, par nom de service.
    """
    lignes = conn.execute(
        "SELECT service_name, 100.0 * AVG(is_healthy) AS sla "
        "FROM service_health WHERE timestamp >= ? GROUP BY service_name",
        (depuis,),
    ).fetchall()
    return {ligne["service_name"]: round(ligne["sla"], 2) for ligne in lignes}


def purger(
    conn: sqlite3.Connection, retention_jours: int, maintenant: float | None = None
) -> int:
    """Supprime les données plus anciennes que la durée de rétention.

    Args:
        conn: Connexion SQLite.
        retention_jours: Durée de conservation, en jours.
        maintenant: Instant de référence (secondes Unix). Par défaut,
            l'heure actuelle ; on le fixe dans les tests.

    Returns:
        Le nombre total de lignes supprimées.
    """
    if maintenant is None:
        maintenant = time.time()
    limite = int(maintenant - retention_jours * SECONDES_PAR_JOUR)

    supprimees = 0
    with conn:
        for table in TABLES:
            # Le nom de table vient de la constante TABLES, jamais de l'extérieur
            curseur = conn.execute(
                f"DELETE FROM {table} WHERE timestamp < ?", (limite,)
            )
            supprimees += curseur.rowcount

    logger.info("Purge : %d ligne(s) supprimée(s)", supprimees)
    return supprimees
