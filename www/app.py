import logging; logging.basicConfig(level=logging.INFO)
import asyncio, os, json, time
from aiohttp import web
from datetime import datetime

def index(request):
	return web.Response(body=b'<h1>Awesome</h1>', content_type='text/html')

def init():
	app = web.Application()
	app.router.add_route('GET', '/', index)
	web.run_app(app, host='127.0.0.1', port=9000)
	print('服务器启动，监听端口9000')

init()

