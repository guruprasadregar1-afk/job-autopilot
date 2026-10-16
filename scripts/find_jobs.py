import time
from src.browser import BrowserManager
from src.policy import SafePage

mgr = BrowserManager(headless=False)
ctx = mgr.start()
p = ctx.new_page()
safe_p = SafePage(p)

safe_p.safe_goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded")
time.sleep(5)

job_links = p.locator('a[href*="/jobs/view/"]')
print("Job links on jobs home:", job_links.count(), flush=True)

for i in range(min(10, job_links.count())):
    href = job_links.nth(i).get_attribute("href") or ""
    text = job_links.nth(i).inner_text().replace("\n", " ").strip()
    print(f"[{i}] {text} -> {href[:80]}", flush=True)

ctx.close()
mgr.close()
