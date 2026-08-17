# Plateforme Manager

Application simple (Python/Flask) pour documenter des plateformes informatiques :
plateformes clients, environnements (INT/UAT/Production), sizing par environnement
(VM, Kubernetes ou AWS), et journal des opérations (installation, maintenance,
changement de sizing, récupération de logs, incident).

Les données sont stockées dans une base SQLite persistée sur un volume Docker.

## Lancer avec Docker Compose

```bash
docker compose up --build
```

L'application est ensuite disponible sur http://localhost:8000

## Utilisation sur Windows

Deux scripts sont fournis à la racine du dépôt pour éviter de passer par la
ligne de commande :

- **`demarrer-application.bat`** : démarre (et construit si besoin) les
  conteneurs Docker, puis ouvre l'application dans le navigateur par défaut.
  Double-cliquer dessus, ou créer un raccourci sur le bureau pointant vers ce
  fichier pour un lancement en un clic.
- **`mettre-a-jour-et-rebuild.bat`** : récupère les derniers changements de la
  branche courante (`git pull`) puis reconstruit et redémarre les conteneurs
  Docker.

Prérequis : [Docker Desktop](https://www.docker.com/products/docker-desktop)
et [Git](https://git-scm.com/download/win) installés et dans le `PATH`. La
fenêtre de commande reste ouverte à la fin pour voir les éventuelles erreurs ;
fermez-la ou appuyez sur une touche pour la fermer.

## Développement local (sans Docker)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python wsgi.py
```

## Modèle de données

- **Plateforme** : nom, client
- **Environnement** : rattaché à une plateforme, type (INT/UAT/Production) et
  type d'infrastructure (VM, Kubernetes, AWS)
  - **VM** : liste de machines virtuelles (nom, rôle, vCPU, RAM, stockage) ;
    le sizing de l'environnement est la somme des VM
  - **Kubernetes** : nombre de nœuds, vCPU/RAM par nœud, stockage total du
    cluster
  - **AWS** : squelette minimal (région, compte) à détailler ultérieurement
- **Opération** : rattachée à une plateforme (et optionnellement à un
  environnement précis) — installation, maintenance, changement de sizing,
  récupération de logs, incident
