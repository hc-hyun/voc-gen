from __future__ import annotations

import contextlib
import gzip
import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path
from typing import Iterator, TextIO

from .contracts import GeneratedArtifact
from .files import sha256
from .profiles import DatasetProfile
from .registry import get_adapter


APPROVAL_PHRASE = "검수완료"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    _write_json(temporary, value)
    temporary.replace(path)


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
            with io.TextIOWrapper(
                compressed,
                encoding="utf-8",
                newline="\n",
            ) as handle:
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


def _progress_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".progress.json")


def _temporary_output_path(path: Path) -> Path:
    if path.suffix == ".gz":
        return path.with_name(path.name[:-3] + ".tmp.gz")
    return path.with_name(path.name + ".tmp")


def _validation_result_path(output_path: Path) -> Path:
    name = output_path.name
    if name.endswith(".jsonl.gz"):
        return output_path.with_name(name[:-9] + ".validation_results.jsonl.gz")
    return output_path.with_name(name[:-6] + ".validation_results.jsonl")


def _quarantine_path(output_path: Path) -> Path:
    name = output_path.name
    if name.endswith(".jsonl.gz"):
        return output_path.with_name(name[:-9] + ".quarantine.jsonl.gz")
    return output_path.with_name(name[:-6] + ".quarantine.jsonl")


def spec_digest(profile: DatasetProfile) -> str:
    adapter = get_adapter(profile.dataset_type)
    value = {
        "profile": profile.as_dict(),
        "dataset_type": profile.dataset_type,
        "generator_version": adapter.generator_version,
        "prompt_version": adapter.prompt_version,
        "generator_sha256": adapter.generator_sha256(),
        "assets": adapter.asset_hashes(profile),
    }
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _render_review_markdown(review: dict, checklist: list[str]) -> str:
    quality = review["quality"]
    check_lines = "\n".join(
        f"- [{'x' if check['passed'] else ' '}] `{check['name']}`: "
        f"{check['actual']} (기준: {check['expected']})"
        for check in quality["checks"]
    )
    distribution_lines = []
    for name, counts in quality["distributions"].items():
        values = ", ".join(f"`{key}` {value:,}" for key, value in counts.items())
        distribution_lines.append(f"- {name}: {values or '없음'}")
    human_lines = "\n".join(f"- [ ] {item}" for item in checklist)
    profile = review["profile"]
    return f"""# {review['dataset_type']} 생성 사전 검수

대량 생성 전에 자동 검사와 사람 검수를 수행하기 위한 자료입니다.

## 생성 사양

- 검수 ID: `{review['review_id']}`
- 데이터 유형: `{review['dataset_type']}`
- 프로필: `{profile['profile_name']}`
- 최종 예정 건수: `{profile['target_count']:,}`
- 시드: `{profile['seed']}`
- 생성기 버전: `{review['generator_version']}`
- 사양 SHA-256: `{review['spec_digest']}`
- 검수 샘플: `{review['sample']['rows']:,}`건
- 검수 대상 split: `{review['review_split']}`

## 자동 품질 검사

전체 결과: **{'통과' if quality['passed'] else '실패'}**

{check_lines}

## 표본 분포

{chr(10).join(distribution_lines)}

## 사람이 확인할 항목

{human_lines}

검수 완료 후 다음 명령으로 승인 파일을 만드세요.

```bash
uv run dataset-factory approve --review "{review['review_file_hint']}" \\
  --reviewer "검수자 이름" --confirm "{APPROVAL_PHRASE}"
```
"""


def build_review(
    profile: DatasetProfile,
    output_dir: Path,
    sample_size: int,
    review_split: str = "TRAIN",
) -> Path:
    adapter = get_adapter(profile.dataset_type)
    if sample_size < adapter.min_review_sample_size:
        raise ValueError(
            f"{profile.dataset_type} 검수 샘플은 최소 "
            f"{adapter.min_review_sample_size}건이어야 합니다."
        )
    if review_split not in {"TRAIN", "VALID", "TEST", "ALL"}:
        raise ValueError("review_split은 TRAIN, VALID, TEST, ALL 중 하나여야 합니다.")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    context = adapter.prepare(profile)
    artifacts: list[GeneratedArtifact] = []
    for sequence_no in range(1, profile.target_count + 1):
        artifact = adapter.generate(context, sequence_no)
        if review_split == "ALL" or artifact.dataset_split == review_split:
            artifacts.append(artifact)
            if len(artifacts) == sample_size:
                break
    if len(artifacts) < sample_size:
        raise ValueError(
            f"{review_split} split에서 요청한 {sample_size:,}건 중 "
            f"{len(artifacts):,}건만 선택할 수 있습니다."
        )
    quality = adapter.inspect(iter(artifacts), profile)
    sample_path = output_dir / "sample.jsonl"
    generation_path = output_dir / "sample.generation.jsonl"
    with sample_path.open("w", encoding="utf-8", newline="\n") as data_handle, (
        generation_path.open("w", encoding="utf-8", newline="\n")
    ) as generation_handle:
        for artifact in artifacts:
            _write_jsonl_line(data_handle, artifact.document)
            _write_jsonl_line(generation_handle, artifact.generation)

    digest = spec_digest(profile)
    plan = adapter.generation_plan(context)
    review_id = hashlib.sha256(
        (
            f"{digest}:{canonical_json(plan)}:{review_split}:"
            f"{len(artifacts)}"
        ).encode("utf-8")
    ).hexdigest()[:20]
    review_path = output_dir / "review.json"
    try:
        review_hint = str(review_path.relative_to(profile.project_dir))
    except ValueError:
        review_hint = str(review_path)
    review = {
        "review_id": review_id,
        "status": "PENDING_MANUAL_REVIEW",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_type": profile.dataset_type,
        "generator_version": adapter.generator_version,
        "generator_sha256": adapter.generator_sha256(),
        "prompt_version": adapter.prompt_version,
        "spec_digest": digest,
        "profile": profile.as_dict(),
        "review_split": review_split,
        "asset_sha256": adapter.asset_hashes(profile),
        "generation_plan": plan,
        "sample": {
            "data_file": sample_path.name,
            "generation_file": generation_path.name,
            "rows": len(artifacts),
            "data_sha256": sha256(sample_path),
            "generation_sha256": sha256(generation_path),
        },
        "quality": quality,
        "review_file_hint": review_hint,
    }
    _write_json(review_path, review)
    (output_dir / "REVIEW.md").write_text(
        _render_review_markdown(review, adapter.review_checklist()),
        encoding="utf-8",
    )
    return review_path


def write_text_sample(
    profile: DatasetProfile,
    output_path: Path,
    count: int,
) -> Path:
    if count < 1 or count > profile.target_count:
        raise ValueError(
            f"sample count는 1~{profile.target_count} 사이여야 합니다."
        )
    adapter = get_adapter(profile.dataset_type)
    context = adapter.prepare(profile)
    lines = []
    for sequence_no in range(1, count + 1):
        artifact = adapter.generate(context, sequence_no)
        text = re.sub(r"\s+", " ", adapter.sample_text(artifact)).strip()
        if not text:
            raise ValueError(f"{sequence_no}번 sample text가 비어 있습니다.")
        lines.append(text)
    if len(lines) != len(set(lines)):
        raise ValueError("sample text에 완전히 같은 행이 있습니다.")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def _load_and_validate_review(
    profile: DatasetProfile,
    review_path: Path,
) -> dict:
    review = json.loads(Path(review_path).read_text(encoding="utf-8"))
    if review.get("dataset_type") != profile.dataset_type:
        raise ValueError("검수의 dataset_type이 현재 profile과 다릅니다.")
    if review.get("spec_digest") != spec_digest(profile):
        raise ValueError("검수 후 profile, source, schema 또는 생성기가 변경되었습니다.")
    sample = review["sample"]
    data_path = Path(review_path).parent / sample["data_file"]
    generation_path = Path(review_path).parent / sample["generation_file"]
    if (
        sha256(data_path) != sample["data_sha256"]
        or sha256(generation_path) != sample["generation_sha256"]
    ):
        raise ValueError("검수 샘플이 생성 후 변경되었습니다.")
    if not review["quality"]["passed"]:
        raise ValueError("자동 품질 검사가 실패한 검수는 사용할 수 없습니다.")
    return review


def create_approval(
    review_path: Path,
    reviewer: str,
    confirmation: str,
) -> Path:
    if confirmation != APPROVAL_PHRASE:
        raise ValueError(f'승인 문구는 정확히 "{APPROVAL_PHRASE}"여야 합니다.')
    review_path = Path(review_path)
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
        raise ValueError("검수 샘플이 생성 후 변경되었습니다.")
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError("검수자 이름을 입력해야 합니다.")
    approval = {
        "status": "APPROVED",
        "dataset_type": review["dataset_type"],
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


def _validate_approval(review: dict, approval_path: Path) -> dict:
    approval = json.loads(Path(approval_path).read_text(encoding="utf-8"))
    errors = []
    for field in ("dataset_type", "review_id", "generator_version", "spec_digest"):
        if approval.get(field) != review.get(field):
            errors.append(field)
    sample = review["sample"]
    if approval.get("sample_data_sha256") != sample["data_sha256"]:
        errors.append("sample_data_sha256")
    if approval.get("sample_generation_sha256") != sample["generation_sha256"]:
        errors.append("sample_generation_sha256")
    if approval.get("status") != "APPROVED":
        errors.append("status")
    if errors:
        raise ValueError(f"승인 파일이 현재 검수와 일치하지 않습니다: {errors}")
    return approval


def generate_dataset(
    profile: DatasetProfile,
    review_path: Path,
    output_path: Path,
    approval_path: Path | None = None,
) -> Path:
    review = _load_and_validate_review(profile, Path(review_path))
    approval = (
        _validate_approval(review, Path(approval_path))
        if approval_path is not None
        else None
    )
    adapter = get_adapter(profile.dataset_type)
    context = adapter.prepare(profile, review["generation_plan"])
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path = _sidecar_path(output_path)
    temporary_data = _temporary_output_path(output_path)
    temporary_sidecar = _temporary_output_path(sidecar_path)
    progress_path = _progress_path(output_path)
    started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    progress = {
        "state": "GENERATING_AND_VALIDATING",
        "pid": os.getpid(),
        "dataset_type": profile.dataset_type,
        "profile_name": profile.profile_name,
        "target_count": profile.target_count,
        "completed_count": 0,
        "started_at": started_at,
        "updated_at": started_at,
        "output": str(output_path),
    }
    _write_json_atomic(progress_path, progress)

    def generated_and_written():
        with _open_text(temporary_data, "wt") as data_handle, _open_text(
            temporary_sidecar, "wt"
        ) as generation_handle:
            for sequence_no in range(1, profile.target_count + 1):
                artifact = adapter.generate(context, sequence_no)
                _write_jsonl_line(data_handle, artifact.document)
                _write_jsonl_line(generation_handle, artifact.generation)
                if sequence_no % 1_000 == 0 or sequence_no == profile.target_count:
                    progress["completed_count"] = sequence_no
                    progress["updated_at"] = datetime.now(timezone.utc).isoformat(
                        timespec="seconds"
                    )
                    _write_json_atomic(progress_path, progress)
                yield artifact

    try:
        quality = adapter.inspect(generated_and_written(), profile)
        if not quality["passed"]:
            raise ValueError(f"생성 데이터 품질 검사 실패: {quality['error_examples'][:3]}")
        temporary_data.replace(output_path)
        temporary_sidecar.replace(sidecar_path)
    except Exception as exc:
        for path in (temporary_data, temporary_sidecar):
            if path.exists():
                path.unlink()
        progress["state"] = "FAILED"
        progress["error"] = f"{type(exc).__name__}: {exc}"
        progress["updated_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        _write_json_atomic(progress_path, progress)
        raise

    progress["state"] = "COMPLETE"
    progress["completed_count"] = quality["sample_count"]
    progress["updated_at"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    progress["quality_passed"] = quality["passed"]
    _write_json_atomic(progress_path, progress)

    manifest = {
        "status": (
            "APPROVED_DATASET"
            if approval is not None
            else "CANDIDATE_NOT_HUMAN_APPROVED"
        ),
        "dataset_type": profile.dataset_type,
        "profile_name": profile.profile_name,
        "target_count": profile.target_count,
        "record_count": quality["sample_count"],
        "review_id": review["review_id"],
        "human_approval_status": "APPROVED" if approval else "NOT_APPROVED",
        "review_file": str(Path(review_path)),
        "approval_file": str(Path(approval_path)) if approval_path else None,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "spec_digest": spec_digest(profile),
        "generator_version": adapter.generator_version,
        "generator_sha256": adapter.generator_sha256(),
        "prompt_version": adapter.prompt_version,
        "generation_plan": adapter.generation_plan(context),
        "asset_sha256": adapter.asset_hashes(profile),
        "data_file": output_path.name,
        "generation_file": sidecar_path.name,
        "data_sha256": sha256(output_path),
        "generation_sha256": sha256(sidecar_path),
        "progress_file": progress_path.name,
        "progress_sha256": sha256(progress_path),
        "quality": quality,
    }
    manifest_path = _manifest_path(output_path)
    _write_json_atomic(manifest_path, manifest)
    return manifest_path


def _read_artifacts(data_path: Path, sidecar_path: Path):
    with _open_text(data_path, "rt") as data_handle, _open_text(
        sidecar_path, "rt"
    ) as generation_handle:
        for line_no, (data_line, generation_line) in enumerate(
            zip_longest(data_handle, generation_handle),
            start=1,
        ):
            if data_line is None or generation_line is None:
                raise ValueError(f"document/sidecar 행 수 불일치: {line_no}행")
            document = json.loads(data_line)
            generation = json.loads(generation_line)
            yield GeneratedArtifact(
                record_id=generation["record_id"],
                dataset_type=generation["dataset_type"],
                dataset_split=generation["dataset_split"],
                lineage_ids=tuple(generation["lineage_ids"]),
                document=document,
                generation=generation,
            )


def validate_dataset(profile: DatasetProfile, manifest_path: Path) -> dict:
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_type") != profile.dataset_type:
        raise ValueError("manifest dataset_type이 현재 profile과 다릅니다.")
    if manifest.get("spec_digest") != spec_digest(profile):
        raise ValueError("manifest 생성 후 profile, source, schema 또는 생성기가 변경되었습니다.")
    data_path = manifest_path.parent / manifest["data_file"]
    sidecar_path = manifest_path.parent / manifest["generation_file"]
    if sha256(data_path) != manifest["data_sha256"]:
        raise ValueError("데이터 파일 hash가 manifest와 다릅니다.")
    if sha256(sidecar_path) != manifest["generation_sha256"]:
        raise ValueError("sidecar 파일 hash가 manifest와 다릅니다.")

    result_path = _validation_result_path(data_path)
    quarantine_path = _quarantine_path(data_path)
    validation_progress_path = manifest_path.with_name(
        manifest_path.name + ".validation.progress.json"
    )
    validation_started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    validation_progress = {
        "state": "REVALIDATING",
        "pid": os.getpid(),
        "dataset_type": profile.dataset_type,
        "profile_name": profile.profile_name,
        "target_count": manifest["record_count"],
        "completed_count": 0,
        "started_at": validation_started_at,
        "updated_at": validation_started_at,
        "manifest": str(manifest_path),
    }
    _write_json_atomic(validation_progress_path, validation_progress)

    def tracked_artifacts():
        for count, artifact in enumerate(
            _read_artifacts(data_path, sidecar_path),
            start=1,
        ):
            if count % 1_000 == 0 or count == manifest["record_count"]:
                validation_progress["completed_count"] = count
                validation_progress["updated_at"] = datetime.now(
                    timezone.utc
                ).isoformat(timespec="seconds")
                _write_json_atomic(
                    validation_progress_path,
                    validation_progress,
                )
            yield artifact

    adapter = get_adapter(profile.dataset_type)
    try:
        with _open_text(result_path, "wt") as result_handle, _open_text(
            quarantine_path, "wt"
        ) as quarantine_handle:
            quality = adapter.inspect(
                tracked_artifacts(),
                profile,
                result_handle=result_handle,
                quarantine_handle=quarantine_handle,
            )
    except Exception as exc:
        validation_progress["state"] = "FAILED"
        validation_progress["error"] = f"{type(exc).__name__}: {exc}"
        validation_progress["updated_at"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )
        _write_json_atomic(validation_progress_path, validation_progress)
        raise

    validation_progress["state"] = (
        "COMPLETE" if quality["passed"] else "VALIDATION_FAILED"
    )
    validation_progress["completed_count"] = quality["sample_count"]
    validation_progress["quality_passed"] = quality["passed"]
    validation_progress["updated_at"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )
    _write_json_atomic(validation_progress_path, validation_progress)
    validation = {
        "status": "PASSED" if quality["passed"] else "FAILED",
        "validated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset_type": profile.dataset_type,
        "manifest_file": manifest_path.name,
        "spec_digest": spec_digest(profile),
        "quality": quality,
        "validation_results": result_path.name,
        "validation_results_sha256": sha256(result_path),
        "quarantine": quarantine_path.name,
        "quarantine_sha256": sha256(quarantine_path),
        "validation_progress": validation_progress_path.name,
    }
    validation_path = manifest_path.with_name(manifest_path.name + ".validation.json")
    _write_json_atomic(validation_path, validation)
    return validation
