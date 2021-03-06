import logging; logging.basicConfig(level=logging.INFO)
import asyncio, os, json, time
from aiohttp import web
from datetime import datetime

from jinja2 import Environment, FileSystemLoader

from coreweb import *
import orm
from handlers import cookie2user, COOKIE_NAME
from config import configs

#def index(request):
	#return web.Response(body=b'<h1>Awesome</h1>', content_type='text/html')

def init_jinja2(app, **kw):
    logging.info('init jinja2...')
    options = dict(
        autoescape = kw.get('autoescape', True),
        block_start_string = kw.get('block_start_string', '{%'),	#定义html中如何写python
        block_end_string = kw.get('block_end_string', '%}'),
        variable_start_string = kw.get('variable_start_string', '{{'),	#定义html中如何写变量
        variable_end_string = kw.get('variable_end_string', '}}'),
        auto_reload = kw.get('auto_reload', True)
    )
    path = kw.get('path', None)
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')	#模板所在路径
    logging.info('set jinja2 template path: %s' % path)
    env = Environment(loader=FileSystemLoader(path), **options)	#初始化jinja2
    filters = kw.get('filters', None)
    if filters is not None:
        for name, f in filters.items():
            env.filters[name] = f
    app['__templating__'] = env

#计算传入的时间是多久之前 jinja2的filter
def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:	#小于1分钟
        return u'1分钟前'
    if delta < 3600:	#小于1小时
        return u'%s分钟前' % (delta // 60)
    if delta < 86400: #小于1天
        return u'%s小时前' % (delta // 3600)
    if delta < 604800: #小于7天
        return u'%s天前' % (delta // 86400)
    dt = datetime.fromtimestamp(t)
    return u'%s年%s月%s日' % (dt.year, dt.month, dt.day)

#拦截器-日志
async def logger_factory(app, handler):
	async def logger(request):
		# 记录日志:
		logging.info('Request: %s %s' % (request.method, request.path))
		# 继续处理请求:
		return (await handler(request))
	return logger

#拦截器-解析cookie 把里面的user绑定到request上 cookie验证的逻辑：
#每个url请求都去验证cookie 如果cookie有效 再从cookie中解析user 因为每个url都要做 所以写成拦截器
async def auth_factory(app, handler):
    async def auth(request):
        logging.info('check user: %s %s' % (request.method, request.path))
        request.__user__ = None
        cookie_str = request.cookies.get(COOKIE_NAME) #获取cookie
        if cookie_str:
            user = await cookie2user(cookie_str)
            if user:
                logging.info('set current user: %s' % user.email)
                request.__user__ = user
        if request.path.startswith('/manage/') and (request.__user__ is None or not request.__user__.admin):    #如果访问/manage/ 检查身份是否为管理员
            return web.HTTPFound('/signin')
        return (await handler(request))
    return auth

#拦截器-解析数据到__data__
async def data_factory(app, handler):
    async def parse_data(request):
        if request.method == 'POST':
            if request.content_type.startswith('application/json'):
                request.__data__ = await request.json()
                logging.info('request json: %s' % str(request.__data__))
            elif request.content_type.startswith('application/x-www-form-urlencoded'):
                request.__data__ = await request.post()
                logging.info('request form: %s' % str(request.__data__))
        return (await handler(request))
    return parse_data

#拦截器-把返回值转换为web.Response对象再返回，以保证满足aiohttp的要求
async def response_factory(app, handler):
    async def response(request):
        logging.info('Response handler... ')
        r = await handler(request)  #拦截器的概念 request的时候到这里，当response后，接着执行下面的语句 和java中的一模一样
        if isinstance(r, web.StreamResponse):   #web.Response()是web.StreamResponse类型对象 所以如果自己返回了web.Response()就不用处理了。
            return r
        if isinstance(r, bytes):
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        if isinstance(r, str):
            if r.startswith('redirect:'):
                return web.HTTPFound(r[9:])
            resp = web.Response(body=r.encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
        if isinstance(r, dict):
            template = r.get('__template__')
            if template is None:    #如果直接返回一个dict，又没有指定模板，那就当作是rest api 把类型设置成json
                resp = web.Response(body=json.dumps(r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8'))
                resp.content_type = 'application/json;charset=utf-8'
                return resp
            else:   #有模板，就当作html处理
                r['__user__'] = request.__user__    #把拦截器处理的__user__ 自动加上
                resp = web.Response(body=app['__templating__'].get_template(template).render(**r).encode('utf-8'))
                resp.content_type = 'text/html;charset=utf-8'
                return resp
        if isinstance(r, int) and r >= 100 and r < 600:
            return web.Response(r)
        if isinstance(r, tuple) and len(r) == 2:
            t, m = r
            if isinstance(t, int) and t >= 100 and t < 600:
                return web.Response(t, str(m))
        # default:
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp
    return response

async def init(loop):
    await orm.create_pool(loop=loop, **configs.db)
    app = web.Application(middlewares=[
        logger_factory, auth_factory, response_factory
    ])
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    add_routes(app, 'handlers')
    add_static(app)
    srv = await loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    # web.run_app(app, host='127.0.0.1', port=9000)
    logging.info('server started at http://127.0.0.1:9000...')
    return srv

loop = asyncio.get_event_loop()
loop.run_until_complete(init(loop))
loop.run_forever()


