document.addEventListener("DOMContentLoaded", () => {
  const API_BASE =
    (window.API_BASE && window.API_BASE.trim()) ||
    (location.origin.startsWith("http") ? location.origin : "http://127.0.0.1:8000");

  // toast (works on both pages)
  const showToast = (msg, type = "ok") => {
    let el = document.getElementById("toast");
    if (!el) { el = document.createElement("div"); el.id = "toast"; document.body.appendChild(el); }
    el.className = `toast toast--${type}`;
    el.textContent = msg;
    el.classList.remove("hidden");
    setTimeout(() => el.classList.add("hidden"), 3000);
  };

  // ----- elements (present on one or both pages) -----
  const uploadButton = document.getElementById("uploadButton");
  const fileInput = document.getElementById("fileInput");
  const dropParse = document.getElementById("dropParse");
  const browseParse = document.getElementById("browseParse");
  const parseSelected = document.getElementById("parseSelected");

  const jdButton = document.getElementById("jdButton");
  const singleResumeInput = document.getElementById("singleResumeInput");
  const dropSingle = document.getElementById("dropSingle");
  const browseSingle = document.getElementById("browseSingle");
  const singleSelected = document.getElementById("singleSelected");

  const outputDiv = document.getElementById("output");
  const loadingDiv = document.getElementById("loading");
  const jdTextarea = document.getElementById("jdTextarea");
  const jdCount = document.getElementById("jdCount");

  const bulkResumes = document.getElementById("bulkResumes");
  const dropBulk = document.getElementById("dropBulk");
  const browseBulk = document.getElementById("browseBulk");
  const bulkSelected = document.getElementById("bulkSelected");
  const bulkJDTextarea = document.getElementById("bulkJDTextarea");
  const bulkJDCount = document.getElementById("bulkJDCount");
  const bulkMatchButton = document.getElementById("bulkMatchButton");
  const bulkOutput = document.getElementById("bulkOutput");
  const backButton = document.getElementById("backButton");

  // counters
  jdTextarea?.addEventListener("input", () => jdCount.textContent = `${jdTextarea.value.length} characters`);
  bulkJDTextarea?.addEventListener("input", () => bulkJDCount.textContent = `${bulkJDTextarea.value.length} characters`);

  // ----- selected filename badges -----
  const setSelected = (el, files) => {
    if (!el) return;
    if (!files || files.length === 0) { el.innerHTML = 'No file selected'; return; }
    if (files.length === 1) {
      el.innerHTML = `Selected: <span class="badge">${files[0].name}</span>`;
    } else {
      const names = Array.from(files).slice(0, 3).map(f => f.name);
      const more = files.length > 3 ? ` +${files.length - 3} more` : '';
      el.innerHTML = `Selected (${files.length}): <span class="badge">${names.join('</span> <span class="badge">')}</span>${more}`;
    }
  };

  // ----- drag & drop wiring -----
  const wireDrop = (zone, input, selectedEl, allowMultiple = false) => {
    if (!zone || !input) return;
    const activate = () => zone.classList.add("dropzone--active");
    const deactivate = () => zone.classList.remove("dropzone--active");
    const updateUI = () => {
      const files = input.files || [];
      setSelected(selectedEl, files);
      if (files.length) zone.classList.add("dropzone--filled");
      else zone.classList.remove("dropzone--filled");
    };

    zone.addEventListener("click", () => input.click());
    zone.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") input.click(); });
    zone.addEventListener("dragenter", (e) => { e.preventDefault(); activate(); });
    zone.addEventListener("dragover", (e) => { e.preventDefault(); activate(); });
    zone.addEventListener("dragleave", (e) => { e.preventDefault(); deactivate(); });
    zone.addEventListener("drop", (e) => {
      e.preventDefault(); deactivate();
      if (!e.dataTransfer?.files?.length) return;
      if (allowMultiple) {
        input.files = e.dataTransfer.files;
      } else {
        const dt = new DataTransfer();
        dt.items.add(e.dataTransfer.files[0]);
        input.files = dt.files;
      }
      input.dispatchEvent(new Event('change', { bubbles: true }));
    });

    input.addEventListener("change", updateUI);
    updateUI();
  };

  // wire zones if present (index.html will have the first two)
  wireDrop(dropParse, fileInput, parseSelected, false);
  wireDrop(dropSingle, singleResumeInput, singleSelected, false);
  // bulk page wiring
wireDrop(dropBulk, bulkResumes, bulkSelected, true);
  // bulk page wiring stays harmless if those IDs are missing

  // browse links
  browseParse?.addEventListener("click", (e) => { e.preventDefault(); fileInput.click(); });
  browseSingle?.addEventListener("click", (e) => { e.preventDefault(); singleResumeInput.click(); });
  browseBulk?.addEventListener("click", (e) => { e.preventDefault(); bulkResumes.click(); });

  backButton?.addEventListener("click", () => { window.location.href = "index.html"; });

  // ----- Parse-only -----
  uploadButton?.addEventListener("click", async () => {
    if (uploadButton.disabled) return;
    outputDiv && (outputDiv.innerHTML = "");
    loadingDiv && loadingDiv.classList.remove("hidden");
    uploadButton.disabled = true;

    const file = fileInput?.files?.[0];
    if (!file) {
      loadingDiv && loadingDiv.classList.add("hidden");
      uploadButton.disabled = false;
      return showToast("Please select a PDF.", "error");
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(`${API_BASE}/upload-resume`, { method: "POST", body: formData });
      const result = await response.json().catch(() => ({}));
      loadingDiv && loadingDiv.classList.add("hidden");
      uploadButton.disabled = false;

      if (!response.ok) return showToast(result.detail || "Resume extraction failed.", "error");

      if (result.status === "success") {
        const data = result.extracted_data || {};
        let html = "<h2>Extracted Resume Data</h2>";
        for (const key in data) {
          const val = (data[key] || "").toString().trim();
          if (val) {
            html += `
              <div class="section">
                <h3>${key}</h3>
                <pre>${val}</pre>
              </div>`;
          }
        }
        outputDiv && (outputDiv.innerHTML = html);
        showToast("Resume parsed successfully.", "ok");
      } else {
        showToast(result.message || "Unknown error.", "error");
      }
    } catch (err) {
      console.error(err);
      loadingDiv && loadingDiv.classList.add("hidden");
      uploadButton.disabled = false;
      showToast("Error while processing the resume.", "error");
    }
  });

  // ----- Single JD match -----
  jdButton?.addEventListener("click", async () => {
    if (jdButton.disabled) return;
    const resumeFile = singleResumeInput?.files?.[0];
    const jdText = (jdTextarea?.value || "").trim();

    if (!resumeFile) return showToast("Please select a resume PDF.", "error");
    if (!jdText) return showToast("Please paste the JD text.", "error");

    const formData = new FormData();
    formData.append("resume", resumeFile);
    formData.append("jd_text", jdText);

    try {
      jdButton.disabled = true;
      const response = await fetch(`${API_BASE}/match-resume-jd`, { method: "POST", body: formData });
      const result = await response.json().catch(() => ({}));
      jdButton.disabled = false;

      if (response.ok && result.status === "success") {
        let html = `<h2>Matching Score: ${result.match_score}</h2>`;
        if (result.parsed_resume) {
          html += `<h3 class="label" style="margin-top:12px;">Parsed Resume</h3>`;
          for (const key in result.parsed_resume) {
            const val = (result.parsed_resume[key] || "").toString().trim();
            if (val) {
              html += `
                <div class="section">
                  <h3>${key}</h3>
                  <pre>${val}</pre>
                </div>`;
            }
          }
        }
        const out = document.getElementById("output");
        out && (out.innerHTML = html);
        showToast("JD matched successfully.", "ok");
      } else {
        showToast(result.detail || result.message || "JD matching failed.", "error");
      }
    } catch (err) {
      console.error(err);
      jdButton.disabled = false;
      showToast("Error during JD matching.", "error");
    }
  });

  // ----- Bulk match handler also exists here (no-op on index unless IDs are present) -----
  bulkMatchButton?.addEventListener?.("click", async () => {
    if (bulkMatchButton.disabled) return;
    bulkOutput && (bulkOutput.innerHTML = "");
    const jdText = (bulkJDTextarea?.value || "").trim();
    const resumeFiles = Array.from(bulkResumes?.files || []);

    if (!jdText) return showToast("Please paste the JD text.", "error");
    if (!resumeFiles.length) return showToast("Please select 1+ resumes.", "error");

    const formData = new FormData();
    formData.append("jd_text", jdText);
    resumeFiles.forEach((f) => formData.append("resumes", f));

    try {
      bulkMatchButton.disabled = true;
      const loader = document.getElementById("loading");
      loader && loader.classList.remove("hidden");

      const response = await fetch(`${API_BASE}/bulk-match?min_score=7`, { method: "POST", body: formData });
      const result = await response.json().catch(() => ({}));

      loader && loader.classList.add("hidden");
      bulkMatchButton.disabled = false;

      if (!response.ok || result.status !== "success") {
        return showToast(result.detail || result.message || "Bulk matching failed.", "error");
      }

      const matches = result.matches || [];
      let html = `<h2>Matches (score ≥ 7)</h2>`;
      if (!matches.length) {
        html += `<div class="toast">No resumes met the threshold.</div>`;
      } else {
        html += `<div class="section"><ul style="margin:0;padding-left:18px">`;
        for (const m of matches) {
          html += `<li><strong>${m.filename}</strong> — Score: ${m.score}</li>`;
        }
        html += `</ul></div>`;
      }
      bulkOutput && (bulkOutput.innerHTML = html);
      showToast("Bulk match complete.", "ok");
    } catch (err) {
      console.error(err);
      const loader = document.getElementById("loading");
      loader && loader.classList.add("hidden");
      bulkMatchButton.disabled = false;
      showToast("Error during bulk matching.", "error");
    }
  });
});
