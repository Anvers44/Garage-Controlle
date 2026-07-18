"""PhoneService : gestion et interrogation de la whitelist des numéros."""

from __future__ import annotations

import logging
from typing import List, Optional

from app.database import SessionFactory, session_scope
from app.models import Phone
from app.utils.phone_numbers import normalize_number

logger = logging.getLogger(__name__)


class PhoneService:
    """Opérations CRUD et lookup sur les numéros autorisés."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    # ------------------------------------------------------------------ #
    # Lookup (utilisé par le flux GSM)
    # ------------------------------------------------------------------ #
    def get_by_number(self, raw_number: str) -> Optional[Phone]:
        """Retourne le ``Phone`` correspondant au numéro (normalisé) ou ``None``."""
        number = normalize_number(raw_number)
        if not number:
            return None
        with session_scope(self._session_factory) as session:
            return (
                session.query(Phone)
                .filter(Phone.number == number)
                .one_or_none()
            )

    def is_authorized(self, raw_number: str) -> bool:
        """Indique si le numéro est présent ET activé dans la whitelist."""
        phone = self.get_by_number(raw_number)
        return bool(phone and phone.enabled)

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def list_phones(self, enabled_only: bool = False) -> List[Phone]:
        with session_scope(self._session_factory) as session:
            query = session.query(Phone)
            if enabled_only:
                query = query.filter(Phone.enabled.is_(True))
            return query.order_by(Phone.name, Phone.number).all()

    def add_phone(
        self,
        raw_number: str,
        name: Optional[str] = None,
        enabled: bool = True,
    ) -> Phone:
        """Ajoute un numéro (normalisé). Lève ``ValueError`` si déjà présent."""
        number = normalize_number(raw_number)
        if not number:
            raise ValueError("Numéro invalide")
        with session_scope(self._session_factory) as session:
            if session.query(Phone).filter(Phone.number == number).count():
                raise ValueError(f"Le numéro {number} existe déjà")
            phone = Phone(number=number, name=name, enabled=enabled)
            session.add(phone)
            session.flush()
            logger.info("Numéro ajouté : %s (%s)", number, name or "-")
            return phone

    def update_phone(
        self,
        phone_id: int,
        name: Optional[str] = None,
        enabled: Optional[bool] = None,
    ) -> Optional[Phone]:
        with session_scope(self._session_factory) as session:
            phone = session.get(Phone, phone_id)
            if phone is None:
                return None
            if name is not None:
                phone.name = name
            if enabled is not None:
                phone.enabled = enabled
            session.flush()
            return phone

    def set_enabled(self, phone_id: int, enabled: bool) -> Optional[Phone]:
        return self.update_phone(phone_id, enabled=enabled)

    def delete_phone(self, phone_id: int) -> bool:
        with session_scope(self._session_factory) as session:
            phone = session.get(Phone, phone_id)
            if phone is None:
                return False
            session.delete(phone)
            return True
