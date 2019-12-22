from pytest import fixture


@fixture(scope="module")
def rpc(channel):
    return channel.rpc_utilities


def test_rpc_channels_id(rpc, coordinator):
    assert set(coordinator.slaves.keys()) == set(rpc.get_slave_channels_ids())
