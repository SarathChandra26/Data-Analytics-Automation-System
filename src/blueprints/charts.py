import os
import json
from flask import Blueprint, render_template, redirect, url_for, flash, send_from_directory, current_app, abort, request
from src.services.db_service import Dataset, PipelineStage
from src.services.visualization_service import generate_visualizations, _chart_dir
from src.utils.logger import app_logger

charts_bp = Blueprint('charts', __name__)


def _manifest_path(chart_dir: str) -> str:
    return os.path.join(chart_dir, 'manifest.json')


@charts_bp.route('/charts/<uuid>')
def details(uuid):
    """Runs (if pending) and displays the automated visualization suite for a dataset."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset:
        flash("Dataset not found.", "error")
        return redirect(url_for('dashboard.index'))

    analytics_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Analytics').first()
    if not analytics_stage or analytics_stage.status != 'Completed':
        flash("Dataset must complete the Analytics stage before generating charts.", "error")
        return redirect(url_for('analytics.details', uuid=uuid))

    viz_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Visualization').first()
    chart_dir = _chart_dir(dataset.dataset_name, uuid)
    manifest_path = _manifest_path(chart_dir)

    if (viz_stage and viz_stage.status == 'Pending') or not os.path.exists(manifest_path):
        try:
            generate_visualizations(uuid)
        except Exception as e:
            flash(f"Chart generation failed: {str(e)}", "error")
            return redirect(url_for('dashboard.index'))

    try:
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
    except Exception as e:
        app_logger.error(f"Failed to read chart manifest: {str(e)}")
        flash("Could not load chart manifest.", "error")
        return redirect(url_for('dashboard.index'))

    return render_template(
        'charts.html',
        dataset=dataset,
        manifest=manifest,
        viz_stage=viz_stage
    )


@charts_bp.route('/charts/<uuid>/asset/<path:filename>')
def asset(uuid, filename):
    """Serves a generated chart asset (PNG or interactive HTML) from the charts directory."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset:
        abort(404)

    chart_dir = _chart_dir(dataset.dataset_name, uuid)
    if not os.path.exists(os.path.join(chart_dir, filename)):
        abort(404)

    as_attachment = request.args.get('download') is not None
    return send_from_directory(chart_dir, filename, as_attachment=as_attachment)
