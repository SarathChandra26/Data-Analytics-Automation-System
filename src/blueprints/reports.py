import os
from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, send_file
from src.services.db_service import Dataset, PipelineStage
from src.services.reporting_service import (
    generate_excel_report, generate_pdf_report, archive_dataset, _report_dir
)
from src.utils.logger import app_logger

reports_bp = Blueprint('reports', __name__)


@reports_bp.route('/reports/<uuid>')
def details(uuid):
    """Runs (if pending) Excel/PDF report generation and final archiving, then displays results."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset:
        flash("Dataset not found.", "error")
        return redirect(url_for('dashboard.index'))

    viz_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Visualization').first()
    if not viz_stage or viz_stage.status != 'Completed':
        flash("Dataset must complete the Visualization stage before generating reports.", "error")
        return redirect(url_for('charts.details', uuid=uuid))

    excel_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Excel_Report').first()
    pdf_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='PDF_Report').first()
    archive_stage = PipelineStage.query.filter_by(dataset_id=dataset.id, stage_name='Archive').first()

    report_dir = _report_dir(dataset.dataset_name, uuid)
    excel_path = os.path.join(report_dir, 'report.xlsx')
    pdf_path = os.path.join(report_dir, 'report.pdf')

    try:
        if (excel_stage and excel_stage.status == 'Pending') or not os.path.exists(excel_path):
            generate_excel_report(uuid)
        if (pdf_stage and pdf_stage.status == 'Pending') or not os.path.exists(pdf_path):
            generate_pdf_report(uuid)
        if archive_stage and archive_stage.status == 'Pending':
            archive_dataset(uuid)
    except Exception as e:
        flash(f"Report generation failed: {str(e)}", "error")
        return redirect(url_for('dashboard.index'))

    excel_size = f"{os.path.getsize(excel_path) / 1024:.1f} KB" if os.path.exists(excel_path) else "N/A"
    pdf_size = f"{os.path.getsize(pdf_path) / 1024:.1f} KB" if os.path.exists(pdf_path) else "N/A"

    return render_template(
        'reports.html',
        dataset=dataset,
        excel_exists=os.path.exists(excel_path),
        pdf_exists=os.path.exists(pdf_path),
        excel_size=excel_size,
        pdf_size=pdf_size,
        report_year=str(datetime.utcnow().year),
        report_dir=report_dir,
        archive_stage=archive_stage
    )


@reports_bp.route('/reports/<uuid>/download/excel')
def download_excel(uuid):
    """Streams the generated Excel report back to the user."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset:
        flash("Dataset not found.", "error")
        return redirect(url_for('dashboard.index'))

    report_dir = _report_dir(dataset.dataset_name, uuid)
    excel_path = os.path.join(report_dir, 'report.xlsx')
    if not os.path.exists(excel_path):
        flash("Excel report not available.", "error")
        return redirect(url_for('reports.details', uuid=uuid))

    return send_file(excel_path, as_attachment=True, download_name=f"{dataset.dataset_name}_report.xlsx")


@reports_bp.route('/reports/<uuid>/download/pdf')
def download_pdf(uuid):
    """Streams the generated PDF report back to the user."""
    dataset = Dataset.query.filter_by(uuid=uuid).first()
    if not dataset:
        flash("Dataset not found.", "error")
        return redirect(url_for('dashboard.index'))

    report_dir = _report_dir(dataset.dataset_name, uuid)
    pdf_path = os.path.join(report_dir, 'report.pdf')
    if not os.path.exists(pdf_path):
        flash("PDF report not available.", "error")
        return redirect(url_for('reports.details', uuid=uuid))

    return send_file(pdf_path, as_attachment=True, download_name=f"{dataset.dataset_name}_report.pdf")
