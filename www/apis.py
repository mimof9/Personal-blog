import json, logging, inspect, functools

#分页 提供数据总数和分页大小 并指定第几页 然后Page就会计算sql的 offset和limit 并且判断是否有下一页或上一页
class Page(object):

    def __init__(self, item_count, page_index=1, page_size=5):
        self.item_count = item_count #数据总数
        self.page_size = page_size  #分页大小
        self.page_count = item_count // page_size + (1 if item_count % page_size > 0 else 0) #需要页数
        if item_count <=  0 or page_index > page_size: #传进来的值不合法
            self.page_index = 1
            self.offset = 0
            self.limit = 0
        else:
            self.page_index = page_index
            self.offset = (page_index - 1) * page_size #当前页的偏移量 单位是数据条数
            self.limit = self.page_size #offset和limit主要是用来提供给 sql语句进行分页查询的
        self.has_next = self.page_index < self.page_count
        self.has_previous = self.page_index > 1

    def __str__(self):
        return 'item_count: %s, page_count: %s, page_index: %s, page_size: %s, offset: %s, limit: %s' \
               % (self.item_count, self.page_count, self.page_index, self.page_size, self.offset, self.limit)

    __repr__ = __str__

class APIError(Exception):
    '''
    the base APIError which contains error(required), data(optional) and message(optional).
    '''
    def __init__(self, error, data='', message=''):
        super(APIError, self).__init__(message)
        self.error = error
        self.data = data
        self.message = message

class APIValueError(APIError):
    '''
    Indicate the input value has error or invalid. The data specifies the error field of input form.
    '''
    def __init__(self, field, message=''):
        super(APIValueError, self).__init__('value:invalid', field, message)

class APIResourceNotFoundError(APIError):
    '''
    Indicate the resource was not found. The data specifies the resource name.
    '''
    def __init__(self, field, message=''):
        super(APIResourceNotFoundError, self).__init__('value:notfound', field, message)

class APIPermissionError(APIError):
    '''
    Indicate the api has no permission.
    '''
    def __init__(self, message=''):
        super(APIPermissionError, self).__init__('permission:forbidden', 'permission', message)