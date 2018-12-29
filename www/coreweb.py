import functools, asyncio, logging
import inspect, os
from aiohttp import web
from urllib import parse
from apis import APIError

#带参数的装饰器 把url和请求方式封装到函数中去
def get(path):
    def decorator(func):
        @functools.wraps(func)
        def wapper(*args, **kw):
            return func(*args, **kw)
        wapper.__method__ = 'GET'
        wapper.__route__ = path
        return wapper
    return decorator

def post(path):
    def decorator(func):
        @functools.wraps(func)
        def wapper(*args, **kw):
            return func(*args, **kw)
        wapper.__method__ = 'POST'
        wapper.__route__ = path
        return wapper
    return decorator

#给服务器添加路由,也就是url映射到处理函数 注意到 封装的路由不用提供url 因为fn被装饰了 自带url。然后再写一个add_routes()添加所有被装饰的fn。路由设置就只需要一句代码了。
def add_route(app, fn):
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if method is None or path is None:      #确保处理函数被@get或@post装饰，以便获取url
        raise ValueError('@get or @post not defined in %s' % str(fn))
    if not asyncio.iscoroutine(fn) and not inspect.isgeneratorfunction(fn): #把处理函数变为协程
        fn = asyncio.coroutine(fn)
    logging.info('add route %s %s ==> %s(%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    app.router.add_route(method, path, RequestHandler(app, fn))  #调用aiohttp的路由


#把模块下的所有被@get或@post装饰过的函数 注册路由
def add_routes(app, module_name):
    n = module_name.rfind('.') #最后一个.的索引
    #mod = __import__(module_name, globals(), locals(), [module_name[n+1:]])  #导入模块
    if n == (-1):
        mod = __import__(module_name, globals(), locals())
    else:
        name = module_name[n + 1:]
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    for attr in dir(mod):
        if attr.startswith('_'):
            continue
        fn = getattr(mod, attr) #根据key去找到对象
        if callable(fn):
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)

#POSITIONAL_ONLY	      仅位置参数
#POSITIONAL_OR_KEYWORD   位置参数和命名关键字参数
#VAR_POSITIONAL           可变位置参数  *args
#KEYWORD_ONLY             仅命名关键字参数   （官方就叫做关键字参数）
#VAR_KEYWORD               关键字参数 **kw   (官方叫做可变关键字参数)

#获取没有默认值的关键字参数
def get_required_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)

#获取所有关键字参数
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)

#是否有关键字参数
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True
    return False

#是否有可变关键字参数
def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True
    return False

#查找是否有参数 fn是否有request参数 因为这是aiohttp框架的要求
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL and param.kind != inspect.Parameter.KEYWORD_ONLY and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError('request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    return found

#RequestHandler最终还是调用fn函数去处理url，不过处理url之前，因为我们想自动从request中获取参数，所以就用RequestHandler来自动获取参数**kw。
#下面写了一大堆，都是自动获取参数而已。 就像spring mvc做的那样
class RequestHandler(object):

    def __init__(self, app, fn):
        self._app = app
        self._func = fn
        #获取fn的参数详情， 只有获取了处理函数的参数，才能在request中获取争取的参数，然后调用处理函数
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)

    # 注册路由的时候，传进去的处理函数都是RequestHandler(fn)，也就是url都会调用RequestHandler()来处理，所以需要重写__call__方法
    async def __call__(self, request):
        kw = None
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args: #处理函数 有关键字参数或**args
            if request.method == 'POST':
                if not request.content_type:                #请求没有设置content_type
                    return web.HTTPBadRequest('Missing Content-Type.')
                ct = request.content_type.lower()
                if ct.startswith('application/json'):       #提交的内容是json格式
                    params = await request.json()
                    if not isinstance(params, dict):
                        return web.HTTPBadRequest('JSON body must be object.')
                    kw = params
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'): #表单默认格式或者二进制格式
                    params = await request.post() #获取请求数据
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest('Unsupported Content-Type: %s' % request.content_type)
            if request.method == 'GET':
                qs = request.query_string   #获取url?后面的参数
                if qs:
                    kw = dict()
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
        if kw is None:
            kw = dict(**request.match_info) #None 就直接添加match_info的值
        else:
            if not self._has_var_kw_arg and self._named_kw_args: #第一个if不够精准，进一步判断，没有可变关键字参数并且有没有默认值的关键字参数
                #删除所有有默认值的关键字参数，因为有默认值了 不需要了
                copy = dict()
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            # check named arg:  把match_info的值添加进去
            for k, v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        if self._has_request_arg:
            kw['request'] = request
            # check required kw:
        if self._required_kw_args:
            for name in self._required_kw_args:
                if not name in kw:
                    return web.HTTPBadRequest('Missing argument: %s' % name)
        logging.info('call with args: %s' % str(kw))
        try:
            r = await self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)

#设置静态文件目录
def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))