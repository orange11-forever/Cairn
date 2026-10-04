from uuid import uuid4

import pytest
from cairn_api.errors import ApiProblem
from cairn_api.knowledge.content_service import (
    ContentObservation,
    _highlight,  # pyright: ignore[reportPrivateUsage]
)


def test_empty_citation_is_rejected_even_if_a_future_storage_path_bypasses_database_constraint() -> (
    None
):
    observation = ContentObservation(
        uuid4(),
        uuid4(),
        "Synthetic",
        "text/plain",
        3,
        "0" * 64,
        "synthetic-fixture",
        uuid4(),
        "",
        1,
        1,
    )
    with pytest.raises(ApiProblem) as caught:
        _highlight(observation, "hit")
    assert caught.value.status_code == 404
    assert caught.value.code == "not_found"
