document.addEventListener('DOMContentLoaded', function() {
    const dropzone = document.getElementById('dropzone');
    const fileInput = document.getElementById('csvFile');
    const fileInfoLabel = document.getElementById('fileInfoLabel');
    const form = document.getElementById('datasetUploadForm');
    const submitBtn = document.getElementById('submitBtn');
    const progressContainer = document.getElementById('progressContainer');
    const progressBar = document.getElementById('progressBar');
    const progressPercent = document.getElementById('progressPercent');
    
    // Containers to toggle visibility
    const summaryContainer = document.getElementById('summaryContainer');
    const previewContainer = document.getElementById('previewContainer');
    const uploadFormContainer = document.getElementById('uploadFormContainer');
    
    // Elements to fill dynamically
    const summaryDatasetName = document.getElementById('summaryDatasetName');
    const summaryFilename = document.getElementById('summaryFilename');
    const summaryFileSize = document.getElementById('summaryFileSize');
    const summaryDimensions = document.getElementById('summaryDimensions');
    const summaryRows = document.getElementById('summaryRows');
    const summaryColumns = document.getElementById('summaryColumns');
    const summaryDuplicates = document.getElementById('summaryDuplicates');
    const summaryMissingCount = document.getElementById('summaryMissingCount');
    const summaryMissingDetails = document.getElementById('summaryMissingDetails');
    const summaryNumericCount = document.getElementById('summaryNumericCount');
    const summaryCategoricalCount = document.getElementById('summaryCategoricalCount');
    
    const previewTableHeader = document.getElementById('previewTableHeader');
    const previewTableBody = document.getElementById('previewTableBody');
    const runPipelineBtn = document.getElementById('runPipelineBtn');
    
    let uploadedDatasetUuid = null;

    // Dropzone Interactivity
    dropzone.addEventListener('click', () => fileInput.click());

    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('dragover');
    });

    ['dragleave', 'dragend'].forEach(type => {
        dropzone.addEventListener(type, () => {
            dropzone.classList.remove('dragover');
        });
    });

    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('dragover');
        
        if (e.dataTransfer.files.length) {
            fileInput.files = e.dataTransfer.files;
            updateFileInfo();
        }
    });

    fileInput.addEventListener('change', updateFileInfo);

    function updateFileInfo() {
        if (fileInput.files.length > 0) {
            const file = fileInput.files[0];
            fileInfoLabel.textContent = `${file.name} (${formatBytes(file.size)})`;
        } else {
            fileInfoLabel.textContent = "No file selected";
        }
    }

    function formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    // Ajax Form Submission
    form.addEventListener('submit', function(e) {
        e.preventDefault();
        
        if (fileInput.files.length === 0) {
            window.showNotification("Upload Error", "Please select a CSV file first.", false);
            return;
        }

        const formData = new FormData(form);
        
        // Setup UI for uploading status
        submitBtn.disabled = true;
        submitBtn.classList.add('btn-custom-loading');
        progressContainer.classList.remove('d-none');
        progressBar.style.width = '0%';
        progressPercent.textContent = '0%';

        const xhr = new XMLHttpRequest();
        xhr.open('POST', '/upload/ajax', true);

        // Upload progress listener
        xhr.upload.addEventListener('progress', function(e) {
            if (e.lengthComputable) {
                const percent = Math.round((e.loaded / e.total) * 100);
                progressBar.style.width = percent + '%';
                progressPercent.textContent = percent + '%';
            }
        });

        xhr.onload = function() {
            submitBtn.disabled = false;
            submitBtn.classList.remove('btn-custom-loading');
            
            if (xhr.status === 200) {
                const response = JSON.parse(xhr.responseText);
                if (response.success) {
                    uploadedDatasetUuid = response.uuid;
                    window.showNotification("Upload Success", `Dataset "${response.dataset_name}" uploaded and scanned successfully!`, true);
                    
                    // Display Summary details
                    summaryDatasetName.textContent = response.dataset_name;
                    summaryFilename.textContent = response.original_filename;
                    summaryFileSize.textContent = response.file_size_formatted;
                    
                    const rowsCount = response.summary.row_count;
                    const colsCount = response.summary.column_count;
                    summaryDimensions.textContent = `${rowsCount.toLocaleString()} Rows x ${colsCount} Cols`;
                    
                    summaryRows.textContent = rowsCount.toLocaleString();
                    summaryColumns.textContent = colsCount.toString();
                    summaryDuplicates.textContent = response.summary.duplicate_rows_count.toLocaleString();
                    
                    if (response.summary.duplicate_rows_count > 0) {
                        summaryDuplicates.className = "m-0 text-danger fw-bold";
                    } else {
                        summaryDuplicates.className = "m-0 text-success fw-bold";
                    }
                    
                    const missingValCount = response.summary.missing_values_count;
                    summaryMissingCount.textContent = missingValCount.toString();
                    if (missingValCount > 0) {
                        summaryMissingCount.className = "badge-custom badge-custom-danger";
                        
                        let missingHtml = '<ul class="m-0 p-0 ps-3">';
                        for (const [col, count] of Object.entries(response.summary.missing_values_by_column)) {
                            missingHtml += `<li><strong>${escapeHtml(col)}</strong>: ${count} nulls</li>`;
                        }
                        missingHtml += '</ul>';
                        summaryMissingDetails.innerHTML = missingHtml;
                    } else {
                        summaryMissingCount.className = "badge-custom badge-custom-success";
                        summaryMissingDetails.textContent = "Clean. No missing values detected.";
                    }
                    
                    summaryNumericCount.textContent = response.summary.numeric_columns_count;
                    summaryCategoricalCount.textContent = response.summary.categorical_columns_count;
                    
                    // Build Preview Table headers
                    let headHtml = "<tr>";
                    response.preview_headers.forEach(header => {
                        headHtml += `<th>${escapeHtml(header)}</th>`;
                    });
                    headHtml += "</tr>";
                    previewTableHeader.innerHTML = headHtml;
                    
                    // Build Preview Table rows
                    let bodyHtml = "";
                    response.preview_rows.forEach(row => {
                        bodyHtml += "<tr>";
                        response.preview_headers.forEach(header => {
                            bodyHtml += `<td>${escapeHtml(row[header])}</td>`;
                        });
                        bodyHtml += "</tr>";
                    });
                    previewTableBody.innerHTML = bodyHtml;
                    
                    // Show containers
                    summaryContainer.classList.remove('d-none');
                    previewContainer.classList.remove('d-none');
                    
                    // Make upload layout equal grid side by side
                    uploadFormContainer.className = "col-lg-6";
                    
                    // Enable pipeline button
                    runPipelineBtn.disabled = false;
                    
                } else {
                    window.showNotification("Upload Error", response.error || "Failed to process dataset.", false);
                    progressContainer.classList.add('d-none');
                }
            } else {
                let errMsg = "An unexpected server error occurred.";
                try {
                    const response = JSON.parse(xhr.responseText);
                    errMsg = response.error || errMsg;
                } catch(e) {}
                window.showNotification("Upload Error", errMsg, false);
                progressContainer.classList.add('d-none');
            }
        };

        xhr.onerror = function() {
            submitBtn.disabled = false;
            submitBtn.classList.remove('btn-custom-loading');
            progressContainer.classList.add('d-none');
            window.showNotification("Connection Error", "Failed to communicate with the server.", false);
        };

        xhr.send(formData);
    });

    // Run pipeline click handler - navigates to Validation, which runs the
    // real validation service synchronously and then chains through Cleaning,
    // Transformation, Database, Analytics, Charts, and Reports as each page is visited.
    runPipelineBtn.addEventListener('click', function() {
        if (!uploadedDatasetUuid) return;

        runPipelineBtn.disabled = true;
        runPipelineBtn.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Opening Validation Stage...';

        const statusBadge = document.getElementById('pipelineStatusBadge');
        statusBadge.className = "status-indicator running";
        statusBadge.innerHTML = '<i class="bi bi-arrow-repeat spin"></i> Running...';

        window.location.href = "/validation/" + uploadedDatasetUuid;
    });

    function escapeHtml(text) {
        if (text === null || text === undefined) return '';
        const map = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#039;'
        };
        return text.toString().replace(/[&<>"']/g, function(m) { return map[m]; });
    }
});
