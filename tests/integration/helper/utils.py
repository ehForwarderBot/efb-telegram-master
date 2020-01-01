from typing import Tuple, Optional


def parse_socks5_link(link: str) -> Tuple[str, int, Optional[str], Optional[str]]:
    """Parse a SOCKS5 link, and extract the
    host name, port, username and password.

    Returns:
        host name, port, username, password
    """

    if not link.lower().startswith('socks5://'):
        raise ValueError(f"{link} is not a valid SOCKS5 link.")

    link = link[len('socks5://'):].rstrip('/')
    split_1 = link.split('@', 1)
    if len(split_1) == 1:
        auth = None
        host = split_1[0]
    else:
        auth, host = split_1

    hostname: str
    port: int
    username: Optional[str]
    password: Optional[str]

    if auth:
        username, password = auth.split(':')
    else:
        username = password = None

    if ':' in host:
        split_2 = host.split(':', 1)
        hostname = split_2[0]
        port = int(split_2[1])
    else:
        hostname = host
        port = 1080

    return hostname, port, username, password
