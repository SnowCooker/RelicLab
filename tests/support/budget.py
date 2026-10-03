"""Small deterministic budgeting graphs and a host-owned test counter."""

from reliclab.compose import TokenCount
from reliclab.resolve import ResolvedGraph, resolve

from tests.support.resolve import catalog, composition
from tests.support.vault import asset


class CharacterCounter:
    """Exact codepoint counts for tests, not a real model tokenizer."""

    counter_id = "test-codepoints-v1"

    def __init__(self, *, exact: bool = True) -> None:
        self.exact = exact
        self.seen: list[str] = []

    def count(self, text: str) -> TokenCount:
        self.seen.append(text)
        return TokenCount(value=len(text), exact=self.exact, counter_id=self.counter_id)


def budget_graph() -> ResolvedGraph:
    return resolve(
        composition(persona="editor", skills=["review"], memory=["first", "always", "last"]),
        catalog(
            asset(id="editor"),
            asset(
                "skill",
                id="review",
                body="Work.\n",
                tools=[
                    {
                        "name": "read",
                        "input_schema": {"type": "object"},
                        "description": "Read files",
                    }
                ],
            ),
            asset("memory", id="first", body="First.\n"),
            asset("memory", id="always", scope="always", body="Always.\n"),
            asset("memory", id="last", body="Last.\n"),
        ),
    )
