/**
 * Convertitore EML → PDF — Frontend
 * Gestisce upload via drag & drop, conversione e download.
 */

(function () {
  "use strict";

  // ── DOM refs ──────────────────────────────────────────────────────────

  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const fileList = document.getElementById("fileList");
  const fileListEmpty = document.getElementById("fileListEmpty");
  const convertBtn = document.getElementById("convertBtn");
  const downloadBtn = document.getElementById("downloadBtn");
  const resetBtn = document.getElementById("resetBtn");
  const statusSection = document.getElementById("statusSection");

  // ── State ─────────────────────────────────────────────────────────────

  let selectedFiles = [];  // File objects
  let currentSessionId = null;
  let isProcessing = false;

  // ── Helpers ───────────────────────────────────────────────────────────

  function formatSize(bytes) {
    if (bytes === 0) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let i = 0;
    let size = bytes;
    while (size >= 1024 && i < units.length - 1) {
      size /= 1024;
      i++;
    }
    return size.toFixed(i === 0 ? 0 : 1) + " " + units[i];
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // ── File handling ────────────────────────────────────────────────────

  function addFiles(files) {
    const validFiles = [];
    for (const f of files) {
      if (f.name.toLowerCase().endsWith(".eml")) {
        // Evita duplicati
        if (!selectedFiles.some((sf) => sf.name === f.name && sf.size === f.size)) {
          validFiles.push(f);
        }
      }
    }

    if (validFiles.length === 0) return;

    selectedFiles = [...selectedFiles, ...validFiles];
    renderFileList();
    updateUI();
  }

  function removeFile(index) {
    selectedFiles.splice(index, 1);
    renderFileList();
    updateUI();
  }

  function renderFileList() {
    // Rimuovi elementi file esistenti
    const existingItems = fileList.querySelectorAll(".file-item");
    existingItems.forEach((el) => el.remove());

    if (selectedFiles.length === 0) {
      fileListEmpty.style.display = "block";
      return;
    }

    fileListEmpty.style.display = "none";

    selectedFiles.forEach((file, index) => {
      const item = document.createElement("div");
      item.className = "file-item";
      item.style.animationDelay = `${index * 40}ms`;

      item.innerHTML = `
        <div class="file-item-icon" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="2" y="4" width="20" height="16" rx="2"/>
            <path d="M2 7l10 7 10-7"/>
          </svg>
        </div>
        <div class="file-item-info">
          <div class="file-item-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
          <div class="file-item-meta">${formatSize(file.size)}</div>
        </div>
        <button type="button" class="file-item-remove" data-index="${index}"
                aria-label="Rimuovi ${escapeHtml(file.name)}">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
               stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"/>
            <line x1="6" y1="6" x2="18" y2="18"/>
          </svg>
        </button>
      `;

      fileList.appendChild(item);
    });

    // Event listeners per rimozione
    fileList.querySelectorAll(".file-item-remove").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const index = parseInt(btn.dataset.index, 10);
        if (!isNaN(index)) removeFile(index);
      });
    });
  }

  function updateUI() {
    const hasFiles = selectedFiles.length > 0;
    convertBtn.disabled = hasFiles === false || isProcessing;
    resetBtn.style.display = hasFiles || currentSessionId ? "" : "none";
    downloadBtn.style.display = currentSessionId && !isProcessing ? "" : "none";

    if (hasFiles) {
      dropZone.classList.add("has-files");
      convertBtn.querySelector(".btn-label").textContent =
        `Converti ${selectedFiles.length} file in PDF`;
    } else {
      dropZone.classList.remove("has-files");
      convertBtn.querySelector(".btn-label").textContent = "Converti in PDF";
    }

    if (isProcessing) {
      convertBtn.classList.add("btn-loading");
      convertBtn.querySelector(".btn-label").textContent = "Elaborazione in corso…";
    } else {
      convertBtn.classList.remove("btn-loading");
    }
  }

  function resetState() {
    selectedFiles = [];
    currentSessionId = null;
    isProcessing = false;
    fileInput.value = "";
    renderFileList();
    updateUI();
    clearStatus();
  }

  function clearStatus() {
    statusSection.style.display = "none";
    statusSection.innerHTML = "";
  }

  // ── Upload via API ────────────────────────────────────────────────────

  async function uploadFiles() {
    if (selectedFiles.length === 0 || isProcessing) return;

    isProcessing = true;
    updateUI();
    clearStatus();

    // Mostra stato processing
    showProcessingStatus(`Elaborazione di ${selectedFiles.length} file in corso…`);

    const formData = new FormData();
    selectedFiles.forEach((f) => formData.append("files", f));

    let response;
    try {
      response = await fetch("api/upload", {
        method: "POST",
        body: formData,
      });
    } catch (err) {
      showErrorStatus("Errore di rete: impossibile comunicare con il server.");
      isProcessing = false;
      updateUI();
      return;
    }

    let data;
    try {
      data = await response.json();
    } catch {
      showErrorStatus("Risposta del server non valida.");
      isProcessing = false;
      updateUI();
      return;
    }

    if (!response.ok) {
      const errMsg = data.error || "Errore durante l'elaborazione.";
      const details = data.details ? data.details.join("; ") : "";
      showErrorStatus(errMsg + (details ? " " + details : ""));
      isProcessing = false;
      updateUI();
      return;
    }

    currentSessionId = data.session_id;

    // Mostra risultato
    showSuccessStatus(data);
    isProcessing = false;
    updateUI();
  }

  function downloadZip() {
    if (!currentSessionId) return;

    // Crea un link nascosto e cliccalo
    const link = document.createElement("a");
    link.href = `api/download/${currentSessionId}`;
    link.download = "eml_to_pdf.zip";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    // Dopo il download, resetta
    setTimeout(() => {
      resetState();
    }, 1500);
  }

  // ── Status UI ─────────────────────────────────────────────────────────

  function showProcessingStatus(message) {
    statusSection.style.display = "flex";
    statusSection.innerHTML = `
      <div class="status-card processing">
        <div class="status-card-header">
          <svg class="status-card-icon processing" width="20" height="20" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
          <span class="status-card-title">${escapeHtml(message)}</span>
        </div>
        <div class="progress-bar">
          <div class="progress-bar-fill" style="width: 60%"></div>
        </div>
      </div>
    `;
  }

  function showSuccessStatus(data) {
    const processed = data.processed || 0;
    const errors = data.errors || [];
    const files = data.files || [];

    let html = `
      <div class="status-card success">
        <div class="status-card-header">
          <svg class="status-card-icon success" width="20" height="20" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round" aria-hidden="true">
            <path d="M22 11.08V12a10 10 0 11-5.93-9.14"/>
            <polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
          <span class="status-card-title">Elaborazione completata</span>
        </div>
        <div class="status-card-detail">
          <p>${processed} file convertit${processed === 1 ? "o" : "i"} con successo.</p>
    `;

    if (files.length > 0) {
      html += `<ul>`;
      files.forEach((f) => {
        const subject = f.subject || "(nessun oggetto)";
        const attCount = f.attachments_count || 0;
        const attLabel =
          attCount === 0
            ? "nessun allegato"
            : `${attCount} allegat${attCount === 1 ? "o" : "i"}`;
        html += `<li><strong>${escapeHtml(f.original_name)}</strong> — ${escapeHtml(subject)} (${attLabel})</li>`;
      });
      html += `</ul>`;
    }

    if (errors.length > 0) {
      html += `<p style="margin-top:8px;color:var(--error)">⚠️ ${errors.length} errore/i:</p><ul>`;
      errors.forEach((e) => {
        html += `<li style="color:var(--error)">${escapeHtml(e)}</li>`;
      });
      html += `</ul>`;
    }

    html += `
          <p style="margin-top:8px">Clicca <strong>"Scarica ZIP"</strong> per ottenere l'archivio con tutti i PDF.</p>
        </div>
      </div>
    `;

    statusSection.style.display = "flex";
    statusSection.innerHTML = html;
  }

  function showErrorStatus(message) {
    statusSection.style.display = "flex";
    statusSection.innerHTML = `
      <div class="status-card error">
        <div class="status-card-header">
          <svg class="status-card-icon error" width="20" height="20" viewBox="0 0 24 24"
               fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="10"/>
            <line x1="15" y1="9" x2="9" y2="15"/>
            <line x1="9" y1="9" x2="15" y2="15"/>
          </svg>
          <span class="status-card-title">Errore</span>
        </div>
        <div class="status-card-detail">
          <p>${escapeHtml(message)}</p>
          <p style="margin-top:4px">Verifica che i file siano nel formato EML corretto e riprova.</p>
        </div>
      </div>
    `;
  }

  // ── Event listeners ───────────────────────────────────────────────────

  // Click sulla drop zone
  dropZone.addEventListener("click", (e) => {
    if (isProcessing) return;
    // Non aprire selettore se cliccato su pulsante remove
    if (e.target.closest(".file-item-remove")) return;
    fileInput.click();
  });

  // Tastiera sulla drop zone
  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (!isProcessing) fileInput.click();
    }
  });

  // File selezionati via input
  fileInput.addEventListener("change", () => {
    if (fileInput.files && fileInput.files.length > 0) {
      addFiles(Array.from(fileInput.files));
      fileInput.value = "";
    }
  });

  // Drag & drop
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isProcessing) dropZone.classList.add("drag-over");
  });

  dropZone.addEventListener("dragleave", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove("drag-over");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropZone.classList.remove("drag-over");
    if (isProcessing) return;
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      addFiles(Array.from(e.dataTransfer.files));
    }
  });

  // Previeni default drag su tutto il documento
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => e.preventDefault());

  // Pulsanti
  convertBtn.addEventListener("click", () => {
    if (!isProcessing && selectedFiles.length > 0) {
      uploadFiles();
    }
  });

  downloadBtn.addEventListener("click", () => {
    downloadZip();
  });

  resetBtn.addEventListener("click", () => {
    resetState();
  });

  // ── Init ──────────────────────────────────────────────────────────────

  updateUI();
})();
