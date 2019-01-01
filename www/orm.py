import asyncio, aiomysql, logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(filename)s[line:%(lineno)d] - %(levelname)s: %(message)s')  # 设置日志级别

#创建数据库连接池
async def create_pool(loop, **kw):
    logging.info('创建数据库连接池...')
    global __pool
    __pool = await aiomysql.create_pool(
        host = kw.get('host', 'localhost'),
        port = kw.get('port', 3306),
        user = kw['user'],
        password = kw['password'],
        db = kw['db'],
        charset = kw.get('charset', 'utf8'),
        autocommit = kw.get('autocommit', True),    #自动提交
        maxsize = kw.get('maxsize', 10),
        minsize = kw.get('minsize', 1),
        loop=loop
    )

#select
async def select(sql, args, size=None):
    logging.info('查询sql: %s' % sql)
    global __pool
    async with __pool.get() as conn: #从连接池获取一个数据库连接 这里写with await __pool.get()也可以
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql.replace('?', '%s'), args or ())
            if size:
                rs = await cur.fetchmany(size)
            else:
                rs = await cur.fetchall()
        logging.info('返回行数：%s' % len(rs))
        return rs

#insert delete update通用
async def execute(sql, args, autocommit=True):
    logging.info('sql: %s' % sql)
    global __pool
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', '%s'), args or ()) #如果sql执行失败 就回滚
                affected = cur.rowcount
                if not autocommit:
                    conn.commit()
        except BaseException as e:
            if not autocommit:
                await conn.rollback()
            raise
        return affected

#orm框架
class Field(object):
    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type      #数据库中表的字段名
        self.primary_key = primary_key      #是否主键
        self.default = default              #默认值

    def __str__(self):
        return '<%s,%s:%s>' % (self.__class__.__name__, self.column_type, self.name)

class StringField(Field):
    def __init__(self, name=None, primary_key=False, default=None, ddl='varchar(100)'): #字符串长度不一定，所以要可以改变
        super().__init__(name, ddl, primary_key, default)

class BooleanField(Field):
    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default) #布尔类型无法做主键

class IntegerField(Field):
    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)

class FloatField(Field):
    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)

class TextField(Field):
    def __init__(self, name=None, default=None):
        super().__init__(name, 'text', False, default) #varchar可以设置最大长度，text不设置长度

#创建带参数的sql语句中的参数
def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)
#具体做映射的元类
class ModelMetaclass(type):
    def __new__(cls, name, bases, attrs):
        if name == 'Model':
            return type.__new__(cls, name, bases, attrs)
        #获取表名
        tableName = attrs.get('__table__', None) or name #继承了Model的类 如果有__table__就作为表名 没有就用类名做表名
        logging.info('建立映射：%s(table: %s)' % (name, tableName))
        #获取所有列和主键
        mappings = dict()
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info('建立映射：%s==>%s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    if primaryKey:
                        raise RuntimeError('重复定义主键:字段%s' % k)
                    primaryKey = k
                else:
                    fields.append(k)
        if not primaryKey:
            raise RuntimeError('没有定义主键')
        # 删除静态属性
        for k in mappings.keys():
            attrs.pop(k)
        attrs['__mappings__'] = mappings #保存属性和列的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey #主键属性名
        attrs['__fields__'] = fields #除主键外的属性名
        #构建crud参数的语句
        escaped_fields = list(map(lambda f: '`%s`' % f, fields)) #``用来保证和mysql中的关键字不冲突
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primaryKey, ','.join(escaped_fields), tableName) #select * from tableName
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ','.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1)) #insert into tableName (*) values (?,?,?...)
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s`=?' % (mappings.get(f).name or f), fields)), primaryKey) #update tableName set f1=?, f2=?... where primaryKey =?
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey) #delete from tableName where primaryKey =?

        return type.__new__(cls, name, bases, attrs)

#orm中用于实体类继承的基类 提供增删改查的方法
class Model(dict, metaclass=ModelMetaclass):
    def __init__(self, **kw):
        super().__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model'没有属性 '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        return getattr(self, key, None)

    def getValueOrDefault(self, key):   #ModelMetaclass中获取了映射，所有属性，但是创建Model子类实例时，不一定传入了所有属性，当获取没有传入的属性时，调用此方法获取默认值
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default #默认值可以是值，也可以是函数，比如日期，id等的计算函数
                logging.debug('使用默认值 %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value

    @classmethod
    async def find(cls, pk):    #查询方法与具体实例无关，设置为类方法 所以self也就换成了cls
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)   #select * from tableName where primaryKey = ?
        if len(rs) == 0:
            return None
        return cls(**rs[0]) #查询到的数据是dict的list 使用关键字参数传入第一个dict 然后创建一个Model子类实例

    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None): #这个就是查询某一个字段
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args,1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']  #查询到的数据是dict的list 加上[0]和[__num__]用于查询总数

    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))
        args.append(self.getValueOrDefault(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warning('插入失败: 受影响行数: %s' % rows)

    async def remove(self):
        args = [self.getValue(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warning('删除失败: 受影响行数: %s' % rows)

    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warning('更新失败: 受影响行数: %s' % rows)