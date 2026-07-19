from langchain_core.messages import BaseMessage
from typing import Union, List, Dict

def get_message_content(msg: Union[BaseMessage, Dict, str]) -> str:
    if isinstance(msg, BaseMessage):
        return msg.content
    elif isinstance(msg, dict):
        return msg.get("content", "")
    else:
        return str(msg)

def get_last_user_message(messages: List) -> str:
    if not messages:
        return ""
    return get_message_content(messages[-1])