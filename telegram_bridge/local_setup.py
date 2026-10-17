"""Read only this clone's private setup; serialize presence, never credentials."""
import json
import os
from pathlib import Path
import subprocess
from dotenv import dotenv_values


def inspect_setup(root, *, run=subprocess.run):
    root=Path(root).resolve();values={**dotenv_values(root/'.env'),**os.environ}
    python=Path(values.get('TELEGRAM_PYTHON_PATH') or root/'.venv/Scripts/python.exe').resolve()
    configured={name:bool(values.get(name)) for name in (
        'HF_TOKEN','ZERNIO_API_KEY','ZERNIO_INSTAGRAM_ID','TELEGRAM_BOT_TOKEN')}
    configured['TELEGRAM_ALLOWED_USERS']=bool(values.get('TELEGRAM_ALLOWED_USER_IDS') or values.get('TELEGRAM_ALLOWED_USER_ID') not in (None,'','0'))
    report={'env_file_present':(root/'.env').is_file(),'configured':configured,
        'python_path':str(python),'python_exists':python.is_file(),
        'saved_channel_present':False,'media_ready':False,'missing_packages':None,'models_cached':None}
    connection=root/'workflow/connection.json'
    if connection.is_file():
        try:report['saved_channel_present']=bool(json.loads(connection.read_text(encoding='utf-8')).get('channel_id'))
        except (OSError,ValueError):pass
    if python.is_file():
        try:
            result=run([str(python),str(root/'reel.py'),'doctor'],cwd=root,capture_output=True,
                text=True,encoding='utf-8',timeout=20)
            if result.returncode==0:
                doctor=json.loads(result.stdout)
                report.update(media_ready=bool(doctor.get('ready_for_media')),missing_packages=doctor.get('missing_packages'),
                    models_cached=bool(doctor.get('whisper_model_cached')),cpu_only=doctor.get('cpu_only'))
        except (OSError,ValueError,subprocess.SubprocessError):report['diagnostics_failed']=True
    # Only returned in process memory for outgoing redaction, not in the report.
    secrets=tuple(value for key,value in values.items() if isinstance(value,str) and value and any(tag in key.upper() for tag in ('KEY','TOKEN','PASSWORD','SECRET')))
    return report,secrets


def instructions(root):
    report,secrets=inspect_setup(root)
    return ('\nCurrent local setup (read-only, no credentials disclosed): '+json.dumps(report)+'''
Use the verified python_path above for all project Python commands. Do not use an unrelated system Python.
Credentials belong to this clone's ignored .env; the project's commands load them there. Never copy
creator/another student's credentials or scan parent projects for secrets. Check presence before asking.
Never request keys, passwords or tokens in Telegram. If genuinely missing, report ONLY missing names
and ask the owner to enter them privately in this local project's .env/Codex editor, then retry.
Use existing configured credentials and cached models; never repeat account setup or installation
when diagnostics pass. Missing Instagram/Zernio credentials do not block clipping a supplied URL.
A saved channel is required only for a channel trigger. Do not invent a missing-credential claim from
an unrelated Python interpreter. This is a Codex conversation: diagnose and repair genuine local
runtime/package/configuration faults here using the existing setup instructions and tests, then
resume. Do not demand desktop onboarding merely because Telegram delivered the request. Avoid
duplicate installations; never reinstall a working environment. Human-only login, credential entry
and provider consent still require the owner through the private local setup flow.
''',secrets)
