"""Module C : tests de santé des services HTTP/HTTPS, en parallèle."""

import http.client
import json
import socket
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any
from urllib.parse import urlsplit

from syswatch.models import EtatService

SECONDES_PAR_JOUR = 86_400


def contient_cle_json(corps: bytes, cle: str) -> bool:
    """Indique si une réponse est un objet JSON contenant une clé donnée.

    Args:
        corps: Contenu brut de la réponse HTTP.
        cle: Clé attendue (ex. "status").

    Returns:
        True si le corps est un objet JSON qui contient la clé.
    """
    try:
        donnees = json.loads(corps)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    return isinstance(donnees, dict) and cle in donnees


def jours_avant_expiration(date_fin: str, maintenant: float | None = None) -> int:
    """Convertit la date d'expiration d'un certificat en jours restants.

    Args:
        date_fin: Champ "notAfter" du certificat
            (ex. "Jun  1 12:00:00 2027 GMT").
        maintenant: Instant de référence (secondes Unix). Par défaut,
            l'heure actuelle ; on le fixe dans les tests.

    Returns:
        Le nombre de jours entiers restants (négatif si le certificat a expiré).
    """
    if maintenant is None:
        maintenant = time.time()
    expiration = ssl.cert_time_to_seconds(date_fin)
    return int((expiration - maintenant) // SECONDES_PAR_JOUR)


def lire_jours_ssl(url: str, timeout: float) -> int | None:
    """Lit le certificat TLS d'une URL HTTPS et calcule ses jours restants.

    Args:
        url: Adresse du service.
        timeout: Délai maximal de connexion, en secondes.

    Returns:
        Les jours restants avant expiration, ou None si l'URL n'est pas en
        HTTPS.
    """
    adresse = urlsplit(url)
    if adresse.scheme != "https" or adresse.hostname is None:
        return None
    contexte = ssl.create_default_context()
    hote = adresse.hostname
    with socket.create_connection((hote, adresse.port or 443), timeout) as brut:
        with contexte.wrap_socket(brut, server_hostname=hote) as tls:
            certificat = tls.getpeercert()
    return jours_avant_expiration(certificat["notAfter"])


def verifier_service(
    service: dict[str, Any], timeout: float, user_agent: str
) -> EtatService:
    """Teste un service : code HTTP, temps de réponse, clé JSON et certificat.

    Args:
        service: Description du service (name, url, expected_status,
            json_key).
        timeout: Délai maximal, en secondes.
        user_agent: Nom sous lequel l'agent se présente au serveur
            (certains sites refusent les requêtes anonymes).

    Returns:
        Le résultat du test ; is_healthy vaut False en cas de problème.
    """
    url = service["url"]
    code: int | None = None
    duree_ms: float | None = None
    erreur: str | None = None
    corps = b""
    requete = urllib.request.Request(url, headers={"User-Agent": user_agent})

    debut = time.perf_counter()
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            # urlopen rend la main dès les en-têtes reçus : c'est le TTFB
            duree_ms = round((time.perf_counter() - debut) * 1000, 1)
            code = reponse.status
            corps = reponse.read()
    except urllib.error.HTTPError as exc:  # le serveur répond, mais en 4xx/5xx
        duree_ms = round((time.perf_counter() - debut) * 1000, 1)
        code = exc.code
        erreur = f"HTTP {exc.code}"
    except (OSError, ValueError, http.client.HTTPException) as exc:
        erreur = f"Injoignable : {exc}"  # DNS, refus, délai dépassé...

    sain = code == service["expected_status"]
    if code is not None and not sain:
        erreur = erreur or f"Code {code}, attendu {service['expected_status']}"

    cle = service.get("json_key")
    if sain and cle and not contient_cle_json(corps, cle):
        sain = False
        erreur = f"Clé JSON absente : {cle}"

    jours_ssl = None
    if code is not None:  # inutile de lire le certificat d'un service injoignable
        try:
            jours_ssl = lire_jours_ssl(url, timeout)
        except OSError as exc:  # comprend ssl.SSLError (certificat invalide...)
            erreur = erreur or f"Certificat illisible : {exc}"

    return EtatService(
        service_name=service["name"],
        url=url,
        status_code=code,
        response_time_ms=duree_ms,
        is_healthy=sain,
        ssl_days_left=jours_ssl,
        error_msg=erreur,
    )


def verifier_services(
    services: list[dict[str, Any]],
    timeout: float,
    user_agent: str,
    executeur: ThreadPoolExecutor,
) -> list[EtatService]:
    """Teste tous les services en parallèle, un thread par service.

    Args:
        services: Liste des services décrits dans config.json.
        timeout: Délai maximal par service, en secondes.
        user_agent: Nom sous lequel l'agent se présente aux serveurs.
        executeur: Groupe de threads qui exécute les tests.

    Returns:
        Les résultats, dans l'ordre de la liste des services.
    """
    tester = partial(verifier_service, timeout=timeout, user_agent=user_agent)
    return list(executeur.map(tester, services))
