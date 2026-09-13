#!/usr/bin/env python3
"""Create this public project and deploy it via the user's local GitHub CLI.
Never reads browser cookies, displays tokens, modifies other repos, or force-pushes.
Python 3.10+ and official `gh` are required. --dry-run needs no GitHub access.
"""
from __future__ import annotations
import argparse,json,re,shutil,subprocess,sys,time
from pathlib import Path
from urllib.request import urlopen,Request
ROOT=Path(__file__).resolve().parent
STATE=ROOT/'.deploy-state.json'
PUBLIC_FILES=['README.md','.gitignore','.github/workflows/pages.yml','scripts/update.py',
 'site/index.html','site/data/latest.json','site/data/status.json','site/.nojekyll',
 'deploy.py','deploy.cmd','CODEX_TASK.md','tests/test_project.py','qa-results.json']

class DeployError(RuntimeError):pass

def redact(s):
    return re.sub(r'(?:gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)', '[REDACTED]',s)

def api(method,path,payload=None,allow_404=False):
    command=['gh','api','--hostname','github.com','--method',method,path,'-H','Accept: application/vnd.github+json','-H','X-GitHub-Api-Version: 2022-11-28']
    if payload is not None:command+=['--input','-']
    result=subprocess.run(command,input=json.dumps(payload) if payload is not None else None,text=True,encoding='utf-8',errors='replace',capture_output=True,timeout=60)
    if result.returncode:
        if allow_404 and 'HTTP 404' in result.stderr:return None
        raise DeployError(redact(result.stderr.strip())[:2000])
    return json.loads(result.stdout) if result.stdout.strip() else {}

def authenticate():
    if not shutil.which('gh'):
        raise DeployError('Official GitHub CLI (gh) is not installed. Windows: winget install --id GitHub.cli --exact ; macOS: brew install gh . Reopen the terminal after installation. Do not paste passwords or tokens into ChatGPT.')
    status=subprocess.run(['gh','auth','status','--hostname','github.com'],capture_output=True,text=True)
    if status.returncode:
        print('Authorize the official GitHub CLI in your browser. Do not send the code to ChatGPT.')
        result=subprocess.run(['gh','auth','login','--hostname','github.com','--git-protocol','https','--web','--scopes','workflow'])
        if result.returncode:raise DeployError('GitHub CLI browser authorization did not complete.')
    return api('GET','user')['login']

def manifest():
    files=[]
    for name in PUBLIC_FILES:
        p=ROOT/name
        if not p.is_file() or p.is_symlink():raise DeployError('Missing or unsafe package file: '+name)
        text=p.read_text(encoding='utf-8')
        if re.search(r'(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|(?m:^[ ]*-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----$))',text):raise DeployError('Possible credential in '+name)
        files.append({'path':name,'mode':'100644','type':'blob','content':text})
    return files

def create_and_push(owner,name,files):
    target=owner+'/'+name
    existing=api('GET','repos/'+target,allow_404=True)
    state=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    if existing:
        if state.get('repo')!=target or state.get('repo_id')!=existing['id']:
            raise DeployError('Repository already exists. Nothing was overwritten: '+target+'. Choose a different --name, or review the existing repository separately.')
        repo=existing
    else:
        repo=api('POST','user/repos',{'name':name,'private':False,'auto_init':True,'description':'A股市场公开简报：新闻、行情与风险观察（数据服务待接入）','has_wiki':False})
        STATE.write_text(json.dumps({'repo':target,'repo_id':repo['id'],'initial_sha':None}),encoding='utf-8')
        state={'repo':target,'repo_id':repo['id'],'initial_sha':None}
    branch=repo['default_branch']
    # Wait only for GitHub's auto-initialized README branch to become readable.
    ref=None
    for _ in range(10):
        ref=api('GET',f'repos/{target}/git/ref/heads/{branch}',allow_404=True)
        if ref:break
        time.sleep(2)
    if not ref:raise DeployError('Initial branch is not yet readable. Repo was created; rerun this script with the same name.')
    base=ref['object']['sha']
    if state.get('commit_sha'):
        print('Resuming verification of the previously uploaded commit. No files overwritten.')
        return target,state['commit_sha'],state.get('pages_url')
    if state.get('initial_sha') and state['initial_sha']!=base:raise DeployError('Repository changed after initial creation. Refusing to overwrite other work.')
    # Record initial branch commit BEFORE any later network operation can fail.
    state.update({'initial_sha':base,'branch':branch});STATE.write_text(json.dumps(state),encoding='utf-8')
    pages=api('GET',f'repos/{target}/pages',allow_404=True)
    if pages is None:pages=api('POST',f'repos/{target}/pages',{'build_type':'workflow'})
    elif pages.get('build_type')!='workflow':
        api('PUT',f'repos/{target}/pages',{'build_type':'workflow'})
    base_commit=api('GET',f'repos/{target}/git/commits/{base}')
    # Only the new project's default branch is a production deployment trigger.
    for item in files:
        if item['path']=='.github/workflows/pages.yml':
            item['content']=item['content'].replace('branches: [main, master]','branches: '+json.dumps([branch]))
    tree=api('POST',f'repos/{target}/git/trees',{'base_tree':base_commit['tree']['sha'],'tree':files})
    commit=api('POST',f'repos/{target}/git/commits',{'message':'Publish A-share brief website and deployment workflow','tree':tree['sha'],'parents':[base]})
    api('PATCH',f'repos/{target}/git/refs/heads/{branch}',{'sha':commit['sha'],'force':False})
    pages=api('GET',f'repos/{target}/pages')
    state.update({'commit_sha':commit['sha'],'pages_url':pages.get('html_url')})
    STATE.write_text(json.dumps(state),encoding='utf-8')
    return target,commit['sha'],pages.get('html_url')

def verify(target,commit_sha,timeout):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        response=api('GET',f'repos/{target}/actions/runs?head_sha={commit_sha}&per_page=10')
        runs=[r for r in response.get('workflow_runs',[]) if r.get('name')=='Publish market brief']
        if runs:
            run=max(runs,key=lambda r:r['id'])
            if run['status']=='completed':
                if run.get('conclusion')!='success':raise DeployError('Deployment did not succeed. Inspect '+run['html_url'])
                pages=api('GET',f'repos/{target}/pages');url=pages.get('html_url')
                if url and url.startswith('https://'):
                    try:
                        with urlopen(Request(url,headers={'User-Agent':'a-share-brief-deploy/1.0'}),timeout=15) as result:
                            html=result.read(1_000_000).decode('utf-8')
                            if result.status==200 and 'name="application-name" content="a-share-brief"' in html:
                                return url
                    except Exception:pass
        time.sleep(8)
    return None

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--name',default='a-share-brief');p.add_argument('--dry-run',action='store_true');p.add_argument('--wait',type=int,default=600)
    args=p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,80}',args.name):raise DeployError('Invalid repository name')
    files=manifest()
    if args.dry_run:
        print(json.dumps({'mode':'dry-run','repository':args.name,'visibility':'public','files':[f['path'] for f in files], 'automatic_research':'not connected','scheduled_imports':'disabled until provider is configured'},ensure_ascii=False,indent=2));return 0
    owner=authenticate()
    print('Target PUBLIC repository:',owner+'/'+args.name)
    print('Only this package\'s allowlisted files will be published. Existing unrelated repositories are not changed.')
    target,sha,url=create_and_push(owner,args.name,files)
    print('Repository created / uploaded: https://github.com/'+target)
    print('Deployment status: https://github.com/'+target+'/actions')
    verified=verify(target,sha,args.wait) if args.wait>0 else None
    result={'repo':target,'commit_sha':sha,'pages_url':url,'live_url_verified':verified,'data_service_connected':False,'push_connected':False}
    (ROOT/'deploy-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if verified:
        print('\nWebsite verified (HTTP 200 and project marker): '+verified)
        print('Website hosting works. Market data, research generation and notifications are NOT connected.');return 0
    print('Files uploaded, but live website has NOT yet been verified. Check Actions / Pages. No live status is claimed.');return 2
if __name__=='__main__':
    try:sys.exit(main())
    except (DeployError,subprocess.TimeoutExpired,KeyboardInterrupt,ValueError,OSError) as e:
        print('Stopped safely: '+redact(str(e)),file=sys.stderr)
        print('No other repository was modified. A partially created project may remain; no cleanup deletion is performed.',file=sys.stderr)
        sys.exit(1)
