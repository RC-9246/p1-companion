"""Staging-only ordinary browser access probe; no login, no writes or workarounds."""
import asyncio,json
from urllib.parse import urlsplit
from playwright.async_api import async_playwright

def approved(u):
 p=urlsplit(u);h=(p.hostname or '').lower()
 return p.scheme=='https' and p.port in (None,443) and not p.username and not p.password and any(h==d or h.endswith('.'+d) for d in ('bilibili.com','hdslb.com','bilivideo.com'))
async def main():
 denied=set();hosts=set()
 async with async_playwright() as p:
  b=await p.chromium.launch(executable_path='/usr/bin/chromium',chromium_sandbox=True,headless=True,args=['--disable-dev-shm-usage','--disable-background-networking','--disable-quic'])
  c=await b.new_context(accept_downloads=False,service_workers='block',viewport={'width':1024,'height':768})
  async def route(r):
   q=r.request
   if q.method not in ('GET','HEAD') or not approved(q.url):
    denied.add(urlsplit(q.url).hostname or '');await r.abort();return
   hosts.add(urlsplit(q.url).hostname);await r.continue_()
  await c.route('**/*',route);page=await c.new_page()
  for url in ('https://www.bilibili.com/','https://search.bilibili.com/all?keyword=%E4%B9%89%E5%A6%B9%E7%94%9F%E6%B4%BB'):
   try:
    response=await page.goto(url,wait_until='domcontentloaded',timeout=25000);await page.wait_for_timeout(6000)
    text=(await page.locator('body').inner_text())[:1000]
    videos=await page.locator('a[href*="/video/BV"]').count()
    print(json.dumps({'document_host':urlsplit(url).hostname,'status':response.status if response else 0,'title':await page.title(),'video_link_count':videos,'challenge':any(x in text for x in ('验证后继续','访问受限','安全验证','异常请求')),'body_prefix':text[:400]},ensure_ascii=False))
   except Exception as e:print(json.dumps({'probe_error':type(e).__name__}))
  print(json.dumps({'contacted_hosts':sorted(hosts),'blocked_hosts':sorted(denied)}));await b.close()
asyncio.run(main())
