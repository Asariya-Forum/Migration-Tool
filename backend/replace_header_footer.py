from pathlib import Path
import fitz

SOURCE = Path(
    r"..\storage\staging\db79b5c3-4b52-4c3c-91ef-63513f32b58a.pdf"
)

OUTPUT = Path(
    r"..\storage\output\header_footer_test.pdf"
)

OLD_HEADER = "www.KitaboSunnat.com"
NEW_HEADER = "www.asariyaforum.com"

def main():
    if not SOURCE.exists():
        raise FileNotFoundError(f"Original PDF nahi mili: {SOURCE.resolve()}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    doc = fitz.open(SOURCE)
    header_count = 0

    try:
        for page in doc:
            matches = page.search_for(OLD_HEADER)

            for rect in matches:
                page.add_redact_annot(rect, fill=(1, 1, 1))
                header_count += 1

            if matches:
                page.apply_redactions(images=0, graphics=0)

                for rect in matches:
                    page.insert_text(
                        (rect.x0, rect.y1 - 2),
                        NEW_HEADER,
                        fontsize=10,
                        fontname="helv",
                        color=(0, 0, 0),
                    )

        doc.save(OUTPUT, garbage=3, deflate=True)
    finally:
        doc.close()

    print(f"Header replacements: {header_count}")
    print(f"Test PDF saved: {OUTPUT.resolve()}")
    print("Original PDF unchanged.")
    print("Footer abhi change nahi kiya gaya hai.")

if __name__ == "__main__":
    main()