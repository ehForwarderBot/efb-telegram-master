import threading
from typing import TYPE_CHECKING, Optional, List
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

from ehforwarderbot import coordinator

if TYPE_CHECKING:
    from . import TelegramChannel


class RPCUtilities:
    """Useful functions exposed to RPC server"""

    server: Optional[SimpleXMLRPCServer] = None

    def __init__(self, channel: 'TelegramChannel'):
        self.channel = channel

        rpc_config = self.channel.config.get('rpc')
        if not rpc_config:
            return

        # Restrict to a particular path.
        class RequestHandler(SimpleXMLRPCRequestHandler):
            rpc_paths = ('/', '/RPC2')

        server_addr = rpc_config['server']
        port = rpc_config['port']

        self.server = SimpleXMLRPCServer((server_addr, port),
                                         requestHandler=RequestHandler)

        self.server.register_introspection_functions()
        self.server.register_multicall_functions()
        self.server.register_instance(self.channel.db)
        self.server.register_function(self.get_slave_channels_ids)

        threading.Thread(target=self.server.serve_forever, name="ETM RPC server thread")

    def shutdown(self):
        """Shutdown RPC server if running."""
        if self.server:
            self.server.shutdown()

    @staticmethod
    def get_slave_channels_ids() -> List[str]:
        """Get the collection of slave channel IDs in current instance"""
        return list(coordinator.slaves.keys())

    # TODO: add more utilities that could be useful for RPC?
