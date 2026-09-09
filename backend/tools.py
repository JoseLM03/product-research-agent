import html
import ipaddress
import re
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit
from .schemas import SearchArgs, EvidenceArgs, NoArgs, ReportDraft


def safe_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.lower()
        if host == 'localhost' or host.endswith(('.local', '.localhost', '.internal')) or '.' not in host:
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except (TypeError, ValueError):
        return False


def plain(value, limit):
    return html.unescape(re.sub(r'<[^>]*>', '', str(value)))[:limit].strip()


def margin(costs):
    if costs is None:
        return {'error': 'No user-supplied cost scenario. Do not estimate margins.'}
    fee = costs.sale_price * costs.fee_percent / Decimal(100)
    contribution = costs.sale_price - costs.unit_cost - costs.shipping - costs.other_costs - fee
    money = lambda x: str(x.quantize(Decimal('.01'), rounding=ROUND_HALF_UP))
    return {'currency': costs.currency, 'inputs': costs.model_dump(mode='json'),
            'fees': money(fee), 'contribution_per_unit': money(contribution),
            'contribution_margin_percent': money(contribution / costs.sale_price * 100),
            'basis': 'User-supplied scenario; not a forecast. Excludes any taxes, returns, acquisition costs, and overhead not included in your inputs.'}


SPECS = {
    'search_web': (SearchArgs, 'Search the web for market context. Results are snippets, not verified facts or full pages.'),
    'search_competitors': (SearchArgs, 'Search for competing products and retail listings using a product-specific query.'),
    'inspect_evidence': (EvidenceArgs, 'Retrieve a previously collected source snippet and its provenance by ID. Does not fetch a webpage.'),
    'calculate_margin': (NoArgs, 'Calculate contribution margin using ONLY the original user-supplied costs. No invented inputs.'),
    'submit_report': (ReportDraft, 'Submit the final structured report with exact supporting quotes from collected snippets. Claims require citations. Opportunities and risks are hypotheses with validation steps.'),
}


def definitions():
    return [{'type': 'function', 'function': {'name': name, 'description': description,
             'parameters': schema.model_json_schema()}} for name, (schema, description) in SPECS.items()]


class ResearchTools:
    def __init__(self, search, costs=None):
        self.search, self.costs = search, costs
        self.sources = {}
        self.calculation = None
        self.failures = []

    async def execute(self, name, args):
        if name in ('search_web', 'search_competitors'):
            query = args.query + (' competing products retail price' if name == 'search_competitors' else '')
            rows = await self.search.search(query)
            found = []
            for row in rows:
                if not isinstance(row, dict) or not safe_url(row.get('url')):
                    continue
                url = row['url'][:2048]
                snippet = plain(row.get('description', ''), 1800)
                if not snippet:
                    continue
                existing = next((s for s in self.sources.values() if s['url'] == url), None)
                if existing:
                    found.append(existing)
                    continue
                if len(self.sources) >= 25:
                    break
                source_id = f'S{len(self.sources) + 1}'
                source = {'id': source_id, 'title': plain(row.get('title', url), 250), 'url': url,
                          'snippet': snippet, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
                          'query': query, 'kind': 'search_snippet'}
                self.sources[source_id] = source
                found.append(source)
            return {'sources': found, 'limitation': 'Search snippets may be outdated or incomplete. No sales volume or demand is established.'}
        if name == 'inspect_evidence':
            if args.source_id not in self.sources:
                raise ValueError('Unknown source ID')
            return self.sources[args.source_id]
        if name == 'calculate_margin':
            self.calculation = margin(self.costs)
            return self.calculation
        raise ValueError('Unknown tool')

    def validate_report(self, report):
        if not self.sources:
            raise ValueError('No retrieved evidence. Search before submitting a report.')
        for claim in [report.overview, report.rationale, *report.observations, *report.competitors]:
            for citation in claim.citations:
                source = self.sources.get(citation.source_id)
                if not source or citation.quote not in source['snippet']:
                    raise ValueError('Every citation must reference a collected source and quote an exact substring of its snippet.')
        data = report.model_dump(mode='json')
        data['sources'] = list(self.sources.values())
        data['calculation'] = self.calculation
        # Numerical observations are extracted without letting the model invent a price.
        data['price_mentions'] = [{'source_id': s['id'], 'text': match.group(0)} for s in self.sources.values()
            for match in re.finditer(r'(?:USD|EUR|GBP|CAD|AUD|[$€£])\s?\d[\d,]*(?:\.\d{1,2})?', s['snippet'])][:30]
        data['limitations'] += ['Evidence is limited to search snippets; citations are validated for existence, not semantic correctness.',
                                 'Price mentions may refer to shipping, accessories, or old offers. Verify listings before relying on them.']
        data['limitations'] += self.failures
        data['data_quality'] = 'limited'
        data['assessment'] = report.assessment if len(self.sources) >= 2 else 'insufficient_evidence'
        return data
