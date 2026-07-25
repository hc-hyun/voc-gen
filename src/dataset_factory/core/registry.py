from __future__ import annotations

from .contracts import DatasetTypeAdapter


_ADAPTERS: dict[str, DatasetTypeAdapter] = {}
_BUILTINS_LOADED = False


def register_adapter(adapter: DatasetTypeAdapter) -> None:
    type_id = adapter.type_id.strip()
    if not type_id:
        raise ValueError("adapter type_id는 비어 있을 수 없습니다.")
    existing = _ADAPTERS.get(type_id)
    if existing is not None and existing is not adapter:
        raise ValueError(f"dataset adapter가 이미 등록됨: {type_id}")
    _ADAPTERS[type_id] = adapter


def _load_builtins() -> None:
    global _BUILTINS_LOADED
    if _BUILTINS_LOADED:
        return
    from dataset_factory.types.internal_dev_test.adapter import ADAPTER as internal
    from dataset_factory.types.voc.adapter import ADAPTER as voc

    register_adapter(voc)
    register_adapter(internal)
    _BUILTINS_LOADED = True


def get_adapter(type_id: str) -> DatasetTypeAdapter:
    _load_builtins()
    try:
        return _ADAPTERS[type_id]
    except KeyError as error:
        raise ValueError(
            f"등록되지 않은 dataset_type: {type_id!r}; "
            f"사용 가능: {sorted(_ADAPTERS)}"
        ) from error


def registered_types() -> tuple[str, ...]:
    _load_builtins()
    return tuple(sorted(_ADAPTERS))
