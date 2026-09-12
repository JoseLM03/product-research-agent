"""Explicit synthetic provider fixtures. Never imported by production code."""


class SearchFixture:
    async def search(self, query):
        return [
            {
                "title": "Fixture Grinder A",
                "url": "https://example.com/grinder-a",
                "description": "Fixture Grinder A has replaceable burrs and is advertised at $80.00.",
            },
            {
                "title": "Fixture Grinder B",
                "url": "https://example.org/grinder-b",
                "description": "Fixture Grinder B has a compact housing for small kitchens.",
            },
        ]


def draft(source="S1", quote="Fixture Grinder A has replaceable burrs"):
    claim = {
        "text": "The fixture listing advertises replaceable burrs.",
        "citations": [{"source_id": source, "quote": quote}],
    }
    return {
        "overview": claim,
        "observations": [claim],
        "competitors": [claim],
        "opportunities": [],
        "risks": [],
        "assessment": "mixed_signals",
        "rationale": claim,
        "limitations": ["Synthetic test evidence only."],
    }


def call(name, arguments):
    if name == "submit_report":
        import copy

        arguments = copy.deepcopy(arguments)
        for claim in [
            arguments["overview"],
            arguments["rationale"],
            *arguments["observations"],
            *arguments["competitors"],
        ]:
            for citation in claim["citations"]:
                if "quote" in citation:
                    quote = citation.pop("quote")
                    citation["excerpt"] = (
                        1 if quote == "Fixture Grinder A has replaceable burrs" else 99
                    )
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
    }


class ModelFixture:
    def __init__(self, responses=None):
        self.responses = responses or [
            call("search_competitors", {"query": "compact coffee grinder"}),
            call("calculate_margin", {}),
            call("submit_report", draft()),
        ]
        self.messages = []

    async def chat(self, messages, tools):
        self.messages.append(list(messages))
        return self.responses.pop(0)
