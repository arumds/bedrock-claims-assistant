"""Step 2.3 - Document upload functionality.

  python step2_poc/upload_documents.py                 # upload all sample claims + policies
  python step2_poc/upload_documents.py my_claim.pdf    # upload one claim file
  python step2_poc/upload_documents.py --list          # list bucket contents
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402
from step2_poc.s3_storage import DocumentStore  # noqa: E402

ALLOWED = {".txt", ".md", ".pdf", ".docx", ".doc", ".html", ".csv"}


def upload_claim(store: DocumentStore, path: Path) -> str:
    """Upload one claim file to claims/ after checking its type."""
    if path.suffix.lower() not in ALLOWED:
        raise ValueError(f"Unsupported file type {path.suffix}; allowed: {sorted(ALLOWED)}")
    return store.upload_file(path, config.CLAIMS_PREFIX + path.name)


def main():
    """Command-line entry point."""
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="claim files to upload (default: sample_data)")
    ap.add_argument("--list", action="store_true", help="list objects in the bucket")
    args = ap.parse_args()

    store = DocumentStore()
    mode = "MOCK (local folder)" if store.mock else f"s3://{store.bucket}"
    print(f"Storage: {mode}\n")

    if args.list:
        for k in store.list_keys():
            print("  ", k)
        return

    if args.files:
        for f in args.files:
            print("uploaded", upload_claim(store, Path(f)))
        return

    for f in sorted((config.SAMPLE_DIR / "claims").glob("*")):
        print("uploaded", upload_claim(store, f))
    for f in sorted((config.SAMPLE_DIR / "policies").glob("*")):
        print("uploaded", store.upload_file(f, config.POLICIES_PREFIX + f.name))


if __name__ == "__main__":
    main()
