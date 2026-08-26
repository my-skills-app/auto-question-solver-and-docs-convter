"""
AI Question Solver — Web UI (multi-paper queue)

Run:
  .\\.venv\\Scripts\\python.exe -m web.server
Then open http://127.0.0.1:7860
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
JOBS_DIR = ROOT / "temp" / "jobs"
BATCHES_DIR = ROOT / "output" / "batches"
STATIC = Path(__file__).resolve().parent / "static"

JOBS_DIR.mkdir(parents=True, exist_ok=True)
BATCHES_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="AI Question Solver")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_jobs: dict[str, dict[str, Any]] = {}
_batches: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()
_queue: list[str] = []  # job_ids waiting
_worker_busy = False

ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_name(name: str) -> str:
    stem = Path(name).stem
    stem = re.sub(r"[^\w\-]+", "_", stem, flags=re.UNICODE).strip("_")
    return (stem or "paper")[:80]


def _job_update(job_id: str, **fields: Any) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(fields)
        if "message" in fields:
            logs = job.setdefault("logs", [])
            logs.append(
                {
                    "t": time.strftime("%H:%M:%S"),
                    "msg": fields["message"],
                    "pct": job.get("percent", 0),
                }
            )
            if len(logs) > 200:
                del logs[:-200]
        job["updated_at"] = time.time()
        batch_id = job.get("batch_id")
        if batch_id and batch_id in _batches:
            _batches[batch_id]["updated_at"] = time.time()


def _batch_snapshot(batch_id: str) -> dict[str, Any]:
    batch = _batches[batch_id]
    items = []
    done = 0
    error = 0
    running = 0
    queued = 0
    for jid in batch["job_ids"]:
        job = _jobs.get(jid, {})
        status = job.get("status", "queued")
        if status == "done":
            done += 1
        elif status == "error":
            error += 1
        elif status == "running":
            running += 1
        else:
            queued += 1
        items.append(
            {
                "job_id": jid,
                "filename": job.get("filename"),
                "status": status,
                "percent": job.get("percent", 0),
                "message": job.get("message", ""),
                "question_count": job.get("question_count"),
                "saved_folder": job.get("saved_folder"),
                "files": {k: True for k in (job.get("files") or {})},
                "error": job.get("error"),
            }
        )
    total = max(len(items), 1)
    # overall % = completed papers + current paper fraction
    overall = 0.0
    for it in items:
        if it["status"] == "done":
            overall += 100.0
        elif it["status"] == "running":
            overall += float(it["percent"] or 0)
        elif it["status"] == "error":
            overall += 100.0
    overall = round(overall / total, 1)
    batch_status = "queued"
    if running or (done + error > 0 and done + error < total):
        batch_status = "running"
    if done + error == total:
        batch_status = "done" if error == 0 else "done_with_errors"
    if done + error == total and done == 0:
        batch_status = "error"
    return {
        "batch_id": batch_id,
        "status": batch_status,
        "percent": overall,
        "folder": batch.get("folder"),
        "created_at": batch.get("created_stamp"),
        "total": len(items),
        "done": done,
        "error": error,
        "running": running,
        "queued": queued,
        "items": items,
        "current": next((it for it in items if it["status"] == "running"), None),
    }


def _copy_outputs(job_id: str, src_files: dict[str, str], paper_name: str) -> dict[str, Any]:
    """Copy Excel/Word/CSV into batch folder with filename_timestamp."""
    with _lock:
        job = _jobs[job_id]
        batch_id = job["batch_id"]
        batch_folder = Path(_batches[batch_id]["folder"])
        index = job.get("index", 1)

    ts = _stamp()
    safe = _safe_name(paper_name)
    paper_dir = batch_folder / f"{index:02d}_{safe}_{ts}"
    paper_dir.mkdir(parents=True, exist_ok=True)

    saved: dict[str, str] = {}
    exts = {"excel": ".xlsx", "docx": ".docx", "csv": ".csv"}
    for label, src in src_files.items():
        src_path = Path(src)
        if not src_path.exists():
            continue
        dest = paper_dir / f"{safe}_{ts}{exts.get(label, src_path.suffix)}"
        shutil.copy2(src_path, dest)
        saved[label] = str(dest.resolve())

    # small marker so user knows when this paper finished
    meta = {
        "paper": paper_name,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "timestamp": ts,
        "job_id": job_id,
        "files": {k: Path(v).name for k, v in saved.items()},
    }
    (paper_dir / "info.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {"saved_folder": str(paper_dir.resolve()), "files": saved, "timestamp": ts}


def _run_solve(job_id: str) -> None:
    from app.pipeline import solve_file

    with _lock:
        job = dict(_jobs[job_id])
    file_path = Path(job["input_path"]).resolve()
    out_dir = (JOBS_DIR / job_id / "output").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    force_images = bool(job.get("force_images", True))
    original_name = job.get("filename") or file_path.name

    _job_update(job_id, status="running", percent=1, message=f"Starting: {original_name}")

    if not file_path.exists():
        _job_update(
            job_id,
            status="error",
            message=f"Failed: uploaded file missing: {file_path}",
            error=f"uploaded file missing: {file_path}",
        )
        return

    def on_progress(msg: str, pct: float) -> None:
        _job_update(job_id, percent=round(float(pct), 1), message=msg)

    try:
        result = solve_file(
            file_path,
            out_dir=out_dir,
            force_images=force_images,
            set_name=_safe_name(original_name),
            progress=on_progress,
        )
        paths = result.get("paths") or {}
        files: dict[str, str] = {}
        for key, label in (("xlsx", "excel"), ("docx", "docx"), ("csv", "csv")):
            p = paths.get(key)
            if p and Path(p).exists():
                files[label] = str(Path(p).resolve())
        for name, label in (
            ("solved_questions.xlsx", "excel"),
            ("solved_questions.docx", "docx"),
            ("solved_questions.csv", "csv"),
        ):
            p = out_dir / name
            if p.exists() and label not in files:
                files[label] = str(p.resolve())

        saved = _copy_outputs(job_id, files, original_name)
        qcount = len(result.get("questions_raw") or [])
        _job_update(
            job_id,
            status="done",
            percent=100,
            message=f"Saved {qcount} Qs → {saved['saved_folder']}",
            files=saved["files"],
            saved_folder=saved["saved_folder"],
            timestamp=saved["timestamp"],
            question_count=qcount,
        )
    except Exception as exc:  # noqa: BLE001
        _job_update(
            job_id,
            status="error",
            message=f"Failed: {exc}",
            error=str(exc),
        )


def _worker_loop() -> None:
    global _worker_busy
    while True:
        with _lock:
            if not _queue:
                _worker_busy = False
                return
            job_id = _queue.pop(0)
            _worker_busy = True
        _run_solve(job_id)


def _ensure_worker() -> None:
    global _worker_busy
    with _lock:
        if _worker_busy:
            return
        _worker_busy = True
    threading.Thread(target=_worker_loop, daemon=True).start()


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/api/auth")
def auth_status() -> dict:
    from app.auth import status

    return status()


@app.post("/api/batch")
async def create_batch(
    files: list[UploadFile] = File(...),
    force_images: bool = True,
) -> dict:
    if not files:
        raise HTTPException(400, "No files uploaded")

    stamp = _stamp()
    batch_id = f"batch_{stamp}_{uuid.uuid4().hex[:6]}"
    batch_folder = (BATCHES_DIR / batch_id).resolve()
    batch_folder.mkdir(parents=True, exist_ok=True)

    job_ids: list[str] = []
    accepted: list[dict[str, Any]] = []

    for idx, upload in enumerate(files, start=1):
        if not upload.filename:
            continue
        suffix = Path(upload.filename).suffix.lower()
        if suffix not in ALLOWED:
            continue
        data = await upload.read()
        if not data:
            continue

        job_id = uuid.uuid4().hex[:12]
        job_dir = JOBS_DIR / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        dest = (job_dir / f"input{suffix}").resolve()
        with dest.open("wb") as f:
            f.write(data)
            f.flush()

        with _lock:
            _jobs[job_id] = {
                "id": job_id,
                "batch_id": batch_id,
                "index": idx,
                "status": "queued",
                "percent": 0,
                "message": "Queued — waiting for previous papers",
                "logs": [],
                "files": {},
                "filename": upload.filename,
                "input_path": str(dest),
                "force_images": force_images,
                "created_at": time.time(),
                "updated_at": time.time(),
            }
            _queue.append(job_id)
        job_ids.append(job_id)
        accepted.append({"job_id": job_id, "filename": upload.filename, "index": idx})

    if not job_ids:
        raise HTTPException(400, "No valid PDF/image files")

    with _lock:
        _batches[batch_id] = {
            "id": batch_id,
            "folder": str(batch_folder),
            "created_stamp": stamp,
            "job_ids": job_ids,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

    _ensure_worker()
    return {
        "batch_id": batch_id,
        "folder": str(batch_folder),
        "total": len(job_ids),
        "files": accepted,
        "message": "Papers queued — solving one by one",
    }


# Keep single-upload for compatibility → creates 1-paper batch
@app.post("/api/upload")
async def upload_one(
    file: UploadFile = File(...),
    force_images: bool = True,
) -> dict:
    result = await create_batch([file], force_images=force_images)
    return {
        "batch_id": result["batch_id"],
        "job_id": result["files"][0]["job_id"],
        "filename": result["files"][0]["filename"],
        "folder": result["folder"],
    }


@app.get("/api/batches/{batch_id}")
def batch_status(batch_id: str) -> dict:
    with _lock:
        if batch_id not in _batches:
            raise HTTPException(404, "Batch not found")
        return _batch_snapshot(batch_id)


@app.get("/api/batches/{batch_id}/events")
async def batch_events(batch_id: str) -> StreamingResponse:
    async def event_stream():
        while True:
            with _lock:
                if batch_id not in _batches:
                    yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                    break
                payload = _batch_snapshot(batch_id)
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if payload["status"] in {"done", "done_with_errors", "error"}:
                break
            await asyncio.sleep(0.8)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return {
            "id": job["id"],
            "batch_id": job.get("batch_id"),
            "status": job["status"],
            "percent": job.get("percent", 0),
            "message": job.get("message", ""),
            "logs": job.get("logs", [])[-30:],
            "files": {k: True for k in (job.get("files") or {})},
            "saved_folder": job.get("saved_folder"),
            "question_count": job.get("question_count"),
            "filename": job.get("filename"),
            "error": job.get("error"),
        }


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> StreamingResponse:
    async def event_stream():
        last_len = 0
        while True:
            with _lock:
                job = _jobs.get(job_id)
                if not job:
                    yield f"data: {json.dumps({'error': 'not_found'})}\n\n"
                    break
                payload = {
                    "status": job["status"],
                    "percent": job.get("percent", 0),
                    "message": job.get("message", ""),
                    "logs": job.get("logs", [])[last_len:],
                    "files": {k: True for k in (job.get("files") or {})},
                    "saved_folder": job.get("saved_folder"),
                    "question_count": job.get("question_count"),
                    "batch_id": job.get("batch_id"),
                }
                last_len = len(job.get("logs", []))
                status = job["status"]
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            if status in {"done", "error"}:
                break
            await asyncio.sleep(0.6)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/jobs/{job_id}/download/{kind}")
def download(job_id: str, kind: str) -> FileResponse:
    kind = kind.lower()
    mapping = {
        "excel": "excel",
        "xlsx": "excel",
        "docx": "docx",
        "word": "docx",
        "csv": "csv",
    }
    key = mapping.get(kind)
    if not key:
        raise HTTPException(400, "kind must be excel|docx|csv")

    with _lock:
        job = _jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job.get("status") != "done":
            raise HTTPException(409, "Job not complete yet")
        path = (job.get("files") or {}).get(key)
        download_name = Path(path).name if path else None

    if not path or not Path(path).exists():
        raise HTTPException(404, f"{key} file not ready")

    media = {
        "excel": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "csv": "text/csv",
    }[key]
    return FileResponse(
        path,
        media_type=media,
        filename=download_name or f"solved_questions.{key}",
    )


def main() -> None:
    import uvicorn

    print("AI Question Solver -> http://127.0.0.1:7860")
    print(f"Batch saves -> {BATCHES_DIR}")
    uvicorn.run("web.server:app", host="127.0.0.1", port=7860, reload=False)


if __name__ == "__main__":
    main()
