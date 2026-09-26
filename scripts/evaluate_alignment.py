"""Deterministic V1 validation smoke evaluation; no model or network calls."""

import json

from backend.quality import hypothesis_failures
from backend.tools import citation_view


def main():
    hypotheses = [
        ("Test whether workers prefer a 12-volt prototype.", True),
        ("Test whether a 170°F prototype heats a 6-cup meal within 30 minutes.", True),
        ("Test whether sales grow 50% next quarter.", False),
        ("Test whether buyers will pay $80.", False),
        ("Test whether proven demand increases sales.", False),
        ("Test whether sales are established before launch.", False),
    ]
    outcomes = []
    for index, (text, expected) in enumerate(hypotheses):
        accepted = not hypothesis_failures(
            f"hypotheses[{index}]",
            {"text": text, "validation_step": "Run a controlled future test."},
        )
        outcomes.append(accepted == expected)

    snippet = (
        "A complete sentence remains. [...] omitted material.\n"
        "[4:15] incomplete transcript fragment for\n"
        "| Battery | 8,000mAh | 14,000mAh |"
    )
    excerpts = citation_view({"id": "S1", "title": "Test", "snippet": snippet})["excerpts"]
    outcomes.append([item["text"] for item in excerpts] == ["A complete sentence remains."])

    result = {
        "cases": len(outcomes),
        "passed": sum(outcomes),
        "failed": len(outcomes) - sum(outcomes),
    }
    print(json.dumps(result))
    if not all(outcomes):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
