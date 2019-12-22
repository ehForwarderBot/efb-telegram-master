import os


def get_env(key):
    val = os.getenv(key.upper())
    if val:
        return val
    raise ValueError(f"{key} is not defined")


def get_bot():
    return {
        'token': get_env('token'),
        'admins': list(map(int, get_env('admins').split(','))),
        'groups': list(map(int, get_env('groups').split(','))),
        'channels': list(map(int, get_env('channels').split(',')))
    }


def get_user_session():
    return {
        'user_session': get_env('user_session'),
        'api_id': int(get_env('api_id')),
        'api_hash': get_env('api_hash')
    }
