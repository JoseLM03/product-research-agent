import asyncio
import time
from fastapi.testclient import TestClient
from sqlalchemy import select
from backend.db import Job
from backend.worker import run_job
from .helpers import ModelFixture, SearchFixture


def create(client):
    return client.post('/api/research',json={'idea':'compact coffee grinder'})


def test_api_to_worker_to_persisted_report(client,app):
    result=create(client)
    assert result.status_code==202
    job_id=result.json()['id']
    with app.state.sessions.begin() as db:
        job=db.get(Job,job_id);job.status='running';job.started_at=time.time()
    asyncio.run(run_job(job_id,app.state.sessions,app.state.settings,ModelFixture(),SearchFixture()))
    result=client.get('/api/research/'+job_id).json()
    assert result['status']=='completed'
    assert result['report']['sources'][0]['id']=='S1'
    assert result['events'][-1]['tool']=='submit_report'
    assert len(client.get('/api/research').json())==1
    assert client.request('DELETE','/api/research/'+job_id,json={}).status_code==200
    assert client.get('/api/research/'+job_id).status_code==404


def test_other_browser_cannot_read_or_delete_history(client,app):
    job_id=create(client).json()['id']
    # Same app, separate cookie jar. Avoid a second lifespan/worker.
    other=TestClient(app)
    other.headers['origin']='http://testserver'
    other.get('/api/session')
    assert other.get('/api/research').json()==[]
    assert other.get('/api/research/'+job_id).status_code==404
    assert other.request('DELETE','/api/research/'+job_id,json={}).status_code==404
    other.close()


def test_csrf_input_limits_and_security_headers(client):
    assert client.post('/api/research',json={'idea':'grinder'},headers={'origin':'https://evil.example'}).status_code==403
    assert client.post('/api/research',json={'idea':'   '}).status_code==422
    assert client.post('/api/research',json={'idea':'x'*10000}).status_code==413
    client.cookies.clear()
    response=client.get('/api/session')
    assert response.headers['cache-control']=='no-store'
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert 'samesite=strict' in response.headers['set-cookie'].lower()


def test_concurrent_job_prevention_and_daily_budget(client,app):
    first=create(client)
    assert first.status_code==202
    assert create(client).status_code==409
    with app.state.sessions.begin() as db:
        db.get(Job,first.json()['id']).status='failed'
    app.state.settings.daily_global_limit=1
    assert create(client).status_code==429
    assert client.request('DELETE','/api/research/'+first.json()['id'],json={}).status_code==200
    assert create(client).status_code==429  # Deletion does not refund abuse quota.


def test_missing_configuration_fails_closed(client,app):
    app.state.settings.research_enabled=False
    assert create(client).status_code==503


def test_forged_session_has_no_access(client):
    job_id=create(client).json()['id']
    client.cookies.clear()
    client.cookies.set('fieldwork_session','forged')
    assert client.get('/api/research/'+job_id).status_code==401


def test_worker_provider_failure_is_persisted(client,app):
    from backend.providers import ProviderError
    class Broken:
        async def chat(self,*args): raise ProviderError('Model unavailable.')
    job_id=create(client).json()['id']
    with app.state.sessions.begin() as db: db.get(Job,job_id).status='running'
    asyncio.run(run_job(job_id,app.state.sessions,app.state.settings,Broken(),SearchFixture()))
    detail=client.get('/api/research/'+job_id).json()
    assert detail['status']=='failed'
    assert detail['report'] is None
    assert detail['error']=='Model unavailable.'
