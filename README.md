# AsariyaForum Digital Library — Local PDF Migration

Local-first starter implementation for PDF intake, conservative metadata inspection, disclaimer insertion, branding review, page watermarking, and a basic admin queue.

## Important safety behavior
- Originals are kept in `storage/staging`; processed files go to `storage/output`.
- Files are not marked completed unless the output is reopened and verified.
- The watermark stage has a configurable deadline (default 20 seconds). A timeout/failure leaves no final output and is marked for review/failed.
- OCR is provisional. The app does not infer an author from website attribution or compiler credit.
- Old-brand removal from scanned/image-only pages cannot be guaranteed by text redaction. Such pages are flagged for manual review.
- Disclaimer text is inserted only when a reasonable text check does not find an existing disclaimer. Scanned disclaimer pages may require review.
- Test with copies of books first. This software does not promise perfect layout preservation for all PDFs.

## Requirements
- Python 3.11+
- Node.js 20+
- PostgreSQL 15+ (or compatible; configure `DATABASE_URL`)
- Tesseract OCR installed at `C:\Program Files\Tesseract-OCR\tesseract.exe` on Windows; Urdu trained data at `backend/tessdata/urd.traineddata`.

## Backend setup (PowerShell)
```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
# Edit DATABASE_URL in .env; never share the password.
uvicorn app.main:app --reload
```
API docs: http://127.0.0.1:8000/docs

If PostgreSQL is unavailable, set `DATABASE_URL=sqlite:///./asariya_local.db` for local testing. PostgreSQL is preferred for the intended setup.

## Frontend setup (new terminal)
```powershell
cd frontend
npm install
Copy-Item .env.local.example .env.local
npm run dev
```
Dashboard: http://localhost:3000

## What the pipeline does
1. Validates the PDF and inspects embedded metadata/text.
2. Uses Urdu OCR on the first-page embedded image only as a fallback clue.
3. Creates a processed copy, adds the fixed disclaimer when not detected, and applies `AsariyaForum.com` text watermark to each page.
4. Checks output can be reopened and page count is plausible.
5. Returns `completed` only when verification passes within the watermark deadline. Legacy branding is detected and reported; destructive replacement is deliberately not automatic on image/scanned pages.

## Status definitions
- `uploaded`: received, not processed yet
- `processing`: work underway
- `needs_review`: metadata/branding/disclaimer uncertainty or processing needs human review
- `completed`: output verified
- `failed`: invalid PDF or processing failed
- `timeout`: processing exceeded the configured deadline

This is a functional baseline, not a claim of perfect automated cleanup for every publisher-specific PDF. Test on copies and review output before public distribution.
