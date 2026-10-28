
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.db_models import MigrationJobRecord
from app.core.config import settings, storage_path
from app.services.pipeline import inspect_pdf, process_pdf

router = APIRouter()


class MetadataReview(BaseModel):
    title: str = ""
    author: str = ""
    publisher: str = ""
    category: str = ""


def serialize(j):
    return {
        "id": j.id,
        "filename": j.filename,
        "size_bytes": j.size_bytes,
        "status": j.status,
        "stage": j.stage,
        "message": j.message,
        "metadata": json.loads(j.metadata_json or "{}"),
        "output_available": bool(
            j.output_path and Path(j.output_path).is_file()
        ),
        "created_at": j.created_at.isoformat() if j.created_at else None,
    }


@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "AsariyaForum PDF Migration API",
    }


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db)):
    return [
        serialize(j)
        for j in db.query(MigrationJobRecord)
        .order_by(MigrationJobRecord.created_at.desc())
        .limit(500)
        .all()
    ]


@router.post("/jobs/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    root = storage_path()
    staging = root / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    created = []

    for file in files:
        if not file.filename or not file.filename.lower().endswith(".pdf"):
            continue

        job_id = str(uuid.uuid4())
        safe = Path(file.filename).name[:200]
        dest = staging / f"{job_id}.pdf"
        size = 0

        try:
            with dest.open("wb") as out:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break

                    size += len(chunk)
                    if size > settings.max_upload_mb * 1024 * 1024:
                        raise HTTPException(
                            413,
                            f"{safe} exceeds upload limit",
                        )

                    out.write(chunk)

            result = inspect_pdf(dest)

            if result.get("status") == "failed":
                dest.unlink(missing_ok=True)
                continue

            metadata = result.get("metadata", {})
            metadata.setdefault("title", "")
            metadata.setdefault("author", "")
            metadata.setdefault("publisher", "")
            metadata.setdefault("category", "")
            metadata.setdefault("review_required", True)

            row = MigrationJobRecord(
                id=job_id,
                filename=safe,
                size_bytes=size,
                status=result.get("status", "uploaded"),
                stage=result.get("stage", "upload"),
                message=result.get("message", ""),
                input_path=str(dest),
                metadata_json=json.dumps(
                    metadata,
                    ensure_ascii=False,
                ),
            )

            db.add(row)
            db.flush()
            created.append(serialize(row))

        except Exception:
            dest.unlink(missing_ok=True)
            raise
        finally:
            await file.close()

    db.commit()

    if not created:
        raise HTTPException(400, "Upload one or more valid PDF files.")

    return {"jobs": created}


@router.put("/jobs/{job_id}/metadata")
def save_metadata(
    job_id: str,
    data: MetadataReview,
    db: Session = Depends(get_db),
):
    job = db.get(MigrationJobRecord, job_id)

    if not job:
        raise HTTPException(404, "Job not found")

    # Preserve processing results and other existing metadata.
    metadata = json.loads(job.metadata_json or "{}")

    metadata["title"] = data.title.strip()
    metadata["author"] = data.author.strip()
    metadata["publisher"] = data.publisher.strip()
    metadata["category"] = data.category.strip()
    metadata["metadata_reviewed"] = True
    metadata["review_required"] = True

    job.metadata_json = json.dumps(
        metadata,
        ensure_ascii=False,
    )
    job.message = "Metadata saved for review."

    db.commit()
    db.refresh(job)

    return serialize(job)


@router.post("/jobs/{job_id}/process")
def process_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = db.get(MigrationJobRecord, job_id)

    if not job:
        raise HTTPException(404, "Job not found")

    job.status = "processing"
    job.stage = "processing"
    job.message = "Processing started"
    db.commit()

    out = storage_path() / "output" / f"{job.id}_asariyaforum.pdf"
    result = process_pdf(Path(job.input_path), out)

    job.status = result.get("status", "failed")
    job.stage = result.get("stage", "processing")
    job.message = result.get("message", "")

    if result.get("output_path"):
        job.output_path = result["output_path"]

    metadata = json.loads(job.metadata_json or "{}")
    metadata["processing_result"] = result
    job.metadata_json = json.dumps(
        metadata,
        ensure_ascii=False,
    )

    db.commit()
    db.refresh(job)

    return serialize(job)


@router.get("/jobs/{job_id}/download")
def download_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = db.get(MigrationJobRecord, job_id)

    if (
        not job
        or not job.output_path
        or not Path(job.output_path).is_file()
    ):
        raise HTTPException(
            404,
            "Verified output not available",
        )

    return FileResponse(
        job.output_path,
        filename=Path(job.output_path).name,
        media_type="application/pdf",
    )
