import os
import json
from flask import Blueprint, render_template, redirect, url_for, flash, send_file
from src.services.db_service import Dataset, PipelineStage
from src.services.cleaning_service import clean_dataset
from src.utils.logger import app_logger

cleaning_bp = Blueprint('cleaning', __name__)


@cleaning_bp.route('/cleaning/<uuid>')
def details(uuid):
    """Runs (if pending) and displays the automated data cleaning summary for a dataset."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset:
        flash("Dataset not found.", "error")
        return redirect(url_for('dashboard.index'))

    validation_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Validation').first()
    if not validation_stage or validation_stage.status != 'Completed':
        flash("Dataset must pass schema validation before cleaning.", "error")
        return redirect(url_for('validation.details', uuid=uuid))

    cleaning_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Cleaning').first()

    cleaned_dir = os.path.dirname(dataset.cleaned_filepath) if dataset.cleaned_filepath else None
    summary_path = os.path.join(cleaned_dir, 'cleaning_summary.json') if cleaned_dir else None

    if (cleaning_stage and cleaning_stage.status == 'Pending') or not summary_path or not os.path.exists(summary_path):
        try:
            clean_dataset(uuid)
            cleaned_dir = os.path.dirname(dataset.cleaned_filepath)
            summary_path = os.path.join(cleaned_dir, 'cleaning_summary.json')
        except Exception as e:
            flash(f"Data cleaning failed: {str(e)}", "error")
            return redirect(url_for('dashboard.index'))

    try:
        with open(summary_path, 'r') as f:
            summary = json.load(f)
    except Exception as e:
        app_logger.error(f"Failed to read cleaning summary: {str(e)}")
        flash("Could not load cleaning summary.", "error")
        return redirect(url_for('dashboard.index'))

    return render_template(
        'cleaning.html',
        dataset=dataset,
        summary=summary,
        cleaning_stage=cleaning_stage
    )


@cleaning_bp.route('/cleaning/<uuid>/download')
def download(uuid):
    """Streams the cleaned CSV file back to the user."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset or not dataset.cleaned_filepath or not os.path.exists(dataset.cleaned_filepath):
        flash("Cleaned file not available.", "error")
        return redirect(url_for('dashboard.index'))

    return send_file(
        dataset.cleaned_filepath,
        as_attachment=True,
        download_name=f"cleaned_{dataset.original_filename}"
    )
