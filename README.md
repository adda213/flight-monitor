# Surveillance automatique des vols France → Algérie

Ce projet cherche sur Google Flights, par l'intermédiaire de SerpApi, des allers-retours :

- pour 2 adultes et 1 enfant de 3 ans ;
- directs uniquement ;
- vers Alger (`ALG`) ou Oran (`ORN`) ;
- du 17 au 31 octobre 2026 ;
- du 19 décembre 2026 au 2 janvier 2027 ;
- depuis les villes et aéroports français définis dans `config.json`.

Il s'exécute sur GitHub Actions à **06:00, 12:00 et 21:00, heure de Paris**, génère un rapport HTML et l'envoie par e-mail avec Brevo.

## Répartition des aéroports et quota gratuit

Google Flights peut refuser une recherche contenant trop de départs simultanés. Les aéroports sont donc répartis automatiquement sur les trois passages :

| Passage | Aéroports contrôlés |
|---|---|
| 06h | CDG, ORY, BVA, LIL |
| 12h | LYS, MRS, NCE, MPL |
| 21h | TLS, BOD, NTE, SXB, ETZ |

Le code métropolitain `PAR` n'est pas utilisé : SerpApi attend des codes d'aéroport précis. Chaque aéroport est contrôlé une fois par jour et chaque passage effectue une seule recherche par voyage :

```text
2 voyages × 3 passages par jour × 30 jours
= environ 180 recherches par mois
```

L'offre gratuite de SerpApi comprend actuellement 250 recherches par mois. Les recherches échouées et les résultats identiques servis depuis le cache ne sont normalement pas décomptés.

Pour rester sous ce quota, le script ne demande pas les détails de chaque vol retour. Le rapport affiche :

- le prix indicatif aller-retour ;
- l'itinéraire et l'horaire de l'aller ;
- la date du retour ;
- un bouton permettant de sélectionner et confirmer le retour sur Google Flights.

Le prix définitif, les bagages et les horaires doivent toujours être confirmés avant l'achat.

## 1. Créer les comptes

### SerpApi

1. Ouvre <https://serpapi.com/users/sign_up?plan=free>.
2. Crée le compte gratuit avec Google, GitHub ou ton adresse e-mail.
3. Ouvre le tableau de bord SerpApi.
4. Copie ta clé API privée.

Documentation utilisée : <https://serpapi.com/google-flights-api>.

### Brevo

1. Crée un compte sur <https://www.brevo.com/>.
2. Valide une adresse d'expéditeur.
3. Crée une clé API dans les paramètres SMTP/API.

## 2. Mettre le projet sur GitHub

1. Décompresse l'archive.
2. Crée un dépôt GitHub **privé** vide.
3. Dans le dossier `flight-monitor`, exécute :

```bash
git init
git add .
git commit -m "Ajout du moniteur de vols"
git branch -M main
git remote add origin https://github.com/TON_COMPTE/TON_DEPOT.git
git push -u origin main
```

## 3. Ajouter les secrets GitHub

Dans le dépôt : **Settings → Secrets and variables → Actions → New repository secret**.

Ajoute exactement ces quatre secrets :

| Secret | Valeur |
|---|---|
| `SERPAPI_KEY` | clé privée du tableau de bord SerpApi |
| `BREVO_API_KEY` | clé API Brevo |
| `EMAIL_FROM` | adresse d'expéditeur validée dans Brevo |
| `EMAIL_TO` | adresse qui recevra les rapports |

`EMAIL_FROM_NAME` est déjà défini dans le workflow et ne nécessite pas de secret.

## 4. Faire le premier test

Dans GitHub : **Actions → Surveillance des prix des vols → Run workflow**.

Le résultat doit apparaître dans les logs et dans ta boîte mail. Le rapport HTML est également disponible pendant sept jours dans la rubrique **Artifacts** de l'exécution.

## Essai local sans clés API

```bash
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
python flight_monitor.py --demo
```

Ouvre ensuite `reports/latest.html`. Le mode démonstration n'appelle aucune API et n'envoie aucun e-mail.

## Essai local avec les vraies API

Sous PowerShell :

```powershell
$env:SERPAPI_KEY="..."
$env:BREVO_API_KEY="..."
$env:EMAIL_FROM="adresse-validee@example.com"
$env:EMAIL_TO="ton-adresse@example.com"
python flight_monitor.py
```

Pour tester la recherche sans envoyer d'e-mail :

```powershell
$env:SERPAPI_KEY="..."
python flight_monitor.py --no-email
```

Pour forcer un groupe lors d'un lancement manuel :

```powershell
# 0 = Paris/Nord, 1 = Sud-Est, 2 = Ouest/Sud-Ouest/Est
$env:ORIGIN_GROUP_INDEX="0"
python flight_monitor.py --no-email
```

## Modifier les aéroports ou les dates

Tout se trouve dans `config.json`, notamment dans `origin_groups`. Utilise des codes d'aéroport précis comme `CDG` et `ORY`, jamais le code métropolitain `PAR`.

Les deux éléments de `trips` correspondent à des dates fixes d'aller et de retour.

## Tests

```bash
python -m unittest discover -s tests -v
```

## Sécurité et fonctionnement

- La clé SerpApi et la clé Brevo ne doivent jamais être enregistrées dans `config.json` ni poussées dans Git.
- Le filtre SerpApi `stops=1` exige des vols sans escale.
- Le script vérifie également que chaque résultat aller ne contient qu'un seul segment.
- L'historique est restauré et sauvegardé avec le cache GitHub Actions.
- Une erreur sur un voyage n'empêche pas l'autre recherche ; le rapport indique les recherches incomplètes.
- Un prix affiché n'est pas une réservation et peut changer avant le paiement.
