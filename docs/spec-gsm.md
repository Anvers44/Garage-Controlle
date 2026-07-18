# Spécification – Service GSM & SIM800

## Schéma matériel

- SIM800 HAT ITEAD v2.0 sur Raspberry Pi 3B+.
- UART : /dev/serial0 (déjà configuré avec enable_uart=1 et testé via commandes AT).

## Comportement GSM

- Le SIM800 écoute en permanence les événements série.
- En cas d’appel entrant :
  - Réception de `RING`, puis `+CLIP` avec numéro appelant.
  - Extraire et normaliser le numéro (ex : +213… vers 0…).
  - Vérifier si le numéro est autorisé (whitelist en base).
  - Si autorisé :
    - Décrocher l’appel.
    - Attendre ~2 secondes (activité GSM pour garder la SIM “vivante”).
    - Raccrocher.
    - Activer le relais pendant une durée configurable (0.5 s par défaut).
    - Journaliser l’événement complet.
  - Si non autorisé :
    - Ne jamais décrocher.
    - Ne jamais activer le relais.
    - Journaliser l’événement.

## Driver SIM800 (hardware)

- Classe réutilisable dans d’autres projets.
- Gestion :
  - Connexion / reconnexion automatique.
  - Timeout.
  - Lecture UART dans un thread dédié.
  - File d’attente de commandes.
  - Événements (callbacks ou système d’évènements).
- Méthodes attendues :
  - `connect()`
  - `disconnect()`
  - `command(cmd: str, timeout: float = ...) -> str`
  - `send(data: bytes) -> None`
  - `get_signal() -> int`
  - `get_operator() -> str`
  - `get_imei() -> str`
  - `get_iccid() -> str`
  - `network_registered() -> bool`
  - `sim_ready() -> bool`
  - `answer() -> None`
  - `hangup() -> None`
  - `call(number: str) -> None`
  - `send_sms(number: str, text: str) -> None`
  - `read_sms(...)`
  - `delete_sms(...)`
  - `list_sms(...)`

- Événements à exposer :
  - `on_ring`
  - `on_clip`
  - `on_sms`
  - `on_network`
  - `on_no_carrier`

- Parsing AT :
  - Parser robuste.
  - **Interdiction** de parser les réponses AT dans le reste du projet.
  - Toute la logique de parsing est encapsulée dans le driver SIM800.

## Service GSM (métier)

- Service indépendant du web.
- Tourne dans un thread séparé.
- Utilise le driver SIM800 pour :
  - Recevoir les événements (ring, clip, sms).
  - Décider quoi faire (en s’appuyant sur PhoneService, RelayService, HistoryService).
- Ne parle jamais directement à Flask/SocketIO.