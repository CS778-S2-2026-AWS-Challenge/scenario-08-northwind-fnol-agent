import re
from uuid import uuid4

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = 'X-Request-ID'
REQUEST_ID_PATTERN = re.compile(r'^[A-Za-z0-9._:-]{1,128}$')


class RequestIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        headers = MutableHeaders(scope=scope)
        supplied_request_id = headers.get(REQUEST_ID_HEADER)
        request_id = (
            supplied_request_id
            if supplied_request_id and REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else f'req_{uuid4().hex}'
        )
        scope.setdefault('state', {})['request_id'] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message['type'] == 'http.response.start':
                response_headers = MutableHeaders(scope=message)
                response_headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.app(scope, receive, send_with_request_id)
