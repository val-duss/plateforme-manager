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
