# Spécification – Appels & SMS (Garage Controller GSM)

## 1. Comportement des appels (whitelist)

### Objectif

- Permettre l’ouverture de la porte de garage par simple appel.
- Garder la carte SIM considérée comme "active" par l’opérateur, même si elle reçoit peu de trafic.
- Ne jamais modifier l’installation électrique existante du garage.

### Flux pour un appel entrant

1. Le module SIM800 reçoit un appel entrant :
   - Événements séquentiels sur l’UART :
     - `RING`
     - `+CLIP: "<number>",...`
2. Le driver SIM800 notifie GSMService via un événement `on_clip` (avec le numéro brut).
3. GSMService applique la logique métier suivante :

   - Normaliser le numéro (ex : `+213...` vers `0...`).
   - Vérifier dans la base si ce numéro fait partie de la whitelist (`Phone.enabled = True`).

   - **Si le numéro est autorisé :**
     - Décrocher l’appel via le driver SIM800 (`answer()`).
     - Attendre environ 2 secondes (valeur paramétrable via `Setting`, ex: `call_answer_duration_seconds`, défaut = 2.0).
       - Objectif : générer une activité GSM pour éviter que l’opérateur considère la SIM comme inactive.
     - Raccrocher l’appel (`hangup()`).
     - Déclencher le relais via `RelayService` pendant une durée configurable (défaut = 0.5 s).
     - Journaliser l’événement complet dans l’historique (voir sections ci‑dessous).

   - **Si le numéro n’est pas autorisé :**
     - Ne jamais décrocher.
     - Ne jamais activer le relais.
     - Enregistrer l’événement dans l’historique avec `authorized = False`, `answered = False`, `relay_triggered = False`.

### Journalisation des appels

- Table concernée : `CallHistory` (et éventuellement `RelayEvent` si le relais est déclenché).
- Champs principaux :
  - `phone_id` (nullable si numéro inconnu)
  - `phone_number` (normalisé)
  - `authorized` (bool)
  - `answered` (bool)
  - `relay_triggered` (bool)
  - `date`
  - `duration` (durée d’appel en secondes, si disponible)
- Pour un appel whitelist qui déclenche le garage :
  - `authorized = True`
  - `answered = True`
  - `relay_triggered = True`
- Pour un appel non whitelist :
  - `authorized = False`
  - `answered = False`
  - `relay_triggered = False`

---

## 2. Comportement des SMS de commande (ouverture)

### Objectif

Permettre l’ouverture de la porte par SMS pour les numéros whitelist, en plus des appels.  
Tout en restant simple, robuste et sécurisé.

### Règles générales

- Seuls les numéros whitelist (`Phone.enabled = True`) peuvent déclencher une ouverture par SMS.
- Les commandes SMS sont simples, en texte brut.
- Toutes les commandes et tentatives (valides ou non) sont journalisées.

### Commande d’ouverture par SMS

- Commande par défaut (paramétrable) : `OUVRE`
  - Stockée dans `Setting` sous la clé `sms_command_open` (valeur par défaut : `OUVRE`).
- Optionnel : code de sécurité simple dans le message (ex: `OUVRE 1234`):
  - Stocké dans `Setting` sous la clé `sms_command_pin` (si vide ou nul, pas de PIN requis).
- Texte du SMS (côté utilisateur) :
  - Sans PIN : `OUVRE`
  - Avec PIN : `OUVRE 1234`

### Flux de traitement d’un SMS entrant

1. Le driver SIM800 reçoit un SMS :
   - Utilise les commandes AT SMS (`+CMTI`, `+CMGR`, etc.) et parse le contenu.
   - Notifie GSMService via un événement `on_sms` avec :
     - numéro d’origine (brut)
     - texte du SMS (décodé)
     - timestamp (si disponible)
     - identifiant du message (index SIM).

2. GSMService applique la logique métier suivante :

   - Normaliser le numéro (même logique que pour les appels).
   - Vérifier la whitelist.
   - Si le numéro n’est pas autorisé :
     - Journaliser l’événement comme tentative non autorisée.
     - Ne jamais déclencher le relais.
   - Si le numéro est autorisé :
     - Normaliser le texte : trim, upper-case.
     - Récupérer configuration :
       - `sms_command_open`
       - `sms_command_pin` (optionnel)
       - `sms_reply_enabled`
       - `sms_reply_text`
     - Vérifier que le SMS correspond à une commande valide :
       - Sans PIN : le contenu doit correspondre à la commande (éventuellement tolérer des variations simples).
       - Avec PIN : vérifier à la fois la commande et le PIN.

     - Si commande valide :
       - Déclencher le relais via `RelayService` avec `source = "sms"`.
       - Journaliser un `RelayEvent` (source `sms`) + inscrire dans l’historique des appels/événements.
       - Si `sms_reply_enabled` :
         - Envoyer un SMS de confirmation, ex : `Garage ouvert` (texte dans `sms_reply_text`).

     - Si commande invalide :
       - Journaliser la tentative (source `sms`, commande rejetée).
       - Optionnel : envoyer un SMS d’erreur générique (sans donner d’informations sensibles).

3. Gestion de la mémoire SMS :
   - Après traitement, marquer le SMS comme lu ou le supprimer via le driver SIM800 afin d’éviter de saturer la SIM.

### Rate limiting / anti‑abus

- Mettre en place un mécanisme simple pour éviter les abus involontaires :
  - Par exemple : pas plus d’une ouverture par SMS toutes les X secondes (configurable, ex : `min_interval_sms_open_seconds`, défaut = 30s) par numéro.
- Stocker ces informations dans la base ou en mémoire (avec horodatage du dernier déclenchement par source/numéro).

---

## 3. Rapport quotidien par SMS à 20h

### Objectif

Envoyer chaque soir un SMS de synthèse des événements de la journée (appels + ouvertures) à un ou plusieurs numéros administrateur.  
Permet de surveiller l’activité sans consulter l’interface Web.

### Configuration

- `report_enabled` (bool) – activation/désactivation du rapport quotidien.
- `report_time` (string, format `HH:MM`, défaut = `20:00`).
- `report_recipients` (liste de numéros, par exemple stockée en JSON dans `Setting`).
- `report_include_sms` (bool, inclure ou non les ouvertures par SMS dans le résumé).
- Ces paramètres sont gérés via la page Paramètres (section “Rapports”).

### Contenu du rapport

Pour la journée courante (de 00:00 à 23:59 ou jusqu’à l’heure du rapport) :

- Date.
- Nombre total d’appels reçus.
- Nombre d’appels autorisés.
- Nombre d’ouvertures par appel (relais déclenché).
- Nombre d’ouvertures par SMS (si activé).
- Nombre de tentatives non autorisées (appels + SMS).
- Éventuellement : état GSM (signal, opérateur) et uptime actuel.

Exemple de SMS :

> `[Garage] 2026-07-18  
> Appels: 12 (10 autorisés)  
> Ouvertures appel: 9  
> Ouvertures SMS: 3  
> Tentatives refusées: 2`

Le texte doit rester court (limite de 160 caractères dans l’idéal ou 1–2 SMS maximum).

### Implémentation

- Un service dédié `ReportingService` (ou extension de `HistoryService`) :
  - Méthode `build_daily_report(date)` → retourne une chaîne de texte prête à être envoyée.
  - Méthode `send_daily_report()` → orchestre la récupération des données + envoi via SIM800.
- Un scheduler simple côté Python (thread dédié dans GSMService ou service séparé) :
  - Vérifie régulièrement l’heure système.
  - Lorsque l’heure atteint `report_time` et que le rapport du jour n’a pas encore été envoyé :
    - Appeler `send_daily_report()`.

- Le rapport doit être journalisé comme un événement (dans les logs d’application).

---

## 4. Commandes SMS additionnelles (`CommandService`)

En plus de `OUVRE`, `app/services/command_service.py` route les commandes
suivantes (mots-clés configurables via `Setting`, comme `sms_command_open`) :

- `STOP` — désactive le traitement des commandes SMS (`sms_enabled = false`).
  Reste traitée même si `sms_enabled` est déjà à `false` (sinon `START` ne
  serait jamais lu : verrouillage sans issue).
- `START` — réactive (`sms_enabled = true`).
- `STATUT` — répond un court résumé texte (modem, réseau, signal, état SMS,
  échecs watchdog en cours).
- `AJOUTE <numéro> [nom]` — ajoute un numéro à la whitelist (`Phone.enabled`).
- `RAPPORT` — déclenche l'envoi immédiat du rapport quotidien (voir §3).

Toutes ces commandes (sauf `OUVRE`) sont réservées aux numéros listés dans le
`Setting` JSON `sms_admin_numbers`. **Si cette liste est vide (par défaut),
tout numéro whitelisté est considéré admin** — comportement rétrocompatible,
à restreindre en configurant `sms_admin_numbers` si on veut réserver ces
commandes au(x) propriétaire(s).

Le rate-limiting (`min_interval_sms_open_seconds`) ne s'applique qu'à `OUVRE`.

---

## 5. Watchdog GSM (auto-récupération)

`GSMService` surveille le modem en tâche de fond (sonde `AT` toutes les
`status_refresh_interval` secondes, ~20s) et agit automatiquement en cas de
panne prolongée, sans intervention manuelle :

- `gsm_soft_reset_after_failures` (défaut 3) sondes consécutives en échec →
  reset logiciel du modem (`AT+CFUN=1,1`).
- `gsm_hard_reconnect_after_failures` (défaut 9) sondes en échec, ou threads
  du driver série détectés morts → reconnexion série complète (ferme/rouvre
  `/dev/serial0`, relance les threads).
- `gsm_watchdog_enabled` (défaut `true`) permet de désactiver entièrement ce
  mécanisme si besoin.

En complément, le service systemd (`Type=notify` + `WatchdogSec=120`) reçoit
un battement de cœur tant que `GSMService.is_healthy()` est vrai ; si la
reconnexion complète reste bloquée trop longtemps, systemd tue et redémarre
tout le process (`Restart=on-failure`) — filet de sécurité de dernier
recours au-dessus de la récupération interne.