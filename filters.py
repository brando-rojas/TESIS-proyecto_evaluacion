from app import app
from datetime import datetime

@app.template_filter('timeago')
def timeago_filter(date):
    """Convierte una fecha a formato "hace X tiempo"."""
    now = datetime.utcnow()
    diff = now - date
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return "hace unos segundos"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"hace {minutes} {'minuto' if minutes == 1 else 'minutos'}"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"hace {hours} {'hora' if hours == 1 else 'horas'}"
    elif seconds < 604800:
        days = int(seconds / 86400)
        return f"hace {days} {'día' if days == 1 else 'días'}"
    elif seconds < 2592000:
        weeks = int(seconds / 604800)
        return f"hace {weeks} {'semana' if weeks == 1 else 'semanas'}"
    else:
        return date.strftime("%d-%m-%Y")