"""Drivers matériels.

Contrainte d'architecture (voir ``CLAUDE.md``) : ces modules ne connaissent ni
Flask ni HTTP, et le SIM800 est le seul endroit où l'on parse les réponses AT.
"""

from app.hardware.gpio import RelayDriver
from app.hardware.sim800 import SIM800, SIM800Error, SMSMessage

__all__ = ["SIM800", "SIM800Error", "SMSMessage", "RelayDriver"]
