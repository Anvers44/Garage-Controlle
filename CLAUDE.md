# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> Le code, les docstrings et les commentaires sont en **français** : garder cette convention.

## But du projet

Ouverture de porte de garage via Raspberry Pi 3B+ et module GSM SIM800. Le Pi pilote
un relais 5V optocouplé soudé en parallèle sur le bouton de la télécommande (aucune
modification de l'installation existante). Un appel ou un SMS d'un numéro whitelisté
déclenche une impulsion du relais.

Matériel : Raspberry Pi 3B+, HAT GSM ITEAD SIM800 v2.0 (UART `/dev/serial0`), relais 5V
optocouplé (GPIO 17 par défaut). Fonctionne **100 % en local**, sans Cloud ni API externe.

## Commandes

```bash
# Installation sur le Pi (venv + service systemd + accès dialout)
sudo ./install.sh

# Dev SANS matériel (faux port série + GPIO mock) — pas de Pi requis
GARAGE_FAKE_SERIAL=1 GARAGE_LOG_LEVEL=DEBUG .venv/bin/python run.py
# → interface web sur http://localhost:8080 (login par défaut: admin / admin)

# Backend seul, sans interface web
GARAGE_WEB_ENABLED=0 GARAGE_FAKE_SERIAL=1 .venv/bin/python run.py

# Service systemd (sur le Pi)
systemctl status garage-controller
journalctl -u garage-controller -f
```

Variables d'environnement (voir `app/config/config.py` pour la liste complète) :
`GARAGE_FAKE_SERIAL`, `GARAGE_WEB_ENABLED`, `GARAGE_WEB_HOST`, `GARAGE_WEB_PORT`,
`GARAGE_LOG_LEVEL`, `GARAGE_SERIAL_PORT`, `GARAGE_RELAY_PIN`, `GARAGE_RELAY_ACTIVE_HIGH`,
`GARAGE_DATABASE_URL`, `GARAGE_LOG_DIR`, `GARAGE_SQL_ECHO`.

> Le dossier `tests/` n'existe pas encore. Le code est conçu pour être testable hors
> matériel : injecter `FakeSerial` (`app/hardware/fake_serial.py`) dans `SIM800`, le
> `_MockGPIO` de `RelayDriver`, et une base SQLite `:memory:` dans `Database`.

## Architecture

Le point clé : **un seul process** héberge le backend GSM (threads série + relais +
scheduler) **et** l'interface web Flask. Les deux partagent le même `ServiceContainer`
car ils partagent le même modem et le même GPIO — il ne peut y avoir qu'un seul
propriétaire de `/dev/serial0` et du relais.

Chaîne de démarrage (`run.py` → `app/backend.py`) :

```
Config.from_env()
  → Backend(config)               # crée Database, SIM800, RelayDriver, SystemMonitor
    → backend.initialize()        # create_all() + build_services() = ServiceContainer
    → backend.start()             # gsm.start() : connect() modem, threads, scheduler
  → create_app(backend)           # Flask réutilise backend.services (même conteneur)
```

Arrêt propre sur SIGINT/SIGTERM (`systemctl stop`) : le serveur web s'arrête via
`werkzeug make_server` (pas `app.run`), puis `backend.stop()` libère modem et GPIO.

### Séparation en couches (à respecter strictement)

- **`app/hardware/`** — drivers matériels réutilisables. **Aucune** dépendance à Flask,
  la base ou les services. `SIM800` est le **seul** endroit autorisé à parler à l'UART
  et à parser l'AT. `RelayDriver` et `SIM800` basculent automatiquement sur mock/fake
  hors Pi (RPi.GPIO absent → `_MockGPIO`).
- **`app/services/`** — logique métier. `build_services()` (dans `services/__init__.py`)
  est le **point de câblage unique** ; il retourne un `ServiceContainer` (dataclass).
  Les services reçoivent une `session_factory` SQLAlchemy et ouvrent des sessions courtes
  via `session_scope` (`app/database.py`) — **pas** de Flask-SQLAlchemy, pour rester
  exécutable dans le thread GSM hors contexte web.
- **`app/web/`** — présentation uniquement. Routes ultra-fines : elles récupèrent le
  `ServiceContainer` via `get_services()` (`web/helpers.py`) et orchestrent, **jamais**
  de logique métier. Un blueprint par domaine (`auth`, `dashboard`, `phones`, `history`,
  `relay`, `settings`). CSS/JS servis en local (aucun CDN) pour fonctionner sur le point
  d'accès Wi-Fi hors ligne. Auth par session + CSRF maison (`web/security.py`, sans
  Flask-WTF).
- **`app/models/`** — modèles SQLAlchemy (`Base` déclaratif dans `models/base.py`,
  `TimestampMixin` en heure **locale** car les rapports raisonnent sur la journée locale).

### GSMService — le cœur

`app/services/gsm_service.py` branche les callbacks du driver et implémente les flux
(voir `docs/spec-sms.md`) :

- **Appel** whitelisté → `answer()` → attente ~2s → `hangup()` → impulsion relais → historique.
- **SMS** whitelisté avec commande valide (`OUVRE [PIN]`) → impulsion relais → historique
  (+ réponse SMS optionnelle). Rate-limité par numéro.
- **Rapport quotidien** par SMS → délégué à `ReportingScheduler`.

Le GSMService ne parle jamais à Flask et ne parse aucun AT (tout le parsing vit dans
`SIM800`). Les numéros sont normalisés via `app/utils/phone_numbers.py`.

### Threading du driver SIM800

`SIM800` utilise deux threads : `_reader_loop` (unique lecteur série, découpe les lignes,
détecte le prompt `>` d'envoi SMS, classe chaque ligne en réponse-de-commande ou URC) et
`_worker_loop` (exécute les callbacks/actions URC hors du lecteur pour éviter tout blocage
et la réentrance). `command()` est sérialisé par un verrou et attend un terminateur
(`OK`/`ERROR`). Les URC (RING, +CLIP, +CMTI, NO CARRIER, +CREG) sont dispatchés vers le
worker.

### Deux niveaux de configuration

- **`Config`** (`app/config/config.py`) : câblage bas niveau figé au démarrage (port série,
  broche GPIO, chemins, port web), surchargeable par variables d'environnement.
- **`Setting`** (modèle DB + `SettingsService`) : paramètres applicatifs modifiables **à
  chaud** depuis l'interface (durée d'impulsion, commande SMS, PIN, rate limit, rapport…).

## Contraintes de qualité

- PEP8, type hints, docstrings, logging structuré avec rotation (`app/utils/logging.py`).
- Services testables indépendamment ; drivers SIM800/GPIO réutilisables ailleurs.
- Routes Flask ultra-fines : orchestration + sérialisation uniquement.
- Aucune dépendance Cloud, aucune API externe, pas de duplication, pas de "quick and dirty".
