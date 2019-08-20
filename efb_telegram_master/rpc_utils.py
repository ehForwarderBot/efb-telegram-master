import threading
from typing import TYPE_CHECKING, KeysView, Optional, Iterable
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

from ehforwarderbot import coordinator, EFBChannel, EFBChat
from ehforwarderbot.types import ModuleID

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
            rpc_paths = ('/RPC2',)

        server_addr = rpc_config['server']
        port = rpc_config['port']

        self.server = SimpleXMLRPCServer((server_addr, port),
                                         requestHandler=RequestHandler)

        self.server.register_introspection_functions()
        self.server.register_multicall_functions()
        self.server.register_instance(self.channel.db)
        self.server.register_function(self.get_slave_channels_id)
        self.server.register_function(self.get_slave_channel_by_id)
        self.server.register_function(self.get_chats_from_channel_by_id)

        threading.Thread(target=self.server.serve_forever)

    def shutdown(self):
        """Shutdown RPC server if running."""
        if self.server:
            self.server.shutdown()

    @staticmethod
    def get_slave_channels_id() -> KeysView[str]:
        """Get the collection of slave channel IDs in current instance"""
        return coordinator.slaves.keys()

    @staticmethod
    def get_slave_channel_by_id(channel_id: ModuleID) -> Optional[EFBChannel]:
        """
        Get the slave channel instance if available. Otherwise return None.

        Args:
            channel_id: ID of the slave channel.
        """
        if channel_id in coordinator.slaves:
            return coordinator.slaves[channel_id]
        return None

    @staticmethod
    def get_chats_from_channel_by_id(channel_id: ModuleID) -> Optional[Iterable[EFBChat]]:
        """
        Get a list of chats from a specific slave channel if available.
        Otherwise return None.

        Args:
            channel_id: ID of the slave channel.
        """
        channel = RPCUtilities.get_slave_channel_by_id(channel_id)
        if channel:
            return channel.get_chats()
        return None
