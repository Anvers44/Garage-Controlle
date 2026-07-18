# Spécification – Interface Web & Dashboard

## Technologies

- Flask
- Flask-SocketIO
- Bootstrap 5 + Bootstrap Icons
- Tout en local (pas de CDN si possible).

## Pages

1. Dashboard
   - Affiche en temps réel :
     - CPU, RAM, température CPU, uptime, charge système.
     - Espace disque, hostname, IP, voltage / throttling si disponible.
     - État GSM : signal, opérateur, IMEI, SIM ready, network registered.
     - Stats du jour : nombre d’appels, nombre d’ouvertures.
     - État relais, version logicielle, date/heure.
   - Actualisation via SocketIO ou AJAX.

2. GSM
   - Affiche :
     - Signal, opérateur, IMEI, ICCID.
     - État SIM, état réseau.
     - Dernières commandes AT.
     - Logs UART (récents).
   - Actions :
     - Bouton reboot modem.
     - Bouton test communication.

3. Relais
   - Affiche :
     - État actuel du relais.
     - Durée d’impulsion configurée.
     - Compteur d’activations.
     - Historique des déclenchements.
   - Actions :
     - Déclenchement manuel du relais.

4. Numéros
   - CRUD complet sur les numéros autorisés :
     - Ajouter, modifier, supprimer.
     - Activer / désactiver.
     - Recherche, tri.
     - Validation et normalisation automatique des numéros (ex : +213… → 0…).

5. Historique
   - Liste paginée des appels :
     - Date, numéro, nom, autorisé, répondu, relais déclenché, durée.
     - Recherche, filtre, pagination.
     - Export CSV.

6. Paramètres
   - Paramètres divers :
     - GPIO (pin relais).
     - Durée impulsion.
     - Nom SSID AP Wi-Fi, mot de passe.
     - Timeout GSM.
     - Paramètres SIM.
   - Import/export configuration (JSON ou équivalent).
   - Sauvegarde automatique côté `Setting` (clé/valeur).

## Sécurité

- Authentification locale (login/password).
- Mots de passe hashés.
- CSRF protection.
- Validation des formulaires côté serveur.
- Journalisation de toutes les actions importantes.