"""Read-only dashboard assembly; all account data is scoped to its owner."""
from backend import views
from backend.config import config
from src.prediction import load_approved


def prediction_summary(db, user_id):
    try:
        _, metadata = load_approved(config.model_path)
        model = {'version': metadata['version'], 'validated': True}
    except (ValueError, OSError, KeyError) as error:
        model = {'version': None, 'validated': False, 'reason': str(error)}
    return {'prediction': views.latest_prediction(db, user_id), 'model': model}


def dashboard_summary(db, user_id):
    return {
        'market': views.market(db),
        'agent': views.status(db, user_id),
        'model': prediction_summary(db, user_id),
        'portfolio': views.portfolio(db, user_id),
        'performance': views.performance(db, user_id),
        'settings': views.settings(db, user_id),
        'trades': views.trades(db, user_id),
        'decisions': views.decisions(db, user_id),
        'research': views.research_forecast(db),
    }
