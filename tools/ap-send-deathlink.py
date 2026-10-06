"""Send one real AP DeathLink probe from an authenticated test peer."""
import argparse
import asyncio
import json
import os
import sys
import time
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
os.environ['AP_TEST_WORLDS']='dead_as_disco';os.environ['SKIP_REQUIREMENTS_UPDATE']='1'
sys.path.insert(0,str(ROOT/'artifacts/references/Archipelago-0.6.8'))

async def send(args):
    from CommonClient import CommonContext,server_loop
    seed=json.loads((ROOT/'artifacts/ap-slice'/args.run/'generation.json').read_text())
    ready=asyncio.Event()
    class Peer(CommonContext):
        game='Dead as Disco';items_handling=0
        async def server_auth(self,password_requested=False):
            if self.server_seed_name!=seed['seed_name']:raise RuntimeError('Wrong probe seed')
            self.auth=seed['slot'];await self.send_connect()
        def on_package(self,cmd,args):
            if cmd=='Connected':ready.set()
    ctx=Peer(None,None)
    ctx.server_task=asyncio.create_task(server_loop(ctx,args.server))
    try:
        await asyncio.wait_for(ready.wait(),10)
        await ctx.send_msgs([{'cmd':'Bounce','tags':['DeathLink'],'data':{
            'time':time.time(),'source':'Protected external DeathLink probe','cause':'Protected incoming DeathLink test'}}])
        await asyncio.sleep(1)
        print('Sent one authenticated AP DeathLink probe.')
    finally:
        ctx.exit_event.set();await ctx.shutdown()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',required=True);p.add_argument('--server',required=True)
    asyncio.run(send(p.parse_args()))
