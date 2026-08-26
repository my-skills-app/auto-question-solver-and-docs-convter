const $ = (id) => document.getElementById(id);

const uploadPanel = $("uploadPanel");
const progressPanel = $("progressPanel");
const donePanel = $("donePanel");
const errorPanel = $("errorPanel");
const fileInput = $("fileInput");
const dropZone = $("dropZone");
const startBtn = $("startBtn");
const fileList = $("fileList");
const authBadge = $("authBadge");
const barFill = $("barFill");
const pctLabel = $("pctLabel");
const statusMsg = $("statusMsg");
const logBox = $("logBox");
const queueList = $("queueList");
const folderPath = $("folderPath");

let selectedFiles = [];
let eventSource = null;

function show(panel) {
  [uploadPanel, progressPanel, donePanel, errorPanel].forEach((el) =>
    el.classList.add("hidden")
  );
  panel.classList.remove("hidden");
}

async function refreshAuth() {
  try {
    const res = await fetch("/api/auth");
    const data = await res.json();
    if (data.connected) {
      authBadge.textContent = `Connected · ${data.mode || "auth"}`;
      authBadge.classList.remove("off");
    } else {
      authBadge.textContent = "Not connected — run: python -m local_chatgpt login";
      authBadge.classList.add("off");
    }
  } catch {
    authBadge.textContent = "Auth check failed";
    authBadge.classList.add("off");
  }
}

function renderFileList() {
  fileList.innerHTML = "";
  selectedFiles.forEach((f, i) => {
    const li = document.createElement("li");
    li.textContent = `${i + 1}. ${f.name}`;
    fileList.appendChild(li);
  });
  startBtn.disabled = selectedFiles.length === 0;
  startBtn.textContent =
    selectedFiles.length > 1
      ? `Start Queue (${selectedFiles.length} papers)`
      : "Start Solving";
}

function setFiles(fileListLike) {
  const arr = Array.from(fileListLike || []).filter((f) => f && f.name);
  if (!arr.length) return;
  selectedFiles = arr;
  renderFileList();
}

dropZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropZone.classList.add("drag");
});
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag"));
dropZone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropZone.classList.remove("drag");
  setFiles(e.dataTransfer.files);
});
fileInput.addEventListener("change", () => setFiles(fileInput.files));

function setProgress(pct, message) {
  const value = Math.max(0, Math.min(100, Number(pct) || 0));
  barFill.style.width = `${value}%`;
  pctLabel.textContent = `${value.toFixed(0)}%`;
  if (message) statusMsg.textContent = message;
}

function statusBadge(status) {
  if (status === "done") return "done";
  if (status === "error") return "err";
  if (status === "running") return "run";
  return "wait";
}

function renderQueue(items) {
  queueList.innerHTML = "";
  (items || []).forEach((it, idx) => {
    const row = document.createElement("div");
    row.className = `q-item ${statusBadge(it.status)}`;
    const pct = it.status === "running" ? ` ${Math.round(it.percent || 0)}%` : "";
    const qs = it.question_count != null ? ` · ${it.question_count} Qs` : "";
    row.innerHTML = `
      <div class="q-top">
        <strong>${idx + 1}. ${it.filename || "paper"}</strong>
        <span class="q-status">${it.status}${pct}${qs}</span>
      </div>
      <div class="q-msg">${it.message || ""}</div>
      <div class="q-actions"></div>
    `;
    const actions = row.querySelector(".q-actions");
    if (it.status === "done" && it.files) {
      if (it.files.excel) {
        const a = document.createElement("a");
        a.className = "btn download mini";
        a.href = `/api/jobs/${it.job_id}/download/excel`;
        a.textContent = "Excel";
        actions.appendChild(a);
      }
      if (it.files.csv) {
        const a = document.createElement("a");
        a.className = "btn download csv mini";
        a.href = `/api/jobs/${it.job_id}/download/csv`;
        a.textContent = "CSV";
        actions.appendChild(a);
      }
      if (it.files.docx) {
        const a = document.createElement("a");
        a.className = "btn download alt mini";
        a.href = `/api/jobs/${it.job_id}/download/docx`;
        a.textContent = "Word";
        actions.appendChild(a);
      }
      if (it.saved_folder) {
        const tip = document.createElement("div");
        tip.className = "q-folder";
        tip.textContent = it.saved_folder;
        row.appendChild(tip);
      }
    }
    queueList.appendChild(row);
  });
}

function appendBatchLog(data) {
  const cur = data.current;
  const line = document.createElement("div");
  const label = cur
    ? `[${cur.filename}] ${cur.message || data.status}`
    : `${data.done}/${data.total} done · ${data.message || data.status || ""}`;
  line.innerHTML = `<span class="time">${new Date().toLocaleTimeString()}</span>${label}`;
  logBox.appendChild(line);
  while (logBox.children.length > 80) logBox.removeChild(logBox.firstChild);
  logBox.scrollTop = logBox.scrollHeight;
}

let lastLogKey = "";

async function startBatch() {
  if (!selectedFiles.length) return;
  show(progressPanel);
  logBox.innerHTML = "";
  queueList.innerHTML = "";
  setProgress(0, "Uploading papers…");
  folderPath.textContent = "";

  const body = new FormData();
  selectedFiles.forEach((f) => body.append("files", f));
  const force = $("forceImages").checked ? "true" : "false";

  let batchId;
  try {
    const res = await fetch(`/api/batch?force_images=${force}`, {
      method: "POST",
      body,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Upload failed");
    }
    const data = await res.json();
    batchId = data.batch_id;
    folderPath.textContent = `Saving to: ${data.folder}`;
    setProgress(1, `Queued ${data.total} paper(s) — solving one by one`);
  } catch (err) {
    show(errorPanel);
    $("errorMsg").textContent = err.message || String(err);
    return;
  }

  if (eventSource) eventSource.close();
  lastLogKey = "";
  eventSource = new EventSource(`/api/batches/${batchId}/events`);
  eventSource.onmessage = (ev) => {
    const data = JSON.parse(ev.data);
    if (data.error) {
      eventSource.close();
      show(errorPanel);
      $("errorMsg").textContent = data.error;
      return;
    }
    setProgress(
      data.percent,
      data.current
        ? `Paper ${data.done + 1}/${data.total}: ${data.current.filename}`
        : `${data.done}/${data.total} complete`
    );
    if (data.folder) folderPath.textContent = `Saving to: ${data.folder}`;
    renderQueue(data.items);

    const key = `${data.done}-${data.running}-${data.current?.message || ""}-${data.percent}`;
    if (key !== lastLogKey) {
      lastLogKey = key;
      appendBatchLog(data);
    }

    if (["done", "done_with_errors", "error"].includes(data.status)) {
      eventSource.close();
      $("doneSummary").textContent =
        data.error === data.total
          ? "All papers failed."
          : `Done: ${data.done} ok` +
            (data.error ? `, ${data.error} failed` : "") +
            ` · ${data.total} total`;
      $("doneFolder").textContent = data.folder
        ? `Folder: ${data.folder}`
        : "";
      $("doneList").innerHTML = "";
      // reuse renderer into done list
      const prev = queueList;
      // clone nodes
      renderQueue(data.items);
      $("doneList").innerHTML = queueList.innerHTML;
      show(donePanel);
    }
  };
}

startBtn.addEventListener("click", startBatch);
$("againBtn").addEventListener("click", () => {
  selectedFiles = [];
  fileInput.value = "";
  fileList.innerHTML = "";
  startBtn.disabled = true;
  startBtn.textContent = "Start Queue";
  show(uploadPanel);
});
$("retryBtn").addEventListener("click", () => show(uploadPanel));

refreshAuth();
