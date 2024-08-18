import aiohttp
from pydantic import Field

from lion_core.abc import ObservableAction
from lion_core.action.status import ActionStatus
from lion_core.generic.element import Element

from lionagi.os.primitives import log
from lionagi.os.service.utils import call_api
from lionagi.os.service.config import RETRY_CONFIG


class APICalling(Element, ObservableAction):

    payload: dict = Field(default_factory=dict)
    response: dict = Field(default_factory=dict)
    base_url: str = Field(default=None)
    endpoint: str = Field(default=None)
    api_key: str = Field(default=None, exclude=True)
    method: str = Field("post")
    status: ActionStatus = Field(ActionStatus.PENDING)
    retry_config: dict = Field(default_factory=dict, exclude=True)
    error: str = Field(default=None)
    required_tokens: int = Field(default=1)
    api_key_schema: str = Field(default=None, exclude=True)
    execution_time: float = Field(default=None)

    def __init__(
        self,
        payload: dict = None,
        base_url: str = None,
        endpoint: str = None,
        api_key: str = None,
        method="post",
        retry_config=RETRY_CONFIG,
        required_tokens=1,
        api_key_schema=None,
    ):
        super().__init__()
        self.payload = payload
        self.base_url = base_url
        self.endpoint = endpoint
        self.api_key = api_key
        self.method = method
        self.retry_config = retry_config
        self.required_tokens = required_tokens
        self.api_key_schema = api_key_schema

    async def invoke(self):
        async with aiohttp.ClientSession() as session:
            url = self.base_url + self.endpoint
            headers = {"Authorization": f"Bearer {self.api_key}"}
            try:
                response, elp = await call_api(
                    http_session=session,
                    url=url,
                    method=self.method,
                    headers=headers,
                    json=self.payload,
                    timing=True,
                    **self.retry_config,
                )
                if response:
                    self.response = response
                    self.execution_time = elp
                    self.status = ActionStatus.COMPLETED

            except Exception as e:
                self.status = ActionStatus.FAILED
                self.error = str(e)

    def to_dict(self):
        dict_ = super().to_dict()
        dict_["api_key"] = (
            self.api_key[:6] + "*" * (len(self.api_key) - 10) + self.api_key[-4:]
        )
        dict_["status"] = self.status.value
        return dict_

    def to_log(self):
        _dict = self.to_dict()
        content = {
            "payload": _dict.pop("payload"),
            "response": _dict.pop("response"),
        }
        return log(
            content=content,
            loginfo=_dict,
        )

    @classmethod
    def from_dict(cls, dict_):
        raise NotImplementedError


# File: lionagi/os/service/api/utils.py
