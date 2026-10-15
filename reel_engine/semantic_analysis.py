"""Semantic entry point: Gemini free-project API only, opt-in and unapproved.

Legacy endpoint arguments remain solely to reject old paid-provider settings.
Local CPU tracking/rendering and all review guards are unchanged.
"""
from .gemini_free import analyze as gemini_analyze


def analyze(base,details,transcript,root,*,settings=None,authorized=False,
            endpoint='',model='',key='',allow_remote=False):
    if endpoint or key or allow_remote:
        raise ValueError('Legacy vision endpoints are disabled; only the verified Gemini free-project integration is allowed.')
    if settings is None:
        from .config import settings
    return gemini_analyze(base,details,transcript,root,settings,authorized=authorized)
