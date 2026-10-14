"""Regression tests: mock providers; disposable database and Redis only."""
import asyncio
import json
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock, patch
import httpx
from sqlalchemy import text
from core.config import settings
assert settings.database_url.endswith('/sports_matter_release_audit_test')
assert settings.redis_url.endswith('/14')
from core.task_runtime import run_async
from core.database import init_database, get_db_session
from core.cache import init_cache
from core.external import base
from modules.journals.services.openalex_client import OpenAlexClient
from modules.arxiv.services import biorxiv_crawler as bio
from modules.arxiv.services import biorxiv_fallback as fallback
from modules.arxiv.services.arxiv_database import ArxivDatabaseService
from modules.arxiv.services.llm_classifier import ArxivLLMClassifier
from modules.arxiv.tasks import arxiv_tasks as tasks
from modules.arxiv.api.schemas import ArxivArticleResponse

assert tasks.celery_app.conf.broker_url == "memory://", "Tests require an in-memory task broker"

checks=[]
def check(name, condition=True):
    assert condition, name
    checks.append(name)
def raises(kind, call):
    try: call()
    except kind: return True
    return False
def record(doi='10.test/a', version=1):
    return dict(doi=doi,title='Exercise training and strength',abstract='Effects of exercise training on strength in athletes.',authors='Tester A',date='2026-09-23',version=version)
def page(items, total=None, cursor=0):
    return {'messages':[{'status':'ok','total':len(items) if total is None else total,'count':len(items),'cursor':cursor}], 'collection':items}
def response(data=None, status=200, content=None):
    return httpx.Response(status, json=data, content=content, request=httpx.Request('GET','https://api.biorxiv.org/test'))

async def provider_tests():
    cache={}
    async def get(k):return cache.get(k)
    async def set_(k,v,ttl=None):cache[k]=v;return True
    client=OpenAlexClient();client.enable_cache=False
    await client.client.aclose()
    seen=[]
    def handler(req):
        seen.append(req)
        if req.url.path=='/works':return httpx.Response(429,headers={'Retry-After':'59234'})
        if 'missing' in req.url.path:return httpx.Response(404)
        return httpx.Response(200,json={'id':'https://openalex.org/W1','cited_by_count':8})
    client.client=httpx.AsyncClient(base_url='https://api.openalex.org',transport=httpx.MockTransport(handler))
    base._provider_cooldowns.clear()
    with patch.object(base,'cache_get',get),patch.object(base,'cache_set',set_),patch('modules.journals.services.openalex_client.cache_get',get),patch('modules.journals.services.openalex_client.cache_set',set_):
        try:await client.get('/works')
        except base.UpstreamRateLimited:pass
        result=await client.get_work_by_doi('https://doi.org/10.test/a?b#c')
        check('paid search quota does not disable officially free singleton',result['cited_by_count']==8)
        check('DOI reserved characters stay in path',seen[-1].url.query.decode().find('filter')==-1 and '%3F' in str(seen[-1].url) and '%23' in str(seen[-1].url))
        n=len(seen);await client.get_work_by_doi('10.test/missing');await client.get_work_by_doi('10.test/missing')
        check('404 not retried and negative result cached',len(seen)==n+1)
        await client.client.aclose()
        requests=Mock(return_value=httpx.Response(429,headers={'Retry-After':'80000'}))
        client.client=httpx.AsyncClient(base_url='https://api.openalex.org',transport=httpx.MockTransport(requests))
        for _ in range(2):
            try:await client.get_work_by_doi('10.test/limited')
            except base.UpstreamRateLimited:pass
            else:raise AssertionError('singleton 429 must propagate')
        check('singleton 429 honored without repeated requests',requests.call_count==1)
    await client.close();base._provider_cooldowns.clear()


def crawler_tests():
    crawler=bio.BiorxivCrawler(page_delay=0)
    with patch.object(bio.httpx,'get',side_effect=[response(content=b''),response(data=page([record()]))]) as get, patch.object(bio.time,'sleep'):
        items,_=crawler._fetch_page('2026-09-22','2026-09-24',0)
        check('empty 200 retries inside validation',len(items)==1 and get.call_count==2)
    for name,data in [('missing metadata',{'collection':[]}),('premature empty page',page([],total=10)),('API error',{'messages':[{'status':'error'}],'collection':[]})]:
        with patch.object(bio.httpx,'get',return_value=response(data=data)),patch.object(bio.time,'sleep'):
            check(name,raises(bio.BiorxivAPIError,lambda:crawler._fetch_page('a','b',0)))
    with patch.object(bio.httpx,'get',return_value=response(data=page([]))):
        check('valid zero response remains valid',crawler._fetch_page('a','b',0)[0]==[])
    pages=[([record()],{'total':3}),([record(version=2)],{'total':3}),([record('10.test/b')],{'total':3})]
    with patch.object(crawler,'_fetch_page',side_effect=pages),patch.object(bio.time,'sleep'):
        articles=crawler.crawl_date_range(date(2026,9,22),date(2026,9,24))
        check('version-only page does not truncate subsequent articles',len(articles)==2 and articles[0]['version']==2)
    with patch.object(crawler,'_fetch_page',side_effect=[([record()],{'total':3}),([record()],{'total':3})]),patch.object(bio.time,'sleep'):
        check('repeated page is a failure, not false success',raises(bio.BiorxivAPIError,lambda:crawler.crawl_date_range(date(2026,9,22),date(2026,9,24))))
    item={'id':'PPR1','source':'PPR','doi':'10.test/fallback','title':'Exercise','abstractText':'<p>Exercise strength &amp; fitness</p>','firstPublicationDate':'2026-09-23','bookOrReportDetails':{'publisher':'bioRxiv'}}
    data={'hitCount':1,'resultList':{'result':[item]}}
    with patch.object(fallback.httpx,'Client') as cls:
        cls.return_value.__enter__.return_value.get.return_value=response(data=data)
        result=fallback.BiorxivEuropePMCCrawler().crawl_date_range(date(2026,9,22),date(2026,9,24))
        check('fallback keeps unknown version and unversioned link',result[0]['version'] is None and result[0]['abs_url'].endswith('10.test/fallback'))
        check('fallback normalizes abstract markup','<p>' not in result[0]['abstract'] and '&' in result[0]['abstract'])
        item['bookOrReportDetails']['publisher']='medRxiv'
        cls.return_value.__enter__.return_value.get.return_value=response(data=data)
        check('fallback validates actual publisher',raises(bio.BiorxivAPIError,lambda:fallback.BiorxivEuropePMCCrawler().crawl_date_range(date(2026,9,22),date(2026,9,24))))
    check('long outage resumes in bounded batch',tasks.preprint_window(date(2026,9,26),date(2026,9,1))==(date(2026,8,31),date(2026,9,6)))
    check('healthy overlap retained',tasks.preprint_window(date(2026,9,26),date(2026,9,25))==(date(2026,9,23),date(2026,9,26)))
    model=ArxivLLMClassifier(api_key='test',strict=True)
    with patch.object(model.client.chat.completions,'create',side_effect=RuntimeError('down')):
        check('model outage cannot silently reject papers',raises(RuntimeError,lambda:model.judge_relevance('x','y')))
    model.client.close()

async def db_tests():
    await init_database();await init_cache()
    async with get_db_session() as db:
        await db.execute(text('TRUNCATE arxiv_articles, arxiv_crawl_log RESTART IDENTITY CASCADE'));await db.commit()
        service=ArxivDatabaseService(db)
        official=bio.BiorxivCrawler()._parse_record(record(version=3))
        await service.upsert_articles([official])
        incoming={**official,'version':None,'title':'incomplete fallback'}
        await service.upsert_articles([incoming])
        row=(await db.execute(text('SELECT version,title FROM arxiv_articles'))).one()
        check('fallback cannot downgrade known official record',row.version==3 and row.title==official['title'])
        unknown={**official,'arxiv_id':'bxunknown','version':None}
        await service.upsert_articles([unknown])
        check('unknown fallback version stored as SQL NULL',(await db.execute(text("SELECT version FROM arxiv_articles WHERE arxiv_id='bxunknown'"))).scalar() is None)
        await db.execute(text('TRUNCATE arxiv_articles, arxiv_crawl_log RESTART IDENTITY CASCADE'));await db.commit()
        await service.log_crawl_task(task_type='incremental',source='biorxiv',status='success',date_to=date(2026,9,23))
    fallback_article={**bio.BiorxivCrawler()._parse_record(record('10.test/new')),'version':None,'_metadata_provider':'europe_pmc'}
    def classify(items,**kwargs):return [{**a,'sport_relevance':0.9} for a in items]
    with patch.object(tasks.BiorxivCrawler,'crawl_date_range',side_effect=bio.BiorxivAPIError('empty upstream')),patch.object(tasks.BiorxivEuropePMCCrawler,'crawl_date_range',return_value=[fallback_article]),patch.object(tasks.ArxivLLMClassifier,'process_batch',side_effect=classify),patch.object(tasks.BatchTranslator,'translate_titles_for_arxiv',AsyncMock()):
        result=await tasks._biorxiv_incremental()
        check('fallback runs through classification and database',result['status']=='fallback_success' and result['inserted']==1)
    async with get_db_session() as db:
        primary_end=(await db.execute(text("SELECT max(date_to) FROM arxiv_crawl_log WHERE task_type='incremental' AND status='success'"))).scalar()
        check('fallback never advances official checkpoint',primary_end==date(2026,9,23))
        check('failed official attempt remains visible',(await db.execute(text("SELECT count(*) FROM arxiv_crawl_log WHERE task_type='incremental' AND status='failed'"))).scalar()==1)
        from modules.arxiv.models.arxiv_article import ArxivArticle
        from sqlalchemy import select
        row=(await db.execute(select(ArxivArticle))).scalar_one()
        check('API accepts unknown preprint version',ArxivArticleResponse.model_validate(row).version is None)
    with patch.object(tasks.BiorxivCrawler,'crawl_date_range',return_value=[bio.BiorxivCrawler()._parse_record(record('10.test/new',3))]),patch.object(tasks.ArxivLLMClassifier,'process_batch',side_effect=classify),patch.object(tasks.BatchTranslator,'translate_titles_for_arxiv',AsyncMock()):
        result=await tasks._biorxiv_incremental()
        check('official recovery reconciles fallback metadata',result['updated']==1 and result['status']=='success')
    # A transient model failure must leave the checkpoint unchanged.
    async with get_db_session() as db:
        before=(await db.execute(text("SELECT count(*) FROM arxiv_crawl_log WHERE status='success'"))).scalar()
    with patch.object(tasks.BiorxivCrawler,'crawl_date_range',return_value=[bio.BiorxivCrawler()._parse_record(record('10.test/strict'))]),patch.object(tasks.ArxivLLMClassifier,'process_batch',side_effect=RuntimeError('model down')):
        try:await tasks._biorxiv_incremental()
        except RuntimeError:pass
        else:raise AssertionError('model failure must fail task')
    async with get_db_session() as db:
        after=(await db.execute(text("SELECT count(*) FROM arxiv_crawl_log WHERE status='success'"))).scalar()
        check('model failure cannot advance checkpoint',before==after)

async def citation_tests():
    from core.cache import cache_set
    from modules.journals.tasks import crawler_tasks as journals
    await cache_set("sm:citations:last-id", 0, ttl=60)
    async with get_db_session() as db:
        await db.execute(text("TRUNCATE journal_articles,crawl_task_log_journals RESTART IDENTITY CASCADE"))
        for i in range(1,4):
            await db.execute(text("""INSERT INTO journal_articles(doi,title,published_at_precise,publication_date,journal_issn,category,cited_by_count,labels,last_citation_update_at)
                VALUES (:doi,'Exercise',now(),current_date,'0000-0000','sports_science',123,ARRAY['hot','recent'],now()-interval '10 days')"""),{'doi':f'10.test/{i}'})
        await db.commit()
    seen=[]
    async def work(doi):
        seen.append(doi)
        return None if doi=='10.test/1' else {'openalex_id':'https://openalex.org/W1','cited_by_count':999,'cited_by_percentile_year':90}
    with patch.object(journals.OpenAlexClient,'get_work_by_doi',side_effect=work):
        first=await journals._async_update_citations(2)
        second=await journals._async_update_citations(1)
    check('citation chunks obey batch limit',first['total_updated']==1 and first['total_failed']==1 and second['total_updated']==1)
    check('citation cursor proceeds beyond repeatedly missing DOI',seen==['10.test/1','10.test/2','10.test/3'])
    async with get_db_session() as db:
        row=(await db.execute(text("SELECT cited_by_count,last_citation_update_at<now()-interval '7 days' AS old FROM journal_articles WHERE doi='10.test/1'"))).one()
        check('missing citation never erases old count or marks it fresh',row.cited_by_count==123 and row.old)
    await cache_set("sm:citations:last-id",0,ttl=60)
    with patch.object(journals.OpenAlexClient,'get_work_by_doi',side_effect=base.UpstreamRateLimited('api.openalex.org',80000)):
        result=await journals._async_update_citations(1)
        check('citation 429 returns deferred promptly',result['status']=='deferred' and result['total_updated']==0)


async def main():
    await provider_tests();crawler_tests();await db_tests();await citation_tests()
    result={'passed':len(checks),'checks':checks}
    Path('/tmp/sm-release-regression.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
run_async(main())
