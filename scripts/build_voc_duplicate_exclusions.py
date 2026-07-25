from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

from dataset_factory.core.files import sha256
from voc_factory.generator import normalized_text


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, mode="rt", encoding="utf-8")
    return path.open(mode="r", encoding="utf-8")


def build_exclusions(manifest_path: Path, output_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data_path = manifest_path.parent / manifest["data_file"]
    generation_path = manifest_path.parent / manifest["generation_file"]
    if sha256(data_path) != manifest["data_sha256"]:
        raise ValueError("data 파일 hash가 manifest와 다릅니다.")
    if sha256(generation_path) != manifest["generation_sha256"]:
        raise ValueError("generation 파일 hash가 manifest와 다릅니다.")

    first_by_text: dict[str, tuple[int, str]] = {}
    excluded = []
    with _open_text(data_path) as handle:
        for sequence_no, line in enumerate(handle, start=1):
            document = json.loads(line)
            key = normalized_text(document["raw_text"])
            first = first_by_text.get(key)
            if first is None:
                first_by_text[key] = (sequence_no, document["voc_id"])
                continue
            excluded.append(
                {
                    "sequence_no": sequence_no,
                    "voc_id": document["voc_id"],
                    "duplicate_of_sequence_no": first[0],
                    "duplicate_of_voc_id": first[1],
                    "raw_text": document["raw_text"],
                }
            )

    audit = {
        "version": "2026-07-25.2",
        "reason": "normalized_text_duplicate",
        "keep_policy": "lowest_sequence_no",
        "data_sha256": manifest["data_sha256"],
        "generation_sha256": manifest["generation_sha256"],
        "excluded_count": len(excluded),
        "excluded": excluded,
    }
    output_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(
        description="VoC manifest에 결속된 normalized-text 중복 제외 감사 파일 생성"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    result = build_exclusions(args.manifest, args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
