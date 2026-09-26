"""Explicit synthetic provider fixtures. Never imported by production code."""

FACT_QUOTE = "Fixture Grinder A has replaceable burrs, a manual handle, and a steel housing and is advertised at $80.00."


class SearchFixture:
    async def search(self, query):
        return [
            {
                "title": "Fixture Grinder A",
                "url": "https://example.com/grinder-a",
                "description": FACT_QUOTE
                + "\nFixture Grinder A uses replaceable burrs.\nFixture Grinder A has a manual handle.\nFixture Grinder A has a steel housing.",
            },
            {
                "title": "Fixture Grinder B",
                "url": "https://example.org/grinder-b",
                "description": "Fixture Grinder B has a compact housing for small kitchens.",
            },
        ]


def draft(source="S1", quote=FACT_QUOTE):
    def claim(text):
        return {"text": text, "citations": [{"source_id": source, "quote": quote}]}

    return {
        "overview": claim("The listing describes Fixture Grinder A."),
        "observations": [claim("The listing describes a manual handle.")],
        "competitors": [claim("The listing describes a steel housing on Fixture Grinder A.")],
        "opportunities": [],
        "risks": [],
        "assessment": "mixed_signals",
        "rationale": claim("The listing advertises replaceable burrs."),
        "limitations": ["Synthetic test evidence only."],
    }


def call(name, arguments):
    if name == "submit_report":
        import copy

        arguments = copy.deepcopy(arguments)
        # Convert the resolved fixture to the native submission contract.
        arguments.pop("limitations", None)
        for index, claim in enumerate(
            [
                arguments["overview"],
                arguments["rationale"],
                *arguments["observations"],
                *arguments["competitors"],
            ],
            1,
        ):
            claim.pop("text", None)
            if "citations" not in claim:
                continue
            citation = claim.pop("citations")[0]
            if "quote" in citation:
                quote = citation.pop("quote")
                citation["excerpt"] = index if quote == FACT_QUOTE else 99
            claim["citation"] = citation
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
        if tools[0]["function"]["name"] == "alignment_verdicts":
            import json

            items = json.loads(messages[-1]["content"])
            return call(
                "alignment_verdicts",
                {
                    "results": [
                        {"id": item["id"], "supported": True, "reason": "ok"} for item in items
                    ]
                },
            )
        self.messages.append(list(messages))
        return self.responses.pop(0)
