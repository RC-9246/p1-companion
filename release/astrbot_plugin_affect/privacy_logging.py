"""Redact Python logging records before console, dashboard and file handlers see them."""
import logging
import re
from .appraisal import scrub

class PrivacyFilter(logging.Filter):
    def filter(self,record):
        try:
            text=record.getMessage()
            sensitive=(getattr(record,'category','')=='user_chat' or
                'base64://' in text or 'data:image/' in text or
                any(x in record.pathname.replace('\\','/') for x in ('/core/platform/','/core/pipeline/','/core/agent/runners/','/core/provider/sources/')) or
                any(x in text for x in ('Prepare to send -','ProviderRequest(','LLMResponse(')))
            if sensitive:
                kind=type(record.exc_info[1]).__name__ if record.exc_info else 'none'
                record.msg='[P1 Privacy] event details redacted; component='+record.module+' exception='+kind
                record.exc_info=None;record.exc_text=None;record.stack_info=None
            else:
                record.msg=re.sub(r'(?<!\d)\d{5,}(?!\d)','[identifier]',scrub(text))
            record.args=()
        except Exception:
            record.msg='[P1 Privacy] unformattable record redacted'
            record.args=();record.exc_info=None;record.exc_text=None
        return True

def install():
    from astrbot.core import logger
    guard=PrivacyFilter()
    registrations=[]
    logger.addFilter(guard);registrations.append(logger)
    handlers=set(logging.getLogger().handlers+logger.handlers)
    for value in list(logging.Logger.manager.loggerDict.values()):
        if isinstance(value,logging.Logger): handlers.update(value.handlers)
    for handler in handlers:
        handler.addFilter(guard);registrations.append(handler)
    return guard,registrations

def remove(registration):
    guard,targets=registration
    for target in targets: target.removeFilter(guard)
