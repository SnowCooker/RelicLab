"""Public selector fixtures define reference semantics independently of private docs."""

import json
from pathlib import Path

import pytest
from reliclab.resolve import ResolutionError, resolve

from tests.support.resolve import catalog, composition
from tests.support.vault import asset

CASES = json.loads((Path(__file__).parents[1] / "fixtures/resolve/selectors.json").read_text())


@pytest.mark.parametrize("case", CASES)
def test_selector_contract(case: dict[str, object]) -> None:
    versions = case["versions"]
    reference = case["reference"]
    assert isinstance(versions, list) and isinstance(reference, str)
    source = catalog(*(asset("skill", version=version) for version in versions))
    request = composition(skills=[reference])
    if "error" in case:
        with pytest.raises(ResolutionError) as caught:
            resolve(request, source)
        assert caught.value.code == case["error"]
        assert caught.value.chain == ("composition:workflow@1.0.0", f"skill:{reference}")
    else:
        graph = resolve(request, source)
        assert graph.skills[0].key.version == case["selected"]
        assert resolve(request, source, lock=graph.lock) == graph
