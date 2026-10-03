"""Fixed composition inputs for public golden and regression tests."""

from typing import Any

from reliclab.resolve import ResolvedGraph, resolve

from tests.support.resolve import catalog, composition
from tests.support.vault import asset


def golden_graph(mode: str) -> ResolvedGraph:
    source = catalog(
        asset(id="parent", identity="Unused parent", values=["Accuracy"], body="Base rule.\n"),
        asset(
            id="editor",
            identity="Editor for {{ project }}",
            extends="parent",
            voice="Concise",
            values=["Accuracy", "Clarity"],
            constraints=["Review before executing."],
            body="Explain the patch.\n",
        ),
        asset(
            "skill",
            id="review",
            trigger="When {{ project }} changes",
            body="Review \u4e2d\u6587 and English.\n",
            examples=[{"input": "{{ project }}", "output": "Checked."}],
            tools=[
                {"name": "read", "input_schema": {"type": "object"}, "description": "Read files"}
            ],
        ),
        asset("memory", id="notes", scope="always", body="Literal {{ project }}.\n"),
    )
    slots: dict[str, dict[str, Any]] = {
        "persona": {"persona": "editor"},
        "skill": {"skills": ["review"]},
        "memory": {"memory": ["notes"]},
        "combined": {"persona": "editor", "skills": ["review"], "memory": ["notes"]},
    }
    return resolve(composition(**slots[mode]), source)
