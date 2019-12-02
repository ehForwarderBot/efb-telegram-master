import os


def get_env(key):
    val = os.getenv(key.upper())
    if val:
        return val
    raise ValueError(f"{key} is not defined")


def get_bot():
    return {
        'token': get_env('token'),
        'admins': get_env('admins').split(','),
        'groups': get_env('groups').split(','),
        'channels': get_env('channels').split(',')
    }
