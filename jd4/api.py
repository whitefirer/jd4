import json
from aiohttp import ClientSession
from asyncio import get_event_loop
from os import path
from urllib.parse import urljoin

from jd4.config import cookie_jar, save_cookies
from jd4.log import logger

CHUNK_SIZE = 32768

class VJ4Error(Exception):
    def __init__(self, name, message, *args):
        super().__init__(name, message, *args)
        self.name = name

async def json_response_to_dict(response):
    if response.content_type != 'application/json':
        raise Exception('invalid content type ' + response.content_type)
    response_dict = await response.json()
    if 'error' in response_dict:
        error = response_dict['error']
        raise VJ4Error(error.get('name', 'unknown'),
                       error.get('message', ''),
                       *error.get('args', []))
    return response_dict

class VJ4Session(ClientSession):
    def __init__(self, server_url):
        super().__init__(cookie_jar=cookie_jar)
        self.server_url = server_url

    def full_url(self, *parts):
        return urljoin(self.server_url, path.join(*parts))

    async def get_json(self, relative_url, **kwargs):
        async with self.get(self.full_url(relative_url),
                            headers={'accept': 'application/json'},
                            allow_redirects=False,
                            params=kwargs) as response:
            return await json_response_to_dict(response)

    async def post_json(self, relative_url, **kwargs):
        async with self.post(self.full_url(relative_url),
                             headers={'accept': 'application/json'},
                             allow_redirects=False,
                             data=kwargs) as response:
            return await json_response_to_dict(response)

    async def judge_consume(self, handler_type):
        async with self.ws_connect(self.full_url('judge/consume-conn/websocket')) as ws:
            logger.info('Connected')
            async for msg in ws:
                request = json.loads(msg.data)
                await handler_type(self, request, ws).handle()
            logger.warning('Connection lost with code %d', ws.close_code)

    async def judge_noop(self):
        await self.get_json('judge/noop')

    async def login(self, uname, password):
        logger.info('Login')
        await self.post_json('login', uname=uname, password=password)

    async def login_if_needed(self, uname, password):
        try:
            await self.judge_noop()
            logger.info('Session is valid')
        except VJ4Error as e:
            if e.name == 'PrivilegeError':
                await self.login(uname, password)
                await save_cookies()
            else:
                raise

    async def judge_datalist(self, last):
        return await self.get_json('judge/datalist', last=last)

    async def problem_data(self, domain_id, pid, save_path):
        logger.info('Getting problem data: %s, %s', domain_id, pid)
        loop = get_event_loop()
        async with self.get(self.full_url('d', domain_id, 'p', pid, 'data'),
                            headers={'accept': 'application/json'}) as response:
            if response.content_type == 'application/json':
                response_dict = await response.json()
                if 'error' in response_dict:
                    error = response_dict['error']
                    raise VJ4Error(error.get('name', 'unknown'),
                                   error.get('message', ''),
                                   *error.get('args', []))
                raise Exception('unexpected response')
            if response.status != 200:
                raise Exception('http error ' + str(response.status))
            with open(save_path, 'wb') as save_file:
                while True:
                    buffer = await response.content.read(CHUNK_SIZE)
                    if not buffer:
                        break
                    await loop.run_in_executor(None, save_file.write, buffer)

    async def record_pretest_data(self, rid):
        logger.info('Getting pretest data: %s', rid)
        async with self.get(self.full_url('records', rid, 'data'),
                            headers={'accept': 'application/json'}) as response:
            if response.content_type == 'application/json':
                response_dict = await response.json()
                if 'error' in response_dict:
                    error = response_dict['error']
                    raise VJ4Error(error.get('name', 'unknown'),
                                   error.get('message', ''),
                                   *error.get('args', []))
                raise Exception('unexpected response')
            if response.status != 200:
                raise Exception('http error ' + str(response.status))
            return await response.read()
