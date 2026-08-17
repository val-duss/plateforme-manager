"""Calcul du statut quotidien (RAS / alerte / non vérifié) des environnements."""

from datetime import date, timedelta

from .models import CheckStatus, DailyCheck, EnvironmentAlert

MONTH_NAMES_FR = [
    "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre",
]

WEEKDAY_NAMES_FR = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
WEEKDAY_NAMES_FR_LONG = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def compute_environment_statuses(environments, start_date, end_date):
    """Retourne (days, status_by_env) pour la période [start_date, end_date] incluse.

    status_by_env est un dict {environment_id: {date: CheckStatus.OK|CheckStatus.ALERT|None}}.
    None signifie « non vérifié ». Une alerte ouverte pendant tout ou partie du
    jour prévaut toujours sur une confirmation RAS ce même jour.
    """
    env_ids = [e.id for e in environments]
    day_count = (end_date - start_date).days + 1
    days = [start_date + timedelta(days=i) for i in range(day_count)]

    if not env_ids:
        return days, {}

    ok_days_by_env = {}
    for check in DailyCheck.query.filter(
        DailyCheck.environment_id.in_(env_ids),
        DailyCheck.check_date >= start_date,
        DailyCheck.check_date <= end_date,
    ):
        ok_days_by_env.setdefault(check.environment_id, set()).add(check.check_date)

    alerts_by_env = {}
    for alert in EnvironmentAlert.query.filter(EnvironmentAlert.environment_id.in_(env_ids)):
        alerts_by_env.setdefault(alert.environment_id, []).append(alert)

    today = date.today()

    status_by_env = {}
    for env_id in env_ids:
        env_alerts = alerts_by_env.get(env_id, [])
        env_ok_days = ok_days_by_env.get(env_id, set())
        day_statuses = {}
        for day in days:
            if day > today:
                day_statuses[day] = None
                continue
            has_alert = any(
                alert.opened_at.date() <= day <= (alert.closed_at.date() if alert.closed_at else today)
                for alert in env_alerts
            )
            if has_alert:
                day_statuses[day] = CheckStatus.ALERT
            elif day in env_ok_days:
                day_statuses[day] = CheckStatus.OK
            else:
                day_statuses[day] = None
        status_by_env[env_id] = day_statuses

    return days, status_by_env
