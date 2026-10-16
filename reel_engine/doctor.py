"""Read-only installation checks. No downloads, API requests, or credential values."""
import importlib.util
import platform
import shutil
from pathlib import Path


def check(root,settings):
    root=Path(root)
    packages=('httpx','numpy','cv2','PIL','pydantic_settings','faster_whisper','torch','soundfile')
    missing=[p for p in packages if importlib.util.find_spec(p) is None]
    tools={name:bool(shutil.which(name)) for name in ('ffmpeg','ffprobe','node','deno')}
    assets={name:(root/name).is_file() for name in ('assets/Creepster-Regular.ttf','assets/Creepster-OFL.txt','assets/cta/watch-full-video.mp4')}
    tools_ready=not missing and tools['ffmpeg'] and tools['ffprobe'] and all(assets.values())
    cached=any(settings.local_model_dir.glob('whisper/**/model.bin'))
    provider_home=getattr(settings,'youtube_po_token_home','')
    from importlib.metadata import version,PackageNotFoundError
    try:provider_version=version('bgutil-ytdlp-pot-provider')
    except PackageNotFoundError:provider_version=None
    provider={'configured':bool(provider_home),'plugin_version':provider_version,
        'script_built':bool(provider_home and (Path(provider_home)/'build/generate_once.js').is_file()),
        'mode':'on-demand local Node script; no HTTP server'}
    return {'supported_platform':platform.system()=='Windows','python':platform.python_version(),
            'missing_packages':missing,'tools':tools,'assets':assets,'cpu_only':settings.local_device=='cpu',
            'instagram_configured':bool(settings.zernio_api_key and settings.zernio_instagram_id),
            'semantic_vision_configured':bool(settings.semantic_vision_url and settings.semantic_vision_model),
            'youtube_po_provider':provider,
            'whisper_model_cached':cached,'ready_for_media_tools':tools_ready,
            'ready_for_media':tools_ready and cached,
            'note':'Readiness is not successful model loading, YouTube access or account verification. No requests or downloads were made.'}
