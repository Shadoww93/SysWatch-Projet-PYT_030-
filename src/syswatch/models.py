"""Structures de données échangées entre les modules.

Chaque classe correspond à une ligne d'une table SQLite : les noms des
champs sont exactement les noms des colonnes.
"""

from dataclasses import dataclass


@dataclass
class MesureHote:
    """Mesures globales de la machine (table host_metrics)."""

    hostname: str
    cpu_pct: float
    load_1m: float | None
    ram_used_mb: float
    ram_pct: float
    swap_pct: float
    disk_read_mb_s: float
    disk_write_mb_s: float
    cpu_user_pct: float
    cpu_system_pct: float
    cpu_iowait_pct: float | None
    load_5m: float | None
    load_15m: float | None
    ram_total_mb: float
    ram_available_mb: float
    ram_cached_mb: float | None
    disk_read_iops: float
    disk_write_iops: float


@dataclass
class UsageCoeur:
    """Utilisation d'un cœur de processeur (table cpu_cores)."""

    core: int
    cpu_pct: float


@dataclass
class Partition:
    """Occupation d'une partition (table disk_partitions)."""

    mountpoint: str
    total_gb: float
    used_gb: float
    usage_pct: float


@dataclass
class Processus:
    """Mesures d'un processus (table process_metrics)."""

    pid: int
    name: str
    status: str
    cpu_pct: float
    rss_mb: float
    num_threads: int | None
    open_files: int | None


@dataclass
class EtatService:
    """Résultat d'un test de santé HTTP (table service_health)."""

    service_name: str
    url: str
    status_code: int | None
    response_time_ms: float | None
    is_healthy: bool
    ssl_days_left: int | None
    error_msg: str | None


@dataclass
class Incident:
    """Dépassement de seuil détecté (table system_incidents)."""

    category: str
    severity: str
    resource_name: str
    metric_value: float
    threshold_value: float
    description: str
