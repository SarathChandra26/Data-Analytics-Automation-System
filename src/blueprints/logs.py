import os
from datetime import datetime
from flask import Blueprint, render_template, request, current_app
from src.services.db_service import ActivityLog, Dataset, db
from src.utils.logger import app_logger

logs_bp = Blueprint('logs', __name__)

LOG_FILES = {
    'application': 'application.log',
    'pipeline': 'pipeline.log',
    'error': 'error.log',
}


def _tail_file(path: str, max_lines: int = 200) -> list:
    """Reads up to `max_lines` from the end of a log file, newest last."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', errors='replace') as f:
            lines = f.readlines()
        return [l.rstrip('\n') for l in lines[-max_lines:]]
    except Exception as e:
        app_logger.error(f"Failed to read log file {path}: {str(e)}")
        return [f"Error reading log file: {str(e)}"]


@logs_bp.route('/logs')
def index():
    """Displays searchable/filterable activity logs and raw log file tails."""
    search_query = request.args.get('q', '').strip()
    level_filter = request.args.get('level', '').strip()
    dataset_filter = request.args.get('dataset_id', '').strip()
    date_from = request.args.get('date_from', '').strip()
    date_to = request.args.get('date_to', '').strip()
    file_filter = request.args.get('file', 'application')

    query = ActivityLog.query

    if search_query:
        query = query.filter(ActivityLog.message.ilike(f"%{search_query}%"))
    if level_filter:
        query = query.filter(ActivityLog.level == level_filter)
    if dataset_filter:
        try:
            query = query.filter(ActivityLog.dataset_id == int(dataset_filter))
        except ValueError:
            pass
    if date_from:
        try:
            dt_from = datetime.strptime(date_from, '%Y-%m-%d')
            query = query.filter(ActivityLog.timestamp >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.strptime(date_to, '%Y-%m-%d')
            dt_to = dt_to.replace(hour=23, minute=59, second=59)
            query = query.filter(ActivityLog.timestamp <= dt_to)
        except ValueError:
            pass

    activity_logs = query.order_by(ActivityLog.timestamp.desc()).limit(300).all()

    error_count = ActivityLog.query.filter_by(level='ERROR').count()
    total_count = ActivityLog.query.count()
    warning_count = ActivityLog.query.filter_by(level='WARNING').count()

    datasets = Dataset.query.order_by(Dataset.upload_time.desc()).all()

    if file_filter not in LOG_FILES:
        file_filter = 'application'
    log_file_path = os.path.join(current_app.config['LOGS_DIR'], LOG_FILES[file_filter])
    raw_lines = _tail_file(log_file_path, max_lines=200)
    raw_lines.reverse()  # newest first

    return render_template(
        'logs.html',
        activity_logs=activity_logs,
        datasets=datasets,
        error_count=error_count,
        warning_count=warning_count,
        total_count=total_count,
        filters={
            'q': search_query, 'level': level_filter, 'dataset_id': dataset_filter,
            'date_from': date_from, 'date_to': date_to, 'file': file_filter
        },
        raw_lines=raw_lines,
        log_files=LOG_FILES
    )
