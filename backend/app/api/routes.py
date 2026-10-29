"""API routes for AsariyaForum PDF Bulk Migration Utility."""

import json
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings, storage_path
from app.core.database import get_db
from app.models.db_models import MigrationJobRecord
from app.services.pipeline import inspect_pdf, process_pdf


router = APIRouter()


# ---------------------------------------------------------
# REQUEST MODELS
# ---------------------------------------------------------

class MetadataReview(BaseModel):
    title: str = ""
    author: str = ""
    publisher: str = ""
    category: str = ""


# ---------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------

def serialize(job: MigrationJobRecord) -> dict:
    """Convert a database job record into an API response."""

    try:
        metadata = json.loads(job.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    output_available = bool(
        job.output_path
        and Path(job.output_path).is_file()
    )

    return {
        "id": job.id,
        "filename": job.filename,
        "size_bytes": job.size_bytes,
        "status": job.status,
        "stage": job.stage,
        "message": job.message,
        "metadata": metadata,
        "output_available": output_available,
        "created_at": (
            job.created_at.isoformat()
            if job.created_at
            else None
        ),
    }


def get_job_or_404(
    job_id: str,
    db: Session,
) -> MigrationJobRecord:
    """Retrieve a job or raise HTTP 404."""

    job = db.get(MigrationJobRecord, job_id)

    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Job not found.",
        )

    return job


def safe_metadata_json(metadata: dict) -> str:
    """Serialize metadata while preserving Urdu and other Unicode text."""

    return json.dumps(
        metadata,
        ensure_ascii=False,
    )


# ---------------------------------------------------------
# HEALTH CHECK
# ---------------------------------------------------------

@router.get("/health")
def health():
    return {
        "status": "ok",
        "service": "AsariyaForum PDF Migration API",
    }


# ---------------------------------------------------------
# LIST MIGRATION JOBS
# ---------------------------------------------------------

@router.get("/jobs")
def list_jobs(
    db: Session = Depends(get_db),
):
    jobs = (
        db.query(MigrationJobRecord)
        .order_by(MigrationJobRecord.created_at.desc())
        .limit(500)
        .all()
    )

    return [serialize(job) for job in jobs]


# ---------------------------------------------------------
# BULK PDF UPLOAD
# ---------------------------------------------------------

@router.post("/jobs/upload")
async def upload_files(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    root = storage_path()
    staging = root / "staging"

    staging.mkdir(
        parents=True,
        exist_ok=True,
    )

    created_jobs = []
    created_paths = []

    try:
        for file in files:
            original_name = file.filename or ""

            # Only accept PDF files.
            if (
                not original_name
                or not original_name.lower().endswith(".pdf")
            ):
                continue

            # Use only the filename, never the supplied directory path.
            safe_filename = Path(original_name).name[:200]

            if not safe_filename:
                continue

            job_id = str(uuid.uuid4())
            destination = staging / f"{job_id}.pdf"
            size = 0

            try:
                with destination.open("wb") as output:
                    while True:
                        chunk = await file.read(1024 * 1024)

                        if not chunk:
                            break

                        size += len(chunk)

                        # Enforce the configured upload limit.
                        if (
                            size
                            > settings.max_upload_mb * 1024 * 1024
                        ):
                            raise HTTPException(
                                status_code=413,
                                detail=(
                                    f"{safe_filename} exceeds the "
                                    f"{settings.max_upload_mb} MB "
                                    "upload limit."
                                ),
                            )

                        output.write(chunk)

                if size == 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"{safe_filename} is empty.",
                    )

                # IMPORTANT:
                # Pass the original filename so metadata extraction
                # does not mistake the UUID staging filename for a title.
                result = inspect_pdf(
                    destination,
                    original_filename=safe_filename,
                )

                if result.get("status") == "failed":
                    destination.unlink(missing_ok=True)

                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"Could not inspect {safe_filename}: "
                            f"{result.get('message', 'Invalid PDF.')}"
                        ),
                    )

                metadata = result.get("metadata") or {}

                # Ensure the expected metadata fields always exist.
                metadata.setdefault("title", "")
                metadata.setdefault("author", "")
                metadata.setdefault("publisher", "")
                metadata.setdefault("category", "")
                metadata.setdefault("review_required", True)
                metadata.setdefault("review_reasons", [])

                job = MigrationJobRecord(
                    id=job_id,
                    filename=safe_filename,
                    size_bytes=size,
                    status=result.get(
                        "status",
                        "needs_review",
                    ),
                    stage=result.get(
                        "stage",
                        "metadata_review",
                    ),
                    message=result.get("message", ""),
                    input_path=str(destination.resolve()),
                    metadata_json=safe_metadata_json(metadata),
                )

                db.add(job)
                db.flush()

                created_paths.append(destination)
                created_jobs.append(serialize(job))

            finally:
                await file.close()

        if not created_jobs:
            raise HTTPException(
                status_code=400,
                detail="Upload one or more valid PDF files.",
            )

        db.commit()

        return {
            "jobs": created_jobs,
            "count": len(created_jobs),
            "message": "PDF upload and inspection completed.",
        }

    except Exception:
        db.rollback()

        # Remove newly uploaded files if the database transaction fails.
        # Existing previously uploaded jobs are not affected.
        for path in created_paths:
            path.unlink(missing_ok=True)

        raise


# ---------------------------------------------------------
# SAVE / REVIEW METADATA
# ---------------------------------------------------------

@router.put("/jobs/{job_id}/metadata")
def save_metadata(
    job_id: str,
    data: MetadataReview,
    db: Session = Depends(get_db),
):
    job = get_job_or_404(job_id, db)

    try:
        metadata = json.loads(job.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    # Update the reviewed fields without deleting other metadata.
    metadata["title"] = data.title.strip()
    metadata["author"] = data.author.strip()
    metadata["publisher"] = data.publisher.strip()
    metadata["category"] = data.category.strip()
    metadata["metadata_reviewed"] = True

    required_fields = (
        metadata["title"],
        metadata["author"],
        metadata["publisher"],
        metadata["category"],
    )

    metadata["review_required"] = not all(
        value.strip() for value in required_fields
    )

    # Remove reasons that are no longer applicable.
    reasons = list(metadata.get("review_reasons", []))

    field_reason_map = {
        "title": "Confirm title",
        "author": "Author not confidently detected",
        "publisher": "Publisher not confidently detected",
        "category": "Confirm category",
    }

    for field, reason in field_reason_map.items():
        if metadata.get(field):
            reasons = [
                item for item in reasons
                if item != reason
            ]

    if metadata.get("ocr_used"):
        if "OCR used; verify extracted metadata" not in reasons:
            reasons.append("OCR used; verify extracted metadata")

    metadata["review_reasons"] = reasons

    job.metadata_json = safe_metadata_json(metadata)

    job.message = (
        "Metadata saved. Some fields still need review."
        if metadata["review_required"]
        else "Metadata saved. Please verify the extracted information."
    )

    try:
        db.commit()
        db.refresh(job)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not save metadata.",
        )

    return serialize(job)


# ---------------------------------------------------------
# PROCESS PDF
# ---------------------------------------------------------

@router.post("/jobs/{job_id}/process")
def process_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = get_job_or_404(job_id, db)

    # Do not start processing when the input file is missing.
    input_path = Path(job.input_path)

    if not input_path.is_file():
        raise HTTPException(
            status_code=404,
            detail="The original uploaded PDF could not be found.",
        )

    # Check whether the metadata needs review.
    try:
        metadata = json.loads(job.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        metadata = {}

    if metadata.get("review_required", True):
        raise HTTPException(
            status_code=409,
            detail=(
                "Metadata review is required before processing. "
                "Please review the title, author, publisher and category."
            ),
        )

    # Update the status before processing starts.
    job.status = "processing"
    job.stage = "watermarking"
    job.message = "PDF branding and watermarking started."

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not update the processing status.",
        )

    output_directory = storage_path() / "output"
    output_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        output_directory
        / f"{job.id}_asariyaforum.pdf"
    )

    try:
        result = process_pdf(
            input_path,
            output_path,
        )

    except Exception as exc:
        job.status = "failed"
        job.stage = "processing"
        job.message = f"PDF processing failed: {exc}"

        try:
            db.commit()
        except Exception:
            db.rollback()

        return serialize(job)

    job.status = result.get("status", "failed")
    job.stage = result.get("stage", "processing")
    job.message = result.get("message", "")

    if (
        result.get("status") == "completed"
        and result.get("output_path")
    ):
        final_path = Path(result["output_path"])

        if final_path.is_file():
            job.output_path = str(final_path.resolve())
        else:
            job.status = "failed"
            job.stage = "storage"
            job.message = (
                "Processing reported completion, "
                "but the output PDF could not be found."
            )

    metadata["processing_result"] = result
    job.metadata_json = safe_metadata_json(metadata)

    try:
        db.commit()
        db.refresh(job)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not save the processing result.",
        )

    return serialize(job)


# ---------------------------------------------------------
# DOWNLOAD PROCESSED PDF
# ---------------------------------------------------------

@router.get("/jobs/{job_id}/download")
def download_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    job = get_job_or_404(job_id, db)

    if (
        job.status != "completed"
        or not job.output_path
        or not Path(job.output_path).is_file()
    ):
        raise HTTPException(
            status_code=404,
            detail="Verified output PDF is not available.",
        )

    return FileResponse(
        path=job.output_path,
        filename=Path(job.output_path).name,
        media_type="application/pdf",
    )