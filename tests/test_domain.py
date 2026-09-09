import asyncio
from decimal import Decimal
import pytest
from pydantic import ValidationError
from backend.schemas import Costs, ResearchInput, ReportDraft, SearchArgs
from backend.tools import ResearchTools, margin, safe_url
from .helpers import SearchFixture, draft


def test_margin_uses_decimal_and_all_costs():
    costs = Costs(currency='USD', sale_price='100', unit_cost='30', shipping='10', other_costs='5', fee_percent='15')
    result = margin(costs)
    assert result['contribution_per_unit'] == '40.00'
    assert result['contribution_margin_percent'] == '40.00'
    assert 'User-supplied' in result['basis']
    assert 'error' in margin(None)


def test_negative_margin_is_not_hidden():
    assert margin(Costs(sale_price=10, unit_cost=20, shipping=0, other_costs=0, fee_percent=0))['contribution_margin_percent'] == '-100.00'


@pytest.mark.parametrize('field,value', [('sale_price', 0), ('unit_cost', -1), ('fee_percent', 101), ('shipping', 'NaN'), ('unit_cost', '1.001')])
def test_invalid_costs(field, value):
    data = dict(sale_price=10, unit_cost=1, shipping=1, other_costs=0, fee_percent=1)
    data[field] = value
    with pytest.raises(ValidationError):
        Costs(**data)


@pytest.mark.parametrize('url', ['javascript:alert(1)', 'file:///etc/passwd', 'http://localhost', 'http://127.0.0.1/x', 'http://169.254.169.254/', 'https://user:pass@example.com', 'https://[::1]/', None])
def test_unsafe_source_links(url):
    assert not safe_url(url)


def test_rejects_blank_idea_and_unknown_fields():
    for payload in [{'idea': '     '}, {'idea': 'coffee grinder', 'owner': 'someone-else'}]:
        with pytest.raises(ValidationError):
            ResearchInput.model_validate(payload)


def test_report_citations_and_prices_are_grounded():
    tools = ResearchTools(SearchFixture())
    asyncio.run(tools.execute('search_web', SearchArgs(query='grinder')))
    report = tools.validate_report(ReportDraft.model_validate(draft()))
    assert report['price_mentions'] == [{'source_id': 'S1', 'text': '$80.00'}]
    assert report['sources'][0]['url'] == 'https://example.com/grinder-a'
    for bad in [draft('S9'), draft(quote='This is an invented source quote.')]:
        with pytest.raises(ValueError):
            tools.validate_report(ReportDraft.model_validate(bad))


def test_empty_evidence_cannot_be_reported_as_success():
    with pytest.raises(ValueError):
        ResearchTools(SearchFixture()).validate_report(ReportDraft.model_validate(draft()))
