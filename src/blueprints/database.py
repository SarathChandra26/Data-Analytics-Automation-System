from flask import Blueprint, render_template, redirect, url_for, flash
from src.services.db_service import Dataset, PipelineStage, AnalyticsTableMeta, AnalyticsRecord
from src.services.database_service import load_dataset_to_database

database_bp = Blueprint('database', __name__)


@database_bp.route('/database/<uuid>')
def details(uuid):
    """Runs (if pending) and displays the SQLite data loader summary for a dataset."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset:
        flash("Dataset not found.", "error")
        return redirect(url_for('dashboard.index'))

    transformation_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Transformation').first()
    cleaning_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Cleaning').first()
    if (not transformation_stage or transformation_stage.status != 'Completed') and \
       (not cleaning_stage or cleaning_stage.status != 'Completed'):
        flash("Dataset must be cleaned (and ideally transformed) before database loading.", "error")
        return redirect(url_for('transformation.details', uuid=uuid))

    database_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Database').first()
    meta = AnalyticsTableMeta.query.filter_by(dataset_id=dataset.id).first()

    if (database_stage and database_stage.status == 'Pending') or not meta:
        try:
            load_dataset_to_database(uuid)
            meta = AnalyticsTableMeta.query.filter_by(dataset_id=dataset.id).first()
        except Exception as e:
            flash(f"Database load failed: {str(e)}", "error")
            return redirect(url_for('dashboard.index'))

    # All datasets currently loaded into the standardized analytics table (for the "Tables" view)
    all_imports = (
        AnalyticsTableMeta.query
        .join(Dataset, AnalyticsTableMeta.dataset_id == Dataset.id)
        .add_columns(Dataset.dataset_name, Dataset.uuid)
        .order_by(AnalyticsTableMeta.imported_at.desc())
        .all()
    )

    sample_records = (
        AnalyticsRecord.query
        .filter_by(dataset_id=dataset.id)
        .limit(10)
        .all()
    )

    return render_template(
        'database.html',
        dataset=dataset,
        meta=meta,
        all_imports=all_imports,
        sample_records=sample_records,
        database_stage=database_stage
    )
