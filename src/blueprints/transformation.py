import os
import json
from flask import Blueprint, render_template, redirect, url_for, flash, send_file
from src.services.db_service import Dataset, PipelineStage
from src.services.transformation_service import transform_dataset
from src.utils.logger import app_logger

transformation_bp = Blueprint('transformation', __name__)


@transformation_bp.route('/transformation/<uuid>')
def details(uuid):
    """Runs (if pending) and displays the business transformation summary for a dataset."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset:
        flash("Dataset not found.", "error")
        return redirect(url_for('dashboard.index'))

    cleaning_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Cleaning').first()
    if not cleaning_stage or cleaning_stage.status != 'Completed':
        flash("Dataset must be cleaned before transformation.", "error")
        return redirect(url_for('cleaning.details', uuid=uuid))

    transformation_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Transformation').first()

    transformed_dir = os.path.dirname(dataset.transformed_filepath) if dataset.transformed_filepath else None
    summary_path = os.path.join(transformed_dir, 'transformation_summary.json') if transformed_dir else None

    if (transformation_stage and transformation_stage.status == 'Pending') or not summary_path or not os.path.exists(summary_path):
        try:
            transform_dataset(uuid)
            transformed_dir = os.path.dirname(dataset.transformed_filepath)
            summary_path = os.path.join(transformed_dir, 'transformation_summary.json')
        except Exception as e:
            flash(f"Data transformation failed: {str(e)}", "error")
            return redirect(url_for('dashboard.index'))

    try:
        with open(summary_path, 'r') as f:
            summary = json.load(f)
    except Exception as e:
        app_logger.error(f"Failed to read transformation summary: {str(e)}")
        flash("Could not load transformation summary.", "error")
        return redirect(url_for('dashboard.index'))

    return render_template(
        'transformation.html',
        dataset=dataset,
        summary=summary,
        transformation_stage=transformation_stage
    )


@transformation_bp.route('/transformation/<uuid>/download')
def download(uuid):
    """Streams the transformed CSV file back to the user."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset or not dataset.transformed_filepath or not os.path.exists(dataset.transformed_filepath):
        flash("Transformed file not available.", "error")
        return redirect(url_for('dashboard.index'))

    return send_file(
        dataset.transformed_filepath,
        as_attachment=True,
        download_name=f"transformed_{dataset.original_filename}"
    )
