"""Live loopback HTTP MCP on main/dedicated processes, isolated DB and fake mail."""
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
from urllib.request import urlopen

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastmcp import Client
from tests.browser_support import browser_server, REPO


async def exercise(main, dedicated, token):
    async with Client(main+'/mcp/',auth=token,timeout=15) as a, Client(dedicated+'/mcp/',auth=token,timeout=15) as b:
        async def call(client,name,args=None):
            result=await client.call_tool(name,args or {})
            assert not result.is_error
            return result.structured_content
        catalogs=[{t.name for t in await client.list_tools()} for client in (a,b)]
        assert catalogs[0]==catalogs[1] and 'issue.create' in catalogs[0] and 'create_project' not in catalogs[0]
        identity=await call(a,'whoami');assert (await call(b,'whoami'))['id']==identity['id']
        created=await call(a,'issue.create',{'title':'Live protocol','description':'Shared live database'})
        iid=created['issue_id']
        assert (await call(b,'issue.get',{'issue_id':iid}))['description']=='Shared live database'
        update=await call(b,'update.add',{'issue_id':iid,'content':'Live cross-service update'})
        assert (await call(a,'update.get',{'issue_id':iid,'update_id':update['update_id']}))['content']=='Live cross-service update'
        content=b'\x00\xfflive binary'
        attached=await call(a,'attachment.add',{'issue_id':iid,'original_name':'evidence.bin','content':base64.b64encode(content).decode()})
        downloaded=await call(b,'attachment.read',{'issue_id':iid,'attachment_id':attached['attachment_id']})
        assert base64.b64decode(downloaded['content'])==content
        assert (await call(a,'search',{'query':'"cross-service update"'}))['total']==1
        for client,base in ((a,main),(b,dedicated)):
            guide=await call(client,'get_agent_guide')
            assert guide['metadata']['attachment_api_base_url']==base
            assert base+'/api/issues/' in guide['markdown']
        await call(a,'issue.delete',{'issue_id':iid})
        missing=await b.call_tool('issue.get',{'issue_id':iid},raise_on_error=False)
        assert missing.is_error and missing.structured_content['code']=='issue_not_found'


def main():
    with browser_server() as fixture:
        root=fixture['root']
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        dedicated=f'http://127.0.0.1:{port}'
        with sqlite3.connect(root/'data/casos.db') as db:
            db.execute('INSERT OR REPLACE INTO app_config(id,server_address) VALUES(1,?)',(fixture['url'].split('://',1)[1],))
        env={**os.environ,'CASOS_DATA_DIR':str(root/'data'),'CASOS_LOG_FILE':str(root/'mcp-security.log'),
             'CASOS_HOST':'127.0.0.1','CASOS_MCP_PORT':str(port)}
        with (root/'mcp-server.log').open('w+') as log:
            process=subprocess.Popen([sys.executable,str(REPO/'dashboard/mcp_app.py')],cwd=REPO,env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                deadline=time.monotonic()+30
                while time.monotonic()<deadline:
                    if process.poll() is not None:
                        log.seek(0);raise RuntimeError(log.read())
                    try:
                        with urlopen(dedicated+'/.well-known/casos-agent.json',timeout=1) as response:
                            if response.status==200:break
                    except OSError:time.sleep(.1)
                else:raise TimeoutError('Dedicated MCP fixture did not start')
                asyncio.run(exercise(fixture['url'],dedicated,fixture['identities']['agent']['token']))
            finally:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        print(json.dumps({'result':'passed','checks':['live main and dedicated HTTP MCP sessions','shared issue/update/attachment data','binary byte preservation','search','runtime guides','cross-service deletion']}))


if __name__=='__main__':main()
