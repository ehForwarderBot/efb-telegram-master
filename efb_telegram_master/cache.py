# coding: utf-8

import collections
import time
import weakref

class LocalCache():

    # Wrapping dict as it requires subclassing for weak reference.
    class Dict(dict):
        def __del__(self):
            pass

    def __init__(self, maxlen=20):
        self.weak = weakref.WeakValueDictionary()
        self.strong = collections.deque(maxlen=maxlen)

    @staticmethod
    def now_time():
        return int(time.time())

    def get(self, key):
        _ = self.weak.get(key, self.notFound)
        if _ is not self.notFound:
            expire = _['expire']
            value = _[r'value']
            if self.nowTime() > expire:
                return self.notFound
            else:
                return value
        else:
            return self.notFound

    def set(self, key, value, expire):
        # strong_ref prevent object from being collected by gc.
        self.weak[key] = strongRef = LocalCache.Dict({
            'expire': self.nowTime() + expire,
            'value': value
        })
        # Enqueue the element and waiting to be collected by gc once popped.
        self.strong.append(strongRef)

    def remove(self, key):
        return self.weak.pop(key)

CACHE = LocalCache()


def get(key):
    return CACHE.get(key)

def set(key, value, expire=3600):
    CACHE.set(key, value, expire)

def remove(key):
    return CACHE.remove(key)
