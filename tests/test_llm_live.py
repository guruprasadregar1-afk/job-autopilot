import sys
from pathlib import Path
sys.path.insert(0, str(Path('job-autopilot').resolve()))
from src.llm import ask_json

prompt = 'You are a test evaluator. Given the candidate skills React, Node.js and job for Senior Full Stack Developer, return ONLY a raw JSON object with keys: apply (boolean), score (number 0-100), reason (short string).'

print('Invoking ask_json...')
res = ask_json(prompt, model='claude-haiku-4-5', cli_command='claude.cmd')
print('SUCCESS! Result:', res)
assert isinstance(res, dict)
assert 'apply' in res
assert 'score' in res
assert 'reason' in res
print('All assertions passed!')
