"""Services métier du Garage Controller GSM.

``build_services`` assemble l'ensemble des services à partir d'une base de
données et des drivers matériels. Cette fabrique constitue le point de câblage
unique, réutilisable aussi bien par le backend (``run.py``) que par les tests.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.database import Database
from app.hardware.gpio import RelayDriver
from app.hardware.sim800 import SIM800
from app.services.auth_service import AuthService
from app.services.gsm_service import GSMService
from app.services.history_service import HistoryService
from app.services.phone_service import PhoneService
from app.services.relay_service import RelayService
from app.services.reporting_service import ReportingScheduler, ReportingService
from app.services.settings_service import SettingsService

__all__ = [
    "GSMService",
    "PhoneService",
    "RelayService",
    "HistoryService",
    "SettingsService",
    "ReportingService",
    "ReportingScheduler",
    "AuthService",
    "ServiceContainer",
    "build_services",
]


@dataclass
class ServiceContainer:
    """Regroupe tous les services câblés ensemble."""

    settings: SettingsService
    phones: PhoneService
    relay: RelayService
    history: HistoryService
    reporting: ReportingService
    gsm: GSMService
    auth: AuthService


def build_services(database: Database, sim800: SIM800, relay_driver: RelayDriver) -> ServiceContainer:
    """Câble et retourne l'ensemble des services.

    Args:
        database: base de données déjà initialisée (``create_all`` fait).
        sim800: driver SIM800 (non encore connecté ; ``GSMService.start`` s'en charge).
        relay_driver: driver GPIO du relais.
    """
    sf = database.session_factory

    settings = SettingsService(sf)
    settings.ensure_defaults()

    pulse = settings.get_float("relay_pulse_seconds", default=0.5)

    phones = PhoneService(sf)
    relay = RelayService(sf, relay_driver, default_pulse_seconds=pulse)
    history = HistoryService(sf)
    reporting = ReportingService(history, settings, sim800)
    auth = AuthService(settings)
    auth.ensure_admin()
    gsm = GSMService(
        sim800=sim800,
        phone_service=phones,
        relay_service=relay,
        history_service=history,
        settings_service=settings,
        reporting_service=reporting,
    )

    return ServiceContainer(
        settings=settings,
        phones=phones,
        relay=relay,
        history=history,
        reporting=reporting,
        gsm=gsm,
        auth=auth,
    )
