# coding: utf-8
# modified from [messud4312]https://my.oschina.net/u/914655/blog/1799159

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
        val = self.weak.get(key, None)
        if val is not None:
            expire = val['expire']
            value = val['value']
            if self.now_time() > expire:
                return None
            else:
                return value
        else:
            return None

    def set(self, key, value, expire=3600):
        # strong_ref prevent object from being collected by gc.
        self.weak[key] = strong_ref = LocalCache.Dict({
            'expire': self.now_time() + expire,
            'value': value
        })
        # Enqueue the element and waiting to be collected by gc once popped.
        self.strong.append(strong_ref)

    def remove(self, key):
        return self.weak.pop(key, None)
