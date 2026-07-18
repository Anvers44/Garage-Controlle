"""Garage Controller GSM – application package.

Le package ``app`` regroupe :

- ``app.models``   : modèles SQLAlchemy (persistance).
- ``app.hardware`` : drivers matériels (SIM800, GPIO) — sans Flask ni HTTP.
- ``app.services`` : logique métier (GSMService, RelayService, …).
- ``app.utils``    : helpers transverses (normalisation de numéros, …).

L'interface Web (``app.web``) n'est qu'une couche de présentation et ne doit
contenir aucune logique métier : elle se contente d'orchestrer les services.
"""

__all__ = ["__version__"]

__version__ = "1.0.0"
