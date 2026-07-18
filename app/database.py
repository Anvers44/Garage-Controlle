"""Configuration SQLAlchemy indépendante de Flask.

On n'utilise volontairement pas Flask-SQLAlchemy : les services doivent être
testables et exécutables hors contexte web (le GSMService tourne dans son
propre thread). Chaque service reçoit une ``session_factory`` (un
``sessionmaker``) et gère ses sessions via ``session_scope``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.base import Base
# Import du package modèles pour enregistrer toutes les tables sur Base.metadata.
import app.models  # noqa: F401

SessionFactory = Callable[[], Session]


class Database:
    """Encapsule le moteur SQLAlchemy et la fabrique de sessions."""

    def __init__(self, url: str = "sqlite:///instance/garage.db", echo: bool = False) -> None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(
            url,
            echo=echo,
            future=True,
            connect_args=connect_args,
        )
        self.session_factory: SessionFactory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            future=True,
        )

    def create_all(self) -> None:
        """Crée toutes les tables déclarées sur ``Base.metadata``."""
        Base.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        """Supprime toutes les tables (principalement pour les tests)."""
        Base.metadata.drop_all(self.engine)

    @contextmanager
    def session_scope(self) -> Iterator[Session]:
        """Contexte transactionnel court (commit / rollback / close)."""
        with session_scope(self.session_factory) as session:
            yield session


@contextmanager
def session_scope(session_factory: SessionFactory) -> Iterator[Session]:
    """Ouvre une session, commit en sortie, rollback en cas d'erreur.

    Utilisé par tous les services : ``with session_scope(self._sf) as s: ...``.
    """
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
