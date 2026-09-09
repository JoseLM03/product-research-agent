"""Opt-in local inference test; search results are explicit synthetic fixtures.

This verifies real model-driven tool selection, not live market research.
Run: python -m scripts.live_ollama_smoke --model YOUR_LOCAL_MODEL
"""
import argparse
import asyncio
import json
import httpx
from backend.agent import research
from backend.config import Settings
from backend.providers import Ollama
from backend.schemas import ResearchInput
from backend.tools import ResearchTools
from tests.helpers import SearchFixture


async def main(model):
    async def emit(tool,status,detail):
        print(json.dumps({'tool':tool,'status':status,'detail':detail}),flush=True)
    settings=Settings(ollama_model=model)
    async with httpx.AsyncClient(trust_env=False) as client:
        async with asyncio.timeout(300):
            report,status=await research(ResearchInput(idea='Investigate a compact coffee grinder with replaceable burrs. This is a test using synthetic evidence.'),
                Ollama(client,settings),ResearchTools(SearchFixture()),10,emit)
    print(json.dumps({'status':status,'source_count':len(report['sources']),'assessment':report['assessment'],'evidence':'synthetic test fixture; real local model'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True)
    asyncio.run(main(parser.parse_args().model))
