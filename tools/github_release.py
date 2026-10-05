"""Use Git Credential Manager in memory; never print or persist a token."""
import argparse,json,os,subprocess,urllib.request,urllib.error
from pathlib import Path
BASE='https://api.github.com'
REPO='DionysusDWI/SCAPI-MCP'

def credential():
    env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
    p=subprocess.run(['git','credential','fill'],input='protocol=https\nhost=github.com\n\n',text=True,capture_output=True,env=env)
    if p.returncode:raise RuntimeError('GitHub credential unavailable; authenticate Git Credential Manager outside this script')
    pairs=dict(line.split('=',1) for line in p.stdout.splitlines() if '=' in line)
    if not pairs.get('password'):raise RuntimeError('GitHub credential unavailable')
    return pairs['password']

def api(token,path,method='GET',data=None,content_type='application/json'):
    url=path if path.startswith('https://uploads.github.com/') else BASE+path
    if data is not None and not isinstance(data,bytes):data=json.dumps(data).encode()
    request=urllib.request.Request(url,data=data,method=method,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'SCAPI-MCP-release','Content-Type':content_type})
    try:
        with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
    except urllib.error.HTTPError as error:raise RuntimeError(f'GitHub API {method} failed: HTTP {error.code}') from None

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['identity','publish','verify']);p.add_argument('--tag');p.add_argument('--commit');p.add_argument('--body');p.add_argument('--assets',nargs='*');args=p.parse_args();token=credential()
    if args.command=='identity':
        user=api(token,'/user');repo=api(token,'/repos/'+REPO)
        print(json.dumps({'login':user['login'],'name':user.get('name') or user['login'],'id':user['id'],'email':str(user['id'])+'+'+user['login']+'@users.noreply.github.com','push':repo.get('permissions',{}).get('push',False),'default_branch':repo['default_branch']},ensure_ascii=False));return
    if not args.tag:raise RuntimeError('Tag required')
    if args.command=='verify':
        r=api(token,f'/repos/{REPO}/releases/tags/{args.tag}');print(json.dumps({'id':r['id'],'url':r['html_url'],'draft':r['draft'],'prerelease':r['prerelease'],'tag':r['tag_name'],'assets':[{'name':a['name'],'size':a['size'],'digest':a.get('digest'),'url':a['browser_download_url']} for a in r['assets']]},ensure_ascii=False));return
    if not args.commit or not args.body:raise RuntimeError('Commit and body required')
    # Existing tags/releases are immutable. Do not silently replace published assets.
    ref=api(token,f'/repos/{REPO}/git/ref/tags/{args.tag}')
    if ref['object']['sha']!=args.commit:raise RuntimeError('Remote tag differs from release commit')
    existing=api(token,f'/repos/{REPO}/releases?per_page=100')
    if any(item['tag_name']==args.tag for item in existing):raise RuntimeError('Release already exists; never replace published assets or retry a partial draft blindly')
    r=api(token,f'/repos/{REPO}/releases','POST',{'tag_name':args.tag,'target_commitish':args.commit,'name':'SCAPI-MCP '+args.tag,'body':Path(args.body).read_text(encoding='utf-8'),'draft':True,'prerelease':False})
    from urllib.parse import quote
    for name in args.assets or []:
        asset=Path(name);api(token,r['upload_url'].split('{')[0]+'?name='+quote(asset.name),'POST',asset.read_bytes(),'application/octet-stream')
    r=api(token,f'/repos/{REPO}/releases/{r["id"]}','PATCH',{'draft':False})
    print(json.dumps({'id':r['id'],'url':r['html_url'],'tag':r['tag_name']},ensure_ascii=False))

if __name__=='__main__':main()
