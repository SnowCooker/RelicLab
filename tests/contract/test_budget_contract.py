"""Public budget serialization and monotonic whole-block retention contracts."""

import json

from hypothesis import given, settings
from hypothesis import strategies as st
from reliclab.compose import ComposeRequest, ContextData, compose
from reliclab.schema import RelicError

from tests.support.budget import CharacterCounter, budget_graph


@settings(max_examples=60, derandomize=True, database=None, deadline=None)
@given(st.lists(st.integers(min_value=1, max_value=250), min_size=2, max_size=10, unique=True))
def test_larger_budgets_never_remove_previously_retained_blocks(budgets: list[int]) -> None:
    graph = budget_graph()
    previous: set[str] = set()
    for budget in sorted(budgets):
        request = ComposeRequest(token_budget=budget, selected_memory_ids=("first", "last"))
        try:
            result = compose(graph, request)
        except RelicError as error:
            assert error.code == "CONTEXT_OVERFLOW"
            assert not previous
            continue
        retained = {block.block_id for block in result.blocks}
        assert previous <= retained
        assert result.budget_report.retained_tokens <= budget
        assert compose(graph, request).to_json() == result.to_json()
        previous = retained


def test_estimate_survives_shared_dto_and_json_boundary() -> None:
    graph = budget_graph()
    full = compose(graph, ComposeRequest(selected_memory_ids=("first", "last")))
    result = compose(
        graph,
        ComposeRequest(
            token_budget=full.budget_report.required_tokens,
            selected_memory_ids=("first", "last"),
        ),
    )
    envelope = json.loads(result.to_json())
    envelope.pop("digest")
    decoded = ContextData.model_validate_json(json.dumps(envelope))
    assert decoded.budget_report == result.budget_report
    assert decoded.budget_report.estimated is True
    assert decoded.budget_report.counting_scope == "core-content-v1"
    assert len(decoded.budget_report.omissions) == 2
    assert len(decoded.tools) == 1
    assert decoded.manifest.selected_memory_ids == ("first", "last")
    assert len(decoded.manifest.sources) == 5


def test_counter_version_and_precision_affect_digest() -> None:
    graph = budget_graph()
    counter = CharacterCounter()
    request = ComposeRequest(counter_id=counter.counter_id)
    exact = compose(graph, request, counter=counter)
    estimated = compose(graph, request, counter=CharacterCounter(exact=False))
    assert exact.blocks == estimated.blocks
    assert exact.digest != estimated.digest
    counter.counter_id = "test-codepoints-v2"
    versioned = compose(graph, ComposeRequest(counter_id=counter.counter_id), counter=counter)
    assert versioned.blocks == exact.blocks
    assert versioned.digest != exact.digest
