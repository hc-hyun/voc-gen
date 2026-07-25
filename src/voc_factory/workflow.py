from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import shutil
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Iterator, TextIO

from .generator import (
    GENERATOR_VERSION,
    PROMPT_VERSION,
    GenerationProfile,
    canonical_json,
    generate_prepared_record,
    generator_sha256,
    prepare_generation,
    spec_digest,
)
from .quality import inspect_records
from dataset_factory.core.files import sha256

from .source import load_scenarios

APPROVAL_PHRASE = "검수완료"


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl_line(handle: TextIO, value: dict) -> None:
    handle.write(canonical_json(value))
    handle.write("\n")


@contextlib.contextmanager
def _open_text(path: Path, mode: str) -> Iterator[TextIO]:
    if "b" in mode:
        raise ValueError("_open_text는 텍스트 모드만 지원합니다.")
    if path.suffix != ".gz":
        with path.open(mode, encoding="utf-8", newline="\n") as handle:
            yield handle
        return

    binary_mode = "wb" if "w" in mode else "rb"
    with path.open(binary_mode) as raw:
        if "w" in mode:
            compressed = gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0)
        else:
            compressed = gzip.GzipFile(fileobj=raw, mode="rb")
        with compressed:
            with io.TextIOWrapper(compressed, encoding="utf-8", newline="\n") as handle:
                yield handle


def _sidecar_path(output_path: Path) -> Path:
    name = output_path.name
    if name.endswith(".jsonl.gz"):
        return output_path.with_name(name[:-9] + ".generation.jsonl.gz")
    if name.endswith(".jsonl"):
        return output_path.with_name(name[:-6] + ".generation.jsonl")
    raise ValueError("출력 파일은 .jsonl 또는 .jsonl.gz 확장자를 사용해야 합니다.")


def _manifest_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".manifest.json")


def _checkpoint_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".checkpoint.json")


def _failure_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".failures.jsonl")


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    _write_json(temporary, value)
    temporary.replace(path)


def _asset_hashes(profile: GenerationProfile) -> dict[str, str]:
    return {
        "phrase_bank": sha256(profile.phrase_bank_path),
    }


def build_review(
    profile: GenerationProfile,
    output_dir: Path,
    sample_size: int,
    review_split: str = "TRAIN",
) -> Path:
    if sample_size < 200:
        raise ValueError("검수 샘플은 최소 200건이어야 합니다.")
    if review_split not in {"TRAIN", "VALID", "TEST", "ALL"}:
        raise ValueError("review_split은 TRAIN, VALID, TEST, ALL 중 하나여야 합니다.")
    output_dir.mkdir(parents=True, exist_ok=True)
    context = prepare_generation(profile)
    records = []
    for sequence_no in range(1, profile.target_count + 1):
        record = generate_prepared_record(context, sequence_no)
        if (
            review_split == "ALL"
            or record[0]["dataset_split"] == review_split
        ):
            records.append(record)
            if len(records) == sample_size:
                break
    if len(records) < sample_size:
        raise ValueError(
            f"{review_split} split에서 요청한 {sample_size:,}건 중 "
            f"{len(records):,}건만 선택할 수 있습니다."
        )
    scenarios = load_scenarios(profile.source_path)
    quality = inspect_records(records, profile, scenarios)

    sample_path = output_dir / "sample.jsonl"
    generation_path = output_dir / "sample.generation.jsonl"
    with sample_path.open("w", encoding="utf-8", newline="\n") as data_handle, generation_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as generation_handle:
        for document, generation in records:
            _write_jsonl_line(data_handle, document)
            _write_jsonl_line(generation_handle, generation)

    digest = spec_digest(profile)
    local_llm_plan = context.local_llm_plan.as_dict()
    review_id = hashlib.sha256(
        (
            f"{digest}:{canonical_json(local_llm_plan)}:"
            f"{review_split}:{len(records)}"
        ).encode("utf-8")
    ).hexdigest()[:20]
    review = {
        "review_id": review_id,
        "status": "PENDING_MANUAL_REVIEW",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator_version": GENERATOR_VERSION,
        "generator_sha256": generator_sha256(),
        "prompt_version": PROMPT_VERSION,
        "spec_digest": digest,
        "profile": profile.as_dict(),
        "review_split": review_split,
        "source_sha256": sha256(profile.source_path),
        "schema_sha256": sha256(profile.schema_path),
        "asset_sha256": _asset_hashes(profile),
        "local_llm_plan": local_llm_plan,
        "sample": {
            "data_file": sample_path.name,
            "generation_file": generation_path.name,
            "rows": len(records),
            "data_sha256": sha256(sample_path),
            "generation_sha256": sha256(generation_path),
        },
        "quality": quality,
    }
    review_path = output_dir / "review.json"
    _write_json(review_path, review)
    (output_dir / "REVIEW.md").write_text(
        _render_review_markdown(review),
        encoding="utf-8",
    )
    return review_path


def _render_review_markdown(review: dict) -> str:
    profile = review["profile"]
    quality = review["quality"]
    check_lines = "\n".join(
        f"- [{'x' if check['passed'] else ' '}] `{check['name']}`: "
        f"{check['actual']} (기준: {check['expected']})"
        for check in quality["checks"]
    )
    distribution_sections = []
    for name, counts in quality["distributions"].items():
        values = ", ".join(f"`{key}` {value:,}" for key, value in counts.items())
        distribution_sections.append(f"- {name}: {values}")
    distributions = "\n".join(distribution_sections)
    return f"""# VoC 생성 사전 검수

이 문서는 대량 데이터를 아직 만들지 않은 상태의 자동 검사 및 사람 검수 자료입니다.

## 생성 사양

- 검수 ID: `{review['review_id']}`
- 프로필: `{profile['profile_name']}`
- 최종 예정 건수: `{profile['target_count']:,}`
- 부모 시나리오: `scenario_bank_500.csv` 500개
- 다중 이슈 목표: `{profile['multi_issue_rate']:.0%}`
- 시드: `{profile['seed']}`
- 생성기 버전: `{review['generator_version']}`
- 사양 SHA-256: `{review['spec_digest']}`
- 검수 샘플: `{review['sample']['rows']:,}`건 (`sample.jsonl`)
- 검수 대상 split: `{review['review_split']}`
- 로컬 LLM 적용 계획: `{review['local_llm_plan']['resolved_mode']}`
  (`{review['local_llm_plan']['sample_rate']:.2%}`, 예상 추가
  `{review['local_llm_plan']['estimated_extra_seconds'] / 3600:.2f}`시간)

## 자동 품질 검사

전체 결과: **{'통과' if quality['passed'] else '실패'}**

{check_lines}

## 표본 분포

{distributions}

## 사람이 확인할 항목

- [ ] 원문이 각 `issues[]` 정답 라벨을 실제로 지지하는가
- [ ] 다중 이슈가 서로 구분되고 같은 split·제품군에 속하는가
- [ ] B0/P1/A1/N1 표현이 채널과 언어에 자연스러운가
- [ ] 원인 추정을 확정 진단처럼 표현하지 않았는가
- [ ] S4·안전 이슈의 의미가 약화되지 않았는가
- [ ] 실제 개인정보나 구체적인 개인 식별 정보가 없는가

검수 완료 후 다음 명령으로 승인 파일을 만드세요.

```powershell
uv run voc-factory approve --review "{Path('reviews') / profile['profile_name'] / 'review.json'}" --reviewer "검수자 이름" --confirm "{APPROVAL_PHRASE}"
```

승인 전에는 10만/100만 건 전체 생성이 실행되지 않습니다.
"""


def create_approval(
    review_path: Path,
    reviewer: str,
    confirmation: str,
) -> Path:
    if confirmation != APPROVAL_PHRASE:
        raise ValueError(f'승인 문구는 정확히 "{APPROVAL_PHRASE}"여야 합니다.')
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if not review["quality"]["passed"]:
        raise ValueError("자동 품질 검사가 실패한 검수 건은 승인할 수 없습니다.")
    sample = review["sample"]
    data_path = review_path.parent / sample["data_file"]
    generation_path = review_path.parent / sample["generation_file"]
    if (
        sha256(data_path) != sample["data_sha256"]
        or sha256(generation_path) != sample["generation_sha256"]
    ):
        raise ValueError("검수 샘플이 생성 후 변경되었습니다. 검수를 다시 만드세요.")
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("검수자 이름을 입력해야 합니다.")
    approval = {
        "status": "APPROVED",
        "review_id": review["review_id"],
        "reviewer": reviewer,
        "approved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator_version": review["generator_version"],
        "spec_digest": review["spec_digest"],
        "sample_data_sha256": sample["data_sha256"],
        "sample_generation_sha256": sample["generation_sha256"],
    }
    approval_path = review_path.parent / "approval.json"
    _write_json(approval_path, approval)
    return approval_path


def validate_approval(
    profile: GenerationProfile,
    review_path: Path,
    approval_path: Path,
) -> tuple[dict, dict]:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    expected_digest = spec_digest(profile)
    errors = []
    if approval.get("status") != "APPROVED":
        errors.append("승인 상태가 APPROVED가 아닙니다.")
    if review.get("review_id") != approval.get("review_id"):
        errors.append("검수 ID와 승인 ID가 다릅니다.")
    if review.get("spec_digest") != expected_digest:
        errors.append("현재 프로필이 검수받은 사양과 다릅니다.")
    if approval.get("spec_digest") != expected_digest:
        errors.append("현재 프로필이 승인받은 사양과 다릅니다.")
    if review.get("generator_version") != GENERATOR_VERSION:
        errors.append("검수 이후 생성기 버전이 변경되었습니다.")
    sample = review["sample"]
    data_path = review_path.parent / sample["data_file"]
    generation_path = review_path.parent / sample["generation_file"]
    if (
        not data_path.exists()
        or sha256(data_path) != approval.get("sample_data_sha256")
        or not generation_path.exists()
        or sha256(generation_path) != approval.get("sample_generation_sha256")
    ):
        errors.append("승인받은 검수 샘플을 확인할 수 없거나 변경되었습니다.")
    if errors:
        raise ValueError(" ".join(errors))
    return review, approval


def validate_review(
    profile: GenerationProfile,
    review_path: Path,
) -> dict:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    errors = []
    if not review.get("quality", {}).get("passed"):
        errors.append("자동 품질 검사를 통과하지 않은 review입니다.")
    if review.get("spec_digest") != spec_digest(profile):
        errors.append("현재 profile과 review 사양 해시가 다릅니다.")
    if review.get("generator_version") != GENERATOR_VERSION:
        errors.append("review 이후 생성기 버전이 변경되었습니다.")
    sample = review.get("sample", {})
    data_path = review_path.parent / sample.get("data_file", "")
    generation_path = review_path.parent / sample.get("generation_file", "")
    if (
        not data_path.exists()
        or sha256(data_path) != sample.get("data_sha256")
        or not generation_path.exists()
        or sha256(generation_path) != sample.get("generation_sha256")
    ):
        errors.append("review sample이 없거나 변경되었습니다.")
    if errors:
        raise ValueError(" ".join(errors))
    return review


def generate_approved_dataset(
    profile: GenerationProfile,
    review_path: Path,
    approval_path: Path | None,
    output_path: Path,
    *,
    candidate: bool = False,
    resume: bool = False,
    chunk_size: int = 10_000,
    max_attempts: int = 3,
) -> Path:
    if candidate:
        if approval_path is not None:
            raise ValueError("candidate 생성에는 approval 파일을 사용하지 않습니다.")
        review = validate_review(profile, review_path)
        approval = None
    else:
        if approval_path is None:
            raise ValueError("승인 생성에는 approval 파일이 필요합니다.")
        review, approval = validate_approval(profile, review_path, approval_path)
    if chunk_size < 1:
        raise ValueError("chunk_size는 1 이상이어야 합니다.")
    if max_attempts < 1:
        raise ValueError("max_attempts는 1 이상이어야 합니다.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    generation_path = _sidecar_path(output_path)
    manifest_path = _manifest_path(output_path)
    checkpoint_path = _checkpoint_path(output_path)
    failure_path = _failure_path(output_path)
    work_dir = output_path.with_name(output_path.name + ".work")
    work_checkpoint = work_dir / "checkpoint.json"

    if resume and manifest_path.exists():
        verify_manifest(manifest_path, approval_path)
        return manifest_path
    if not resume and any(
        path.exists()
        for path in (output_path, generation_path, manifest_path, work_dir)
    ):
        raise FileExistsError(
            "기존 생성 파일 또는 작업 폴더가 있습니다. 이어서 실행하려면 --resume을 사용하세요."
        )

    digest = spec_digest(profile)
    local_llm_plan = review["local_llm_plan"]
    if work_checkpoint.exists():
        if not resume:
            raise FileExistsError("기존 checkpoint가 있습니다. --resume을 사용하세요.")
        checkpoint = json.loads(work_checkpoint.read_text(encoding="utf-8"))
        if (
            checkpoint.get("spec_digest") != digest
            or checkpoint.get("target_count") != profile.target_count
            or checkpoint.get("chunk_size") != chunk_size
            or checkpoint.get("local_llm_plan") != local_llm_plan
        ):
            raise ValueError("checkpoint의 사양 또는 chunk_size가 현재 실행과 다릅니다.")
    else:
        work_dir.mkdir(parents=True, exist_ok=True)
        checkpoint = {
            "status": "IN_PROGRESS",
            "spec_digest": digest,
            "target_count": profile.target_count,
            "chunk_size": chunk_size,
            "local_llm_plan": local_llm_plan,
            "completed_chunks": [],
        }
        _write_json_atomic(work_checkpoint, checkpoint)

    completed = {
        chunk["chunk_index"]: chunk for chunk in checkpoint["completed_chunks"]
    }
    context = prepare_generation(profile, local_llm_plan)
    chunk_count = (profile.target_count + chunk_size - 1) // chunk_size
    for chunk_index in range(chunk_count):
        start = chunk_index * chunk_size + 1
        end = min(profile.target_count, start + chunk_size - 1)
        data_part = work_dir / f"data-{chunk_index:06d}.jsonl.gz"
        generation_part = work_dir / f"generation-{chunk_index:06d}.jsonl.gz"
        previous = completed.get(chunk_index)
        if previous is not None:
            if (
                not data_part.exists()
                or not generation_part.exists()
                or sha256(data_part) != previous["data_sha256"]
                or sha256(generation_part)
                != previous["generation_sha256"]
            ):
                raise ValueError(f"완료된 chunk {chunk_index} 파일이 없거나 변경되었습니다.")
            continue

        data_temp = data_part.with_name(data_part.stem + ".tmp.gz")
        generation_temp = generation_part.with_name(
            generation_part.stem + ".tmp.gz"
        )
        try:
            with _open_text(data_temp, "w") as data_handle, _open_text(
                generation_temp, "w"
            ) as generation_handle:
                for sequence_no in range(start, end + 1):
                    last_error: Exception | None = None
                    for attempt in range(1, max_attempts + 1):
                        try:
                            document, generation = generate_prepared_record(
                                context,
                                sequence_no,
                            )
                            generation["attempt_number"] = attempt
                            _write_jsonl_line(data_handle, document)
                            _write_jsonl_line(generation_handle, generation)
                            last_error = None
                            break
                        except Exception as exc:
                            last_error = exc
                    if last_error is not None:
                        with failure_path.open(
                            "a",
                            encoding="utf-8",
                            newline="\n",
                        ) as failure_handle:
                            _write_jsonl_line(
                                failure_handle,
                                {
                                    "sequence_no": sequence_no,
                                    "attempts": max_attempts,
                                    "error_type": type(last_error).__name__,
                                    "error": str(last_error),
                                },
                            )
                        raise RuntimeError(
                            f"{sequence_no}번 생성이 {max_attempts}회 모두 실패했습니다."
                        ) from last_error
            data_temp.replace(data_part)
            generation_temp.replace(generation_part)
        finally:
            for temporary in (data_temp, generation_temp):
                if temporary.exists():
                    temporary.unlink()

        chunk_info = {
            "chunk_index": chunk_index,
            "start_sequence": start,
            "end_sequence": end,
            "row_count": end - start + 1,
            "data_file": data_part.name,
            "data_sha256": sha256(data_part),
            "generation_file": generation_part.name,
            "generation_sha256": sha256(generation_part),
        }
        checkpoint["completed_chunks"].append(chunk_info)
        completed[chunk_index] = chunk_info
        _write_json_atomic(work_checkpoint, checkpoint)

    data_output_temp = output_path.with_name(output_path.name + ".tmp")
    generation_output_temp = generation_path.with_name(generation_path.name + ".tmp")
    with data_output_temp.open("wb") as data_output, generation_output_temp.open(
        "wb"
    ) as generation_output:
        for chunk_index in range(chunk_count):
            with (work_dir / f"data-{chunk_index:06d}.jsonl.gz").open("rb") as part:
                shutil.copyfileobj(part, data_output, length=1024 * 1024)
            with (
                work_dir / f"generation-{chunk_index:06d}.jsonl.gz"
            ).open("rb") as part:
                shutil.copyfileobj(part, generation_output, length=1024 * 1024)
    data_output_temp.replace(output_path)
    generation_output_temp.replace(generation_path)
    if not failure_path.exists():
        failure_path.write_text("", encoding="utf-8")

    checkpoint["status"] = "COMPLETE"
    checkpoint["completed_at"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    _write_json_atomic(checkpoint_path, checkpoint)
    shutil.rmtree(work_dir)
    row_count = sum(chunk["row_count"] for chunk in checkpoint["completed_chunks"])

    manifest = {
        "status": (
            "CANDIDATE_NOT_HUMAN_APPROVED"
            if candidate
            else "GENERATED_NOT_VALIDATED"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator_version": GENERATOR_VERSION,
        "generator_sha256": generator_sha256(),
        "prompt_version": PROMPT_VERSION,
        "profile": profile.as_dict(),
        "spec_digest": spec_digest(profile),
        "source_sha256": sha256(profile.source_path),
        "schema_sha256": sha256(profile.schema_path),
        "asset_sha256": _asset_hashes(profile),
        "local_llm_plan": local_llm_plan,
        "review_id": review["review_id"],
        "approved_by": approval["reviewer"] if approval else None,
        "human_approval_status": "NOT_APPROVED" if candidate else "APPROVED",
        "data_file": output_path.name,
        "data_sha256": sha256(output_path),
        "generation_file": generation_path.name,
        "generation_sha256": sha256(generation_path),
        "checkpoint_file": checkpoint_path.name,
        "checkpoint_sha256": sha256(checkpoint_path),
        "failure_file": failure_path.name,
        "failure_sha256": sha256(failure_path),
        "failure_count": sum(
            1
            for line in failure_path.read_text(encoding="utf-8").splitlines()
            if line
        ),
        "chunk_size": chunk_size,
        "chunk_count": chunk_count,
        "max_attempts": max_attempts,
        "row_count": row_count,
    }
    _write_json_atomic(manifest_path, manifest)
    return manifest_path


def verify_manifest(
    manifest_path: Path,
    approval_path: Path | None = None,
) -> tuple[dict, Path, Path]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data_path = manifest_path.parent / manifest["data_file"]
    generation_path = manifest_path.parent / manifest["generation_file"]
    errors = []
    if approval_path is not None:
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
        if manifest.get("review_id") != approval.get("review_id"):
            errors.append("데이터와 승인 파일의 검수 ID가 다릅니다.")
        if manifest.get("spec_digest") != approval.get("spec_digest"):
            errors.append("데이터와 승인 파일의 사양 해시가 다릅니다.")
    for path, key, label in (
        (data_path, "data_sha256", "데이터"),
        (generation_path, "generation_sha256", "generation sidecar"),
        (
            manifest_path.parent / manifest.get("checkpoint_file", ""),
            "checkpoint_sha256",
            "checkpoint",
        ),
        (
            manifest_path.parent / manifest.get("failure_file", ""),
            "failure_sha256",
            "failure log",
        ),
    ):
        if not manifest.get(key):
            errors.append(f"{label} 해시가 manifest에 없습니다.")
            continue
        if not path.exists():
            errors.append(f"{label} 파일이 없습니다.")
        elif sha256(path) != manifest.get(key):
            errors.append(f"{label} 파일 해시가 manifest와 다릅니다.")
    if errors:
        raise ValueError(" ".join(errors))
    return manifest, data_path, generation_path


def promote_candidate(
    profile: GenerationProfile,
    review_path: Path,
    approval_path: Path,
    manifest_path: Path,
) -> Path:
    review, approval = validate_approval(profile, review_path, approval_path)
    manifest, _, _ = verify_manifest(manifest_path)
    errors = []
    if manifest.get("status") != "CANDIDATE_NOT_HUMAN_APPROVED":
        errors.append("manifest가 승인 전 candidate 상태가 아닙니다.")
    if manifest.get("spec_digest") != spec_digest(profile):
        errors.append("candidate와 현재 profile 사양이 다릅니다.")
    if manifest.get("review_id") != review.get("review_id"):
        errors.append("candidate와 승인 review ID가 다릅니다.")
    if errors:
        raise ValueError(" ".join(errors))
    manifest["status"] = "GENERATED_NOT_VALIDATED"
    manifest["human_approval_status"] = "APPROVED"
    manifest["approved_by"] = approval["reviewer"]
    manifest["approved_at"] = approval["approved_at"]
    _write_json_atomic(manifest_path, manifest)
    return manifest_path


def validate_dataset(
    profile: GenerationProfile,
    manifest_path: Path,
    approval_path: Path | None = None,
) -> dict:
    manifest, data_path, generation_path = verify_manifest(
        manifest_path,
        approval_path,
    )
    name = data_path.name
    base_name = (
        name[:-9]
        if name.endswith(".jsonl.gz")
        else name[:-6]
        if name.endswith(".jsonl")
        else name
    )
    validation_results_path = data_path.with_name(
        base_name + ".validation_results.jsonl.gz"
    )
    quarantine_path = data_path.with_name(base_name + ".quarantine.jsonl.gz")
    stats_path = data_path.with_name(base_name + ".dataset_stats.json")

    def records() -> Iterator[tuple[dict, dict]]:
        with _open_text(data_path, "r") as data_handle, _open_text(
            generation_path, "r"
        ) as generation_handle:
            for line_no, (data_line, generation_line) in enumerate(
                zip_longest(data_handle, generation_handle),
                start=1,
            ):
                if data_line is None or generation_line is None:
                    raise ValueError(f"{line_no}행에서 본문과 sidecar 건수가 다릅니다.")
                yield json.loads(data_line), json.loads(generation_line)

    with _open_text(validation_results_path, "w") as result_handle, _open_text(
        quarantine_path,
        "w",
    ) as quarantine_handle:
        quality = inspect_records(
            records(),
            profile,
            load_scenarios(profile.source_path),
            result_handle=result_handle,
            quarantine_handle=quarantine_handle,
        )
    quality["manifest_row_count"] = manifest["row_count"]
    quality["row_count_matches_manifest"] = (
        quality["sample_count"] == manifest["row_count"] == profile.target_count
    )
    quality["passed"] = quality["passed"] and quality["row_count_matches_manifest"]
    quality["artifacts"] = {
        "validation_results_file": validation_results_path.name,
        "validation_results_sha256": sha256(validation_results_path),
        "quarantine_file": quarantine_path.name,
        "quarantine_sha256": sha256(quarantine_path),
    }
    _write_json(stats_path, quality)
    quality["artifacts"]["dataset_stats_file"] = stats_path.name
    quality["artifacts"]["dataset_stats_sha256"] = sha256(stats_path)
    validation_path = manifest_path.with_name(manifest_path.name + ".validation.json")
    _write_json(validation_path, quality)
    return {
        "validation": validation_path,
        "validation_results": validation_results_path,
        "quarantine": quarantine_path,
        "dataset_stats": stats_path,
        "quality": quality,
    }
