"""Driver GPIO du relais.

Réutilisable hors de ce projet. En dehors d'un Raspberry Pi (dev / CI), la
librairie ``RPi.GPIO`` est absente : on bascule alors automatiquement sur une
implémentation factice (``_MockGPIO``) afin que les services restent testables.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class _MockGPIO:
    """Backend GPIO factice pour les environnements sans matériel."""

    BCM = "BCM"
    OUT = "OUT"
    HIGH = 1
    LOW = 0

    def setmode(self, mode: Any) -> None:  # noqa: D401 - API mimée
        logger.debug("MockGPIO.setmode(%s)", mode)

    def setwarnings(self, flag: bool) -> None:
        logger.debug("MockGPIO.setwarnings(%s)", flag)

    def setup(self, pin: int, mode: Any, initial: Any = None) -> None:
        logger.debug("MockGPIO.setup(pin=%s, mode=%s, initial=%s)", pin, mode, initial)

    def output(self, pin: int, value: Any) -> None:
        logger.debug("MockGPIO.output(pin=%s, value=%s)", pin, value)

    def cleanup(self, pin: Any = None) -> None:
        logger.debug("MockGPIO.cleanup(%s)", pin)


def _load_gpio() -> Any:
    """Retourne le module ``RPi.GPIO`` s'il est disponible, sinon un mock."""
    try:
        import RPi.GPIO as GPIO  # type: ignore

        return GPIO
    except Exception:  # pragma: no cover - dépend du matériel
        logger.warning("RPi.GPIO indisponible : utilisation du GPIO factice.")
        return _MockGPIO()


class RelayDriver:
    """Pilote un relais optocouplé raccordé sur une broche GPIO.

    Le relais est piloté par impulsion : ``pulse(duration)`` l'active pendant
    ``duration`` secondes puis le désactive. Un verrou garantit qu'une seule
    impulsion se produit à la fois (pas de chevauchement).
    """

    def __init__(
        self,
        pin: int = 17,
        active_high: bool = True,
        default_pulse_seconds: float = 0.5,
        gpio: Any = None,
    ) -> None:
        """Initialise le driver.

        Args:
            pin: broche GPIO (numérotation BCM).
            active_high: ``True`` si le relais est activé par un niveau haut.
            default_pulse_seconds: durée d'impulsion par défaut.
            gpio: backend GPIO injectable (utile pour les tests).
        """
        self._pin = pin
        self._active_high = active_high
        self._default_pulse = default_pulse_seconds
        self._gpio = gpio if gpio is not None else _load_gpio()
        self._lock = threading.Lock()
        self._state = False
        self._setup()

    def _setup(self) -> None:
        self._gpio.setmode(self._gpio.BCM)
        self._gpio.setwarnings(False)
        inactive = self._level(False)
        self._gpio.setup(self._pin, self._gpio.OUT, initial=inactive)
        self._state = False

    def _level(self, active: bool) -> Any:
        """Traduit un état logique (actif/inactif) en niveau GPIO."""
        if active:
            return self._gpio.HIGH if self._active_high else self._gpio.LOW
        return self._gpio.LOW if self._active_high else self._gpio.HIGH

    @property
    def is_active(self) -> bool:
        """État logique courant du relais."""
        return self._state

    def on(self) -> None:
        """Active le relais (maintien)."""
        self._gpio.output(self._pin, self._level(True))
        self._state = True

    def off(self) -> None:
        """Désactive le relais."""
        self._gpio.output(self._pin, self._level(False))
        self._state = False

    def pulse(self, duration: float | None = None) -> float:
        """Active le relais pendant ``duration`` secondes puis le coupe.

        Args:
            duration: durée d'impulsion ; ``None`` → durée par défaut.

        Returns:
            La durée réellement appliquée (secondes).
        """
        pulse_duration = self._default_pulse if duration is None else float(duration)
        with self._lock:
            logger.info("Relais : impulsion de %.3fs (pin %s)", pulse_duration, self._pin)
            self.on()
            try:
                time.sleep(pulse_duration)
            finally:
                self.off()
        return pulse_duration

    def cleanup(self) -> None:
        """Libère la broche GPIO."""
        try:
            self.off()
            self._gpio.cleanup(self._pin)
        except Exception:  # pragma: no cover - best effort
            logger.exception("Erreur lors du cleanup GPIO")
