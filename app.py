import os
from flask import Flask, redirect, url_for
from config.config import Config
from src.services.db_service import db, init_db
from src.blueprints.dashboard import dashboard_bp
from src.blueprints.upload import upload_bp
from src.blueprints.validation import validation_bp
from src.blueprints.cleaning import cleaning_bp
from src.blueprints.transformation import transformation_bp
from src.blueprints.database import database_bp
from src.blueprints.analytics import analytics_bp
from src.blueprints.charts import charts_bp
from src.blueprints.reports import reports_bp
from src.blueprints.logs import logs_bp
from src.utils.logger import app_logger

def create_app(config_class=Config) -> Flask:
    """App factory that initializes config, registers blueprints, databases, and setups loggers."""
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    
    # Ensure all required folders exist
    folders_to_ensure = [
        app.config['UPLOAD_RAW_DIR'],
        app.config['UPLOAD_CLEANED_DIR'],
        app.config['UPLOAD_TRANSFORMED_DIR'],
        app.config['UPLOAD_ARCHIVE_DIR'],
        app.config['REPORTS_DIR'],
        app.config['CHARTS_DIR'],
        app.config['LOGS_DIR'],
        os.path.join(app.config['BASE_DIR'], 'uploads', 'analytics'),
        os.path.join(app.config['BASE_DIR'], 'instance')
    ]
    for folder in folders_to_ensure:
        os.makedirs(folder, exist_ok=True)
        
    # Initialize DB
    init_db(app)
    
    # Register blueprints
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(upload_bp)
    app.register_blueprint(validation_bp)
    app.register_blueprint(cleaning_bp)
    app.register_blueprint(transformation_bp)
    app.register_blueprint(database_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(charts_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(logs_bp)

    @app.context_processor
    def inject_sidebar_dataset():
        """Makes the most recently uploaded dataset available to every template,
        so the sidebar's pipeline-stage links can route to its detail pages."""
        from src.services.db_service import Dataset
        latest_dataset = Dataset.query.order_by(Dataset.upload_time.desc()).first()
        return {'sidebar_dataset': latest_dataset}

    # Catch-all route redirecting to dashboard
    @app.route('/<path:dummy>')
    def fallback(dummy):
        return redirect(url_for('dashboard.index'))
        
    app_logger.info("DA Automation System (DAAS) Flask Application instance created successfully.")
    
    return app

if __name__ == '__main__':
    app = create_app()
    # Run the application
    app.run(host='0.0.0.0', port=5000, debug=True)
