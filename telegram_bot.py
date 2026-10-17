"""Optional private Telegram controller. Does not run a clipping job on import."""
import argparse
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from telegram_bridge.config import Config
from telegram_bridge.api import API
from telegram_bridge.controller import Controller, poll
from telegram_bridge.runner import fingerprint, require_probe, Runner, WorkflowError, run_codex
from telegram_bridge.storage import atomic_json

ROOT=Path(__file__).resolve().parent


@contextmanager
def singleton(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    stream=path.open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:stream.close()


def doctor(config):
    from reel_engine.config import settings
    from reel_engine.doctor import check
    result={'telegram_configured':bool(config.token and config.owner),'generation_request_made':False,
            'media':check(config.root,settings),'desktop_window_required':False}
    try:
        result['codex']=fingerprint(config)
        try:require_probe(config);result['headless_tools_verified']=True
        except WorkflowError:result['headless_tools_verified']=False
    except (WorkflowError,OSError,subprocess.TimeoutExpired):
        result.update(codex_ready=False,headless_tools_verified=False)
    result['ready']=bool(result.get('headless_tools_verified') and result['telegram_configured'] and result['media']['ready_for_media'])
    return result


def record_probe(config, folder, result, evidence):
    if (result.get('status')!='verified' or 'green' not in result.get('color','').lower()
        or not all(evidence.values()) or not (folder/'shell-proof.txt').is_file()
        or (folder/'shell-proof.txt').read_text().strip()!='PROBE_OK'):
        raise WorkflowError('Headless image/shell capability not proved. Desktop tools are not assumed equivalent; do not start real jobs.')
    atomic_json(config.state/'capability.json',{'binding':fingerprint(config),**evidence,'verified':time.time()})
    return {'capability_probe_passed':True,'clipping_job_started':False,'note':'Real source editorial quality is still untested; existing review safeguards remain.'}


def probe(config):
    """Explicitly authorized model request; NOT run by doctor or unit tests."""
    binding=fingerprint(config)
    from PIL import Image
    folder=config.state/'probe'/str(time.time_ns());folder.mkdir(parents=True)
    image=Image.new('RGB',(80,80),(25,170,90));image.save(folder/'fixture.png')
    schema={'type':'object','additionalProperties':False,'required':['status','color'],
        'properties':{'status':{'type':'string','enum':['verified','unavailable']},'color':{'type':'string'}}}
    prompt=f'''Harmless local tool-capability test ONLY. Do not run clipping, downloads, account requests,
publishing, or read .env/auth files. Use an actual shell tool to read templates/output-defaults.json
and write the exact text PROBE_OK to {folder/'shell-proof.txt'}. Use the actual image-view tool to
open {folder/'fixture.png'} and report its dominant color. Do not infer from file names or a shell pixel
query. If shell or image tools are unavailable report unavailable. No code/config changes. Return schema.'''
    result,evidence=run_codex(config,folder,prompt,schema,required_image=folder/'fixture.png')
    if fingerprint(config)!=binding:raise WorkflowError('Setup changed during the probe; proof refused.')
    return record_probe(config,folder,result,evidence)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['doctor','probe','run','identify'])
    p.add_argument('--authorize-codex-probe',action='store_true');args=p.parse_args()
    # Reuse the active environment's existing private CA bundle when one was
    # installed for this Windows machine. Never turn TLS verification off.
    trust=Path(sys.executable).parent/'ca.pem'
    if trust.is_file():os.environ.setdefault('SSL_CERT_FILE',str(trust))
    config=Config.load(ROOT)
    try:
        if args.command=='doctor':print(json.dumps(doctor(config),indent=2));return
        if args.command=='probe':
            if not args.authorize_codex_probe:raise WorkflowError('The probe consumes Codex account usage. Explicitly authorize with --authorize-codex-probe. No generation performed.')
            with singleton(config.state/'bot.lock'):print(json.dumps(probe(config),indent=2))
            return
        if args.command=='identify':
            if not config.token:raise WorkflowError('Configure the bot token privately first.')
            api=API(config.token)
            print('Send /start to your own bot now. Reading IDs only; no workflow or messages are sent.')
            for update in api.updates(0,30):
                m=update.get('message',{})
                if m.get('chat',{}).get('type')=='private':print('Private Telegram numeric user ID:',m.get('from',{}).get('id'))
            return
        config.require_private_owner()
        readiness=doctor(config)
        if not readiness['ready']:raise WorkflowError('Telegram/Codex/media setup incomplete. Run doctor; finish setup and the authorized probe before starting.')
        with singleton(config.state/'bot.lock'):
            print('Private Telegram controller running. No clipping starts until the owner sends a trigger and count.')
            api=API(config.token)
            poll(Controller(config,api,Runner(config)),api)
    except (WorkflowError,ValueError,OSError,subprocess.SubprocessError):
        print('Controller stopped safely. Check configuration, doctor, capability proof and private request/job state. No automatic rerun or publication.',file=sys.stderr)
        return 1


if __name__=='__main__':sys.exit(main())
