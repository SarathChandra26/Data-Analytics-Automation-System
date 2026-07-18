import os
import json
from flask import Blueprint, render_template, redirect, url_for, flash
from src.services.db_service import Dataset, PipelineStage
from src.services.analytics_service import generate_analytics
from src.utils.logger import app_logger

analytics_bp = Blueprint('analytics', __name__)


def _summary_path(dataset_uuid: str) -> str:
    from flask import current_app
    return os.path.join(current_app.config['BASE_DIR'], 'uploads', 'analytics', dataset_uuid, 'analytics_summary.json')


@analytics_bp.route('/analytics/<uuid>')
def details(uuid):
    """Runs (if pending) and displays the automated analytics engine KPIs for a dataset."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset:
        flash("Dataset not found.", "error")
        return redirect(url_for('dashboard.index'))

    database_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Database').first()
    if not database_stage or database_stage.status != 'Completed':
        flash("Dataset must be loaded into the database before running analytics.", "error")
        return redirect(url_for('database.details', uuid=uuid))

    analytics_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Analytics').first()
    summary_path = _summary_path(uuid)

    if (analytics_stage and analytics_stage.status == 'Pending') or not os.path.exists(summary_path):
        try:
            generate_analytics(uuid)
        except Exception as e:
            flash(f"Analytics generation failed: {str(e)}", "error")
            return redirect(url_for('dashboard.index'))

    try:
        with open(summary_path, 'r') as f:
            summary = json.load(f)
    except Exception as e:
        app_logger.error(f"Failed to read analytics summary: {str(e)}")
        flash("Could not load analytics summary.", "error")
        return redirect(url_for('dashboard.index'))

    return render_template(
        'analytics.html',
        dataset=dataset,
        summary=summary,
        analytics_stage=analytics_stage
    )
