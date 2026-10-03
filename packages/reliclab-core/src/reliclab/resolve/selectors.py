"""The deliberately small reference selector language, using semver precedence."""

from semver import Version


def matches(selector: str, version: str) -> bool:
    """Match already schema-validated strings; exact versions include build identity."""
    candidate = Version.parse(version)
    if selector and not selector.startswith("^") and selector.count(".") >= 2:
        return selector == version
    if selector.startswith("^"):
        lower = Version.parse(selector[1:])
        if lower.major:
            upper = Version(lower.major + 1, 0, 0)
        elif lower.minor:
            upper = Version(0, lower.minor + 1, 0)
        else:
            upper = Version(0, 0, lower.patch + 1)
        if candidate.prerelease and (
            not lower.prerelease or candidate.to_tuple()[:3] != lower.to_tuple()[:3]
        ):
            return False
        return lower <= candidate < upper
    if candidate.prerelease:
        return False
    if not selector:
        return True
    components = tuple(selector.split("."))
    return tuple(str(item) for item in candidate.to_tuple()[: len(components)]) == components
