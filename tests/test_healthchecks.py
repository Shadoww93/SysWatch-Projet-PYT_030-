"""Tests des tests de santé : parsing JSON, certificats et service local."""

import ssl
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from syswatch.healthchecks import (
    contient_cle_json,
    jours_avant_expiration,
    verifier_service,
)

AGENT = "SysWatch-Test/1.0"


def test_cle_json_presente() -> None:
    assert contient_cle_json(b'{"status": "healthy"}', "status") is True


def test_cle_json_absente() -> None:
    assert contient_cle_json(b'{"etat": "ok"}', "status") is False


def test_reponse_pas_en_json() -> None:
    assert contient_cle_json(b"<html>OK</html>", "status") is False


def test_json_qui_n_est_pas_un_objet() -> None:
    assert contient_cle_json(b"[1, 2, 3]", "status") is False


def test_jours_avant_expiration() -> None:
    maintenant = ssl.cert_time_to_seconds("Jan  1 00:00:00 2027 GMT")
    assert jours_avant_expiration("Jan 11 00:00:00 2027 GMT", maintenant) == 10


def test_certificat_expire() -> None:
    maintenant = ssl.cert_time_to_seconds("Jan 11 00:00:00 2027 GMT")
    assert jours_avant_expiration("Jan  1 00:00:00 2027 GMT", maintenant) == -10


class FauxService(BaseHTTPRequestHandler):
    """Petit serveur HTTP local : /health répond en JSON, /panne en 503."""

    agent_recu: str | None = None

    def do_GET(self) -> None:  # noqa: N802 (nom imposé par http.server)
        FauxService.agent_recu = self.headers.get("User-Agent")
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status": "healthy"}')
        else:
            self.send_response(503)
            self.end_headers()

    def log_message(self, *args: object) -> None:  # pas d'affichage parasite
        pass


@pytest.fixture
def url_locale() -> Iterator[str]:
    """Démarre le faux service sur un port libre, puis l'arrête."""
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), FauxService)
    thread = threading.Thread(target=serveur.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{serveur.server_address[1]}"
    serveur.shutdown()
    serveur.server_close()


def test_service_sain(url_locale: str) -> None:
    service = {
        "name": "api",
        "url": f"{url_locale}/health",
        "expected_status": 200,
        "json_key": "status",
    }
    etat = verifier_service(service, timeout=2, user_agent=AGENT)
    assert etat.is_healthy is True
    assert etat.status_code == 200
    assert etat.response_time_ms is not None
    assert FauxService.agent_recu == AGENT  # l'agent s'est bien identifié


def test_service_en_panne(url_locale: str) -> None:
    service = {
        "name": "api",
        "url": f"{url_locale}/panne",
        "expected_status": 200,
        "json_key": None,
    }
    etat = verifier_service(service, timeout=2, user_agent=AGENT)
    assert etat.is_healthy is False
    assert etat.status_code == 503


def test_service_injoignable() -> None:
    service = {
        "name": "absent",
        "url": "http://127.0.0.1:1/",
        "expected_status": 200,
        "json_key": None,
    }
    etat = verifier_service(service, timeout=2, user_agent=AGENT)
    assert etat.is_healthy is False
    assert etat.status_code is None
    assert "Injoignable" in (etat.error_msg or "")
