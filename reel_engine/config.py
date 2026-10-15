from pathlib import Path
import os
from pydantic_settings import BaseSettings,SettingsConfigDict
from pydantic import Field

ROOT=Path(__file__).resolve().parents[1]
class Settings(BaseSettings):
    model_config=SettingsConfigDict(env_file=ROOT/'.env',extra='ignore')
    whisper_model:str='small'
    local_device:str='cpu'
    local_compute_type:str='int8'
    hf_token:str=''
    diarization_model:str='pyannote/speaker-diarization-community-1'
    local_model_dir:Path=ROOT/'data/models'
    youtube_cookie_file:str=''
    youtube_cookies_from_browser:str=''
    youtube_request_delay_seconds:float=2.0
    caption_cache_dir:Path=ROOT/'workflow/caption-cache'
    caption_retry_wait_cap_seconds:float=300.0
    fast_word_confidence_threshold:float=.6
    fast_disagreement_confidence_threshold:float=.8
    fast_whisper_beam_size:int=Field(default=5,ge=1,le=10)
    whisper_beam_size:int=Field(default=5,ge=1,le=10)
    fast_caption_skip_warning_fraction:float=.15
    crop_safety_margin:float=.04
    scene_pan_threshold:float=.08
    min_subject_width_fraction:float=Field(default=1.,gt=0,le=1)
    selection_draft_model:str=Field(default='base',pattern='^(base|tiny)$')
    full_download_max_bytes:int=Field(default=1500000000,gt=0)
    section_download_min_height:int=Field(default=2160,ge=1080)
    download_mode:str=Field(default='auto',pattern='^(auto|selected-sections)$')
    compact_pre_review:bool=True
    processing_mode:str=Field(default='smart',pattern='^(fast|smart)$')
    adaptive_details:bool=True
    render_backend:str=Field(default='legacy',pattern='^(legacy|direct)$')
    x264_preset:str=Field(default='fast',pattern='^(fast|veryfast)$')
    semantic_vision_url:str=''
    semantic_vision_model:str=''
    semantic_vision_api_key:str=''
    semantic_allow_remote:bool=False
    # Gemini Developer API is the only permitted semantic provider. Disabled
    # until the operator confirms the free plan AND authorizes a CLI request.
    gemini_enabled:bool=False
    gemini_api_key:str=Field(default='',repr=False)
    gemini_model:str='gemini-2.5-flash'
    gemini_project_id:str=''
    gemini_free_tier_confirmed:bool=False
    google_oauth_access_token:str=Field(default='',repr=False)
    gemini_rpm:int=Field(default=1,ge=1,le=10)
    gemini_rpd:int=Field(default=20,ge=1,le=1000)
    gemini_tpm:int=Field(default=150000,ge=1000,le=1000000)
    gemini_max_frames:int=Field(default=80,ge=1,le=80)
    gemini_max_output_tokens:int=Field(default=8192,ge=1024,le=16384)
    gemini_max_retries:int=Field(default=2,ge=0,le=2)
    gemini_backoff_cap_seconds:float=Field(default=30,ge=0,le=60)
    motion_check_interval:float=Field(default=.1,ge=.033,le=.25)
    parallel_downloads:bool=False
    youtube_api_key:str=''
    min_source_height:int=1080
    quality_wait_hours:int=24
    max_source_seconds:int=7200
    zernio_api_key:str=''
    zernio_instagram_id:str=''

settings=Settings()
trust=ROOT/'.venv/ca.pem'
if trust.exists():os.environ.setdefault('SSL_CERT_FILE',str(trust))
