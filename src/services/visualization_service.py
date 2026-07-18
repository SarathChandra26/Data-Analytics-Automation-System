import os
import re
import json
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import plotly.io as pio
from datetime import datetime
from flask import current_app
from src.services.analytics_service import _first_match, REVENUE_COLUMNS, SALES_COLUMNS, CATEGORY_COLUMNS, DATE_COLUMNS
from src.services.db_service import update_pipeline_stage, log_activity, Dataset, db
from src.utils.logger import pipeline_logger, error_logger

# Dark theme palette matching the app's design tokens, reused for every generated chart.
CHART_BG = '#111827'
CHART_GRID = '#1f2937'
CHART_TEXT = '#9ca3af'
CHART_ACCENT = '#3b82f6'
CHART_PALETTE = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#ec4899', '#84cc16']

plt.rcParams.update({
    'figure.facecolor': CHART_BG,
    'axes.facecolor': CHART_BG,
    'axes.edgecolor': CHART_GRID,
    'axes.labelcolor': CHART_TEXT,
    'text.color': CHART_TEXT,
    'xtick.color': CHART_TEXT,
    'ytick.color': CHART_TEXT,
    'grid.color': CHART_GRID,
    'font.size': 10,
})


def _sanitize_name(name: str) -> str:
    """Converts a dataset name into a filesystem-safe folder name."""
    name = re.sub(r'[^a-zA-Z0-9_-]+', '_', name.strip())
    return name.strip('_') or 'dataset'


def _chart_dir(dataset_name: str, dataset_uuid: str) -> str:
    base = current_app.config['CHARTS_DIR']
    folder = f"{_sanitize_name(dataset_name)}_{dataset_uuid[:8]}"
    chart_dir = os.path.join(base, folder)
    os.makedirs(chart_dir, exist_ok=True)
    return chart_dir


def _save_matplotlib(fig, path_png):
    fig.savefig(path_png, dpi=130, bbox_inches='tight', facecolor=CHART_BG)
    plt.close(fig)


def _plotly_layout(title: str):
    return dict(
        title=title,
        paper_bgcolor=CHART_BG,
        plot_bgcolor=CHART_BG,
        font=dict(color=CHART_TEXT),
        xaxis=dict(gridcolor=CHART_GRID, zerolinecolor=CHART_GRID),
        yaxis=dict(gridcolor=CHART_GRID, zerolinecolor=CHART_GRID),
        margin=dict(l=40, r=20, t=50, b=40),
    )


def generate_visualizations(dataset_uuid: str) -> dict:
    """Auto-generates a suite of charts (bar, line, pie, histogram, box plot) for a dataset.

    For every chart type, both a static PNG (matplotlib) and an interactive HTML
    (Plotly) version are generated and saved under charts/<dataset_name>_<uuid>/.
    """
    update_pipeline_stage(dataset_uuid, 'Visualization', 'Running')

    try:
        dataset = Dataset.query.filter_by(uuid=dataset_uuid).first()
        if not dataset:
            raise ValueError(f"Dataset with UUID {dataset_uuid} not found.")

        source_path = dataset.transformed_filepath or dataset.cleaned_filepath or dataset.raw_filepath
        if not source_path or not os.path.exists(source_path):
            raise FileNotFoundError("No processed dataset available. Run earlier pipeline stages first.")

        df = pd.read_csv(source_path)
        chart_dir = _chart_dir(dataset.dataset_name, dataset_uuid)

        revenue_col = _first_match(list(df.columns), REVENUE_COLUMNS)
        sales_col = _first_match(list(df.columns), SALES_COLUMNS)
        category_col = _first_match(list(df.columns), CATEGORY_COLUMNS)
        date_col = _first_match(list(df.columns), DATE_COLUMNS)
        numeric_cols = list(df.select_dtypes(include=[np.number]).columns)

        charts = []

        # --- 1. Bar Chart: category vs revenue/sales ---
        if category_col and (revenue_col or sales_col):
            metric_col = revenue_col or sales_col
            metric_label = 'Revenue' if revenue_col else 'Units Sold'
            grouped = df.groupby(category_col)[metric_col].sum().sort_values(ascending=False).head(10)

            fig, ax = plt.subplots(figsize=(7, 4.5))
            ax.bar(grouped.index.astype(str), grouped.values, color=CHART_ACCENT)
            ax.set_title(f"{metric_label} by {category_col.replace('_', ' ').title()}", color=CHART_TEXT)
            ax.set_ylabel(metric_label)
            plt.xticks(rotation=35, ha='right')
            png_path = os.path.join(chart_dir, 'bar_chart.png')
            _save_matplotlib(fig, png_path)

            fig_p = go.Figure(data=[go.Bar(x=grouped.index.astype(str), y=grouped.values, marker_color=CHART_PALETTE)])
            fig_p.update_layout(**_plotly_layout(f"{metric_label} by {category_col.replace('_', ' ').title()}"))
            html_path = os.path.join(chart_dir, 'bar_chart.html')
            pio.write_html(fig_p, html_path, include_plotlyjs='cdn', full_html=True)

            charts.append({'type': 'bar', 'title': f"{metric_label} by {category_col.replace('_', ' ').title()}",
                            'png': 'bar_chart.png', 'html': 'bar_chart.html'})

        # --- 2. Line Chart: trend over time ---
        if date_col and (revenue_col or sales_col):
            metric_col = revenue_col or sales_col
            metric_label = 'Revenue' if revenue_col else 'Units Sold'
            parsed = pd.to_datetime(df[date_col], errors='coerce')
            trend = pd.DataFrame({'period': parsed.dt.to_period('M'), 'value': pd.to_numeric(df[metric_col], errors='coerce').fillna(0)})
            trend = trend.dropna(subset=['period']).groupby('period')['value'].sum().sort_index()
            x_labels = [str(p) for p in trend.index]

            fig, ax = plt.subplots(figsize=(7, 4.5))
            ax.plot(x_labels, trend.values, color=CHART_PALETTE[1], marker='o', linewidth=2)
            ax.set_title(f"Monthly {metric_label} Trend", color=CHART_TEXT)
            ax.set_ylabel(metric_label)
            plt.xticks(rotation=35, ha='right')
            png_path = os.path.join(chart_dir, 'line_chart.png')
            _save_matplotlib(fig, png_path)

            fig_p = go.Figure(data=[go.Scatter(x=x_labels, y=trend.values, mode='lines+markers',
                                                line=dict(color=CHART_PALETTE[1], width=3))])
            fig_p.update_layout(**_plotly_layout(f"Monthly {metric_label} Trend"))
            html_path = os.path.join(chart_dir, 'line_chart.html')
            pio.write_html(fig_p, html_path, include_plotlyjs='cdn', full_html=True)

            charts.append({'type': 'line', 'title': f"Monthly {metric_label} Trend",
                            'png': 'line_chart.png', 'html': 'line_chart.html'})

        # --- 3. Pie Chart: category composition ---
        if category_col:
            metric_col = revenue_col or sales_col
            if metric_col:
                grouped = df.groupby(category_col)[metric_col].sum().sort_values(ascending=False).head(8)
            else:
                grouped = df[category_col].value_counts().head(8)

            fig, ax = plt.subplots(figsize=(6, 6))
            ax.pie(grouped.values, labels=grouped.index.astype(str), autopct='%1.1f%%',
                   colors=CHART_PALETTE, textprops={'color': CHART_TEXT})
            ax.set_title(f"{category_col.replace('_', ' ').title()} Composition", color=CHART_TEXT)
            png_path = os.path.join(chart_dir, 'pie_chart.png')
            _save_matplotlib(fig, png_path)

            fig_p = go.Figure(data=[go.Pie(labels=grouped.index.astype(str), values=grouped.values,
                                            marker=dict(colors=CHART_PALETTE))])
            fig_p.update_layout(**_plotly_layout(f"{category_col.replace('_', ' ').title()} Composition"))
            html_path = os.path.join(chart_dir, 'pie_chart.html')
            pio.write_html(fig_p, html_path, include_plotlyjs='cdn', full_html=True)

            charts.append({'type': 'pie', 'title': f"{category_col.replace('_', ' ').title()} Composition",
                            'png': 'pie_chart.png', 'html': 'pie_chart.html'})

        # --- 4. Histogram: distribution of the primary numeric metric ---
        hist_col = revenue_col or sales_col or (numeric_cols[0] if numeric_cols else None)
        if hist_col:
            values = pd.to_numeric(df[hist_col], errors='coerce').dropna()
            fig, ax = plt.subplots(figsize=(7, 4.5))
            ax.hist(values, bins=20, color=CHART_PALETTE[2], edgecolor=CHART_BG)
            ax.set_title(f"Distribution of {hist_col.replace('_', ' ').title()}", color=CHART_TEXT)
            ax.set_xlabel(hist_col.replace('_', ' ').title())
            ax.set_ylabel('Frequency')
            png_path = os.path.join(chart_dir, 'histogram.png')
            _save_matplotlib(fig, png_path)

            fig_p = go.Figure(data=[go.Histogram(x=values, nbinsx=20, marker_color=CHART_PALETTE[2])])
            fig_p.update_layout(**_plotly_layout(f"Distribution of {hist_col.replace('_', ' ').title()}"))
            html_path = os.path.join(chart_dir, 'histogram.html')
            pio.write_html(fig_p, html_path, include_plotlyjs='cdn', full_html=True)

            charts.append({'type': 'histogram', 'title': f"Distribution of {hist_col.replace('_', ' ').title()}",
                            'png': 'histogram.png', 'html': 'histogram.html'})

        # --- 5. Box Plot (optional): spread of numeric columns by category, or overall ---
        if numeric_cols:
            box_col = revenue_col or sales_col or numeric_cols[0]
            fig, ax = plt.subplots(figsize=(7, 4.5))
            if category_col:
                top_cats = df[category_col].value_counts().head(6).index
                data_groups = [pd.to_numeric(df[df[category_col] == c][box_col], errors='coerce').dropna() for c in top_cats]
                bp = ax.boxplot(data_groups, labels=[str(c) for c in top_cats], patch_artist=True)
                for patch, color in zip(bp['boxes'], CHART_PALETTE):
                    patch.set_facecolor(color)
                    patch.set_alpha(0.6)
                plt.xticks(rotation=35, ha='right')
                fig_p = go.Figure()
                for c, color in zip(top_cats, CHART_PALETTE):
                    fig_p.add_trace(go.Box(y=pd.to_numeric(df[df[category_col] == c][box_col], errors='coerce').dropna(),
                                            name=str(c), marker_color=color))
            else:
                values = pd.to_numeric(df[box_col], errors='coerce').dropna()
                bp = ax.boxplot([values], labels=[box_col], patch_artist=True)
                for patch in bp['boxes']:
                    patch.set_facecolor(CHART_ACCENT)
                    patch.set_alpha(0.6)
                fig_p = go.Figure(data=[go.Box(y=values, name=box_col, marker_color=CHART_ACCENT)])

            ax.set_title(f"Box Plot: {box_col.replace('_', ' ').title()}", color=CHART_TEXT)
            png_path = os.path.join(chart_dir, 'box_plot.png')
            _save_matplotlib(fig, png_path)

            fig_p.update_layout(**_plotly_layout(f"Box Plot: {box_col.replace('_', ' ').title()}"))
            html_path = os.path.join(chart_dir, 'box_plot.html')
            pio.write_html(fig_p, html_path, include_plotlyjs='cdn', full_html=True)

            charts.append({'type': 'box_plot', 'title': f"Box Plot: {box_col.replace('_', ' ').title()}",
                            'png': 'box_plot.png', 'html': 'box_plot.html'})

        chart_folder_rel = os.path.relpath(chart_dir, current_app.config['CHARTS_DIR'])
        results = {
            'charts': charts,
            'chart_dir': chart_dir,
            'chart_folder': chart_folder_rel,
            'generated_at': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S'),
        }

        manifest_path = os.path.join(chart_dir, 'manifest.json')
        with open(manifest_path, 'w') as f:
            json.dump(results, f, indent=4, default=str)

        update_pipeline_stage(dataset_uuid, 'Visualization', 'Completed')

        log_msg = f"Visualization engine generated {len(charts)} chart(s) in '{chart_folder_rel}'."
        pipeline_logger.info(log_msg)
        log_activity(log_msg, level='INFO', dataset_id=dataset.id, stage='Visualization')

        return results
    except Exception as e:
        error_msg = f"Fatal visualization engine failure: {str(e)}"
        error_logger.error(error_msg)
        update_pipeline_stage(dataset_uuid, 'Visualization', 'Failed', error_message=error_msg)
        raise e
