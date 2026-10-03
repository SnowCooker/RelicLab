"""Budget boundaries, fail-closed counters, immutable reports, and omissions."""

import json
from typing import Any, cast

import pytest
from pydantic import ValidationError
from reliclab.compose import BudgetReport, ComposeRequest, TokenCount, Utf8ByteCounter, compose
from reliclab.resolve import resolve
from reliclab.resolve.types import canonical_json
from reliclab.schema import RelicError

from tests.support.budget import CharacterCounter, budget_graph
from tests.support.resolve import catalog, composition
from tests.support.vault import asset


def request(budget: int = 8000) -> ComposeRequest:
    return ComposeRequest(selected_memory_ids=("first", "last"), token_budget=budget)


def test_exact_budget_and_one_unit_over_remove_last_optional_block() -> None:
    graph = budget_graph()
    full = compose(graph, request())
    total = full.budget_report.input_tokens
    assert compose(graph, request(total)).blocks == full.blocks
    trimmed = compose(graph, request(total - 1))
    assert [block.source_key.id for block in trimmed.blocks] == [
        "editor",
        "review",
        "first",
        "always",
    ]
    report = trimmed.budget_report
    assert report.input_tokens == total
    assert report.retained_tokens == total - len("Last.\n")
    assert report.omissions[0].block_id == "memory:last@1.0.0"
    assert report.omissions[0].source.key == full.blocks[-1].source_key
    assert report.omissions[0].source.content_hash == full.blocks[-1].source_hash
    assert report.omissions[0].original_order == 4
    assert trimmed.manifest == full.manifest
    assert trimmed.tools == full.tools
    assert trimmed.digest != full.digest
    assert trimmed.diagnostics[0].severity == "warning"
    assert trimmed.diagnostics[0].source == "memory/last@1.0.0.md"
    assert "Last." not in trimmed.diagnostics[0].message


def test_required_boundary_keeps_tools_and_all_required_blocks() -> None:
    graph = budget_graph()
    full = compose(graph, request())
    minimum = full.budget_report.required_tokens
    trimmed = compose(graph, request(minimum))
    assert [block.source_key.id for block in trimmed.blocks] == ["editor", "review", "always"]
    assert [block.order for block in trimmed.blocks] == [0, 1, 3]
    assert [item.source.key.id for item in trimmed.budget_report.omissions] == ["last", "first"]
    assert len(trimmed.tools) == 1
    tool_cost = len(canonical_json(full.tools[0].requirement.model_dump(mode="json")).encode())
    assert tool_cost == trimmed.budget_report.tool_tokens > 0
    assert minimum == sum(len(block.text.encode()) for block in trimmed.blocks) + tool_cost
    assert trimmed.budget_report.retained_tokens == minimum
    with pytest.raises(RelicError) as failure:
        compose(graph, request(minimum - 1))
    assert failure.value.code == "CONTEXT_OVERFLOW"
    assert str(minimum) in failure.value.message
    assert failure.value.details[0].location == ("token_budget",)


@pytest.mark.parametrize("budget", [0, -1, True, 1.5, "8", 1000001])
def test_invalid_budgets_are_rejected(budget: Any) -> None:
    with pytest.raises(ValidationError):
        ComposeRequest(token_budget=budget)


def test_unselected_memory_is_not_counted_and_external_notes_are_not_read() -> None:
    graph = resolve(
        composition(memory=["local", "external"]),
        catalog(
            asset("memory", id="local", body="Secret notes."),
            asset("memory", id="external", source="file", root="notes", path="missing.md", body=""),
        ),
    )
    counter = CharacterCounter()
    result = compose(
        graph, ComposeRequest(counter_id=counter.counter_id, token_budget=1), counter=counter
    )
    assert counter.seen == []
    assert result.blocks == ()
    assert result.budget_report.input_tokens == result.budget_report.retained_tokens == 0
    assert result.budget_report.estimated is True
    assert result.budget_report.omissions == ()
    assert len(result.manifest.sources) == 2


@pytest.mark.parametrize("text", ["", "ASCII", "\u4e2d\u6587", "\U0001f680", "e\u0301", "\n\t"])
def test_offline_estimate_is_utf8_bytes_never_exact_tokens(text: str) -> None:
    counted = Utf8ByteCounter().count(text)
    assert counted.value == len(text.encode("utf-8"))
    assert counted.exact is False
    assert counted.counter_id == "utf8-bytes-v1"


def test_injected_counter_counts_each_candidate_and_tool_once() -> None:
    graph = budget_graph()
    counter = CharacterCounter()
    result = compose(
        graph,
        ComposeRequest(
            selected_memory_ids=("first", "last"),
            counter_id=counter.counter_id,
        ),
        counter=counter,
    )
    assert counter.seen == [block.text for block in result.blocks] + [
        canonical_json(result.tools[0].requirement.model_dump(mode="json"))
    ]
    report = result.budget_report
    assert not report.estimated
    assert report.counter_id == result.manifest.counter_id == counter.counter_id
    assert report.input_tokens == sum(map(len, counter.seen))
    assert all(item.count.exact for item in report.block_counts + report.tool_counts)
    counter.seen.clear()
    trimmed = compose(
        graph,
        ComposeRequest(
            selected_memory_ids=("first", "last"),
            counter_id=counter.counter_id,
            token_budget=report.required_tokens,
        ),
        counter=counter,
    )
    assert len(counter.seen) == 6
    assert len(trimmed.budget_report.omissions) == 2


def test_any_estimated_measurement_marks_entire_report_estimated() -> None:
    class MixedCounter(CharacterCounter):
        def count(self, text: str) -> TokenCount:
            counted = super().count(text)
            return counted.model_copy(update={"exact": text != "Last.\n"})

    counter = MixedCounter()
    graph = budget_graph()
    minimum = compose(graph, request()).budget_report.required_tokens
    result = compose(
        graph,
        ComposeRequest(
            selected_memory_ids=("first", "last"),
            counter_id=counter.counter_id,
            token_budget=minimum,
        ),
        counter=counter,
    )
    assert result.budget_report.estimated
    assert len(result.budget_report.omissions) == 2
    assert not result.budget_report.block_counts[-1].count.exact


@pytest.mark.parametrize("counter_id", ["unmeasured", "unregistered-v1", "test-codepoints-v1"])
def test_counter_identity_never_silently_falls_back(counter_id: str) -> None:
    with pytest.raises(RelicError, match="unavailable or mismatched") as failure:
        compose(budget_graph(), ComposeRequest(counter_id=counter_id))
    assert failure.value.code == "SCHEMA_INVALID"


@pytest.mark.parametrize("value", [-1, True, 1.5, "2", 2**63])
def test_forged_token_values_fail_closed(value: Any) -> None:
    class BrokenCounter(CharacterCounter):
        def count(self, text: str) -> TokenCount:
            return TokenCount.model_construct(value=value, exact=True, counter_id=self.counter_id)

    counter = BrokenCounter()
    with pytest.raises(RelicError, match="invalid measurement"):
        compose(budget_graph(), ComposeRequest(counter_id=counter.counter_id), counter=counter)


@pytest.mark.parametrize("failure_kind", ["type", "exception", "id", "changed-id", "precision"])
def test_counter_errors_are_redacted_without_retry(failure_kind: str) -> None:
    class BrokenCounter(CharacterCounter):
        def count(self, text: str) -> TokenCount:
            self.seen.append(text)
            if failure_kind == "exception":
                raise RuntimeError("secret source text")
            if failure_kind == "type":
                return cast(TokenCount, {"value": 0, "exact": True, "counter_id": self.counter_id})
            if failure_kind == "changed-id":
                self.counter_id = "changed"
            return TokenCount.model_construct(
                value=0,
                exact="true" if failure_kind == "precision" else True,
                counter_id="other" if failure_kind == "id" else self.counter_id,
            )

    counter = BrokenCounter()
    with pytest.raises(RelicError) as failure:
        compose(budget_graph(), ComposeRequest(counter_id=counter.counter_id), counter=counter)
    assert failure.value.code == "SCHEMA_INVALID"
    assert "secret" not in str(failure.value)
    assert len(counter.seen) == 1


def test_unavailable_counter_identity_is_redacted() -> None:
    class BrokenIdentity:
        @property
        def counter_id(self) -> str:
            raise RuntimeError("secret configuration")

        def count(self, text: str) -> TokenCount:
            pytest.fail("Unavailable counter must not be called")

    with pytest.raises(RelicError, match="unavailable") as failure:
        compose(budget_graph(), counter=BrokenIdentity())
    assert "secret" not in str(failure.value)


def test_optional_only_content_can_be_completely_removed() -> None:
    graph = resolve(composition(memory=["sample"]), catalog(asset("memory", body="Long notes.\n")))
    result = compose(graph, ComposeRequest(selected_memory_ids=("sample",), token_budget=1))
    assert result.blocks == ()
    assert result.budget_report.retained_tokens == result.budget_report.required_tokens == 0
    assert result.budget_report.omissions[0].tokens == len("Long notes.\n")


def test_zero_cost_optional_blocks_do_not_break_reverse_removal() -> None:
    class ZeroLastCounter(CharacterCounter):
        def count(self, text: str) -> TokenCount:
            return TokenCount(
                value=0 if text == "Last.\n" else len(text), exact=True, counter_id=self.counter_id
            )

    graph = budget_graph()
    minimum = compose(graph, request()).budget_report.required_tokens
    counter = ZeroLastCounter()
    result = compose(
        graph,
        ComposeRequest(
            selected_memory_ids=("first", "last"),
            token_budget=minimum,
            counter_id=counter.counter_id,
        ),
        counter=counter,
    )
    assert [item.tokens for item in result.budget_report.omissions] == [0, 7]
    assert result.budget_report.retained_tokens == minimum


@pytest.mark.parametrize(
    "field",
    [
        "input_tokens",
        "retained_tokens",
        "required_tokens",
        "tool_tokens",
        "estimated",
        "counter_id",
        "token_budget",
    ],
)
def test_report_rejects_inconsistent_totals_and_precision(field: str) -> None:
    report = compose(budget_graph(), request()).budget_report
    payload = report.model_dump()
    payload[field] = {"estimated": False, "counter_id": "other", "token_budget": 1}.get(field, 0)
    with pytest.raises(ValidationError):
        BudgetReport.model_validate(payload)


@pytest.mark.parametrize(
    "kind",
    ["duplicate-block", "duplicate-tool", "duplicate-omission", "required", "unknown", "tokens"],
)
def test_report_rejects_invalid_measurement_and_omission_links(kind: str) -> None:
    graph = budget_graph()
    minimum = compose(graph, request()).budget_report.required_tokens
    payload = compose(graph, request(minimum)).budget_report.model_dump(mode="json")
    if kind.startswith("duplicate"):
        field = {
            "duplicate-block": "block_counts",
            "duplicate-tool": "tool_counts",
            "duplicate-omission": "omissions",
        }[kind]
        payload[field].append(payload[field][0])
    elif kind == "required":
        payload["omissions"][0]["block_id"] = payload["block_counts"][0]["block_id"]
    elif kind == "unknown":
        payload["omissions"][0]["block_id"] = "unknown"
    else:
        payload["omissions"][0]["tokens"] += 1
    with pytest.raises(ValidationError):
        BudgetReport.model_validate_json(json.dumps(payload))
