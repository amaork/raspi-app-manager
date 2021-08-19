# -*- coding: utf-8 -*-
import abc
import time
import ping3
import raspi_io
from framework.misc.parallel import ParallelOperate
__all__ = ['RaspiOperate', 'RebootOperate', 'LocalUpdate', 'JoinWirelessNetwork', 'LeaveWirelessNetwork']


class RaspiOperate(ParallelOperate):
    @abc.abstractmethod
    def _operate(self, *args, **kwargs):
        pass


class RebootOperate(RaspiOperate):
    def _operate(self, index: int, address: str):
        query = raspi_io.Query(address)
        query.reboot_system(delay=3)
        time.sleep(3)
        t0 = time.perf_counter()
        while time.perf_counter() - t0 < 10:
            if ping3.ping(dest_addr=address, timeout=1) is None:
                return True

        return False


class LocalUpdate(RaspiOperate):
    def _operate(self, index: int, address: str, update_package: str, update_path: str):
        agent = raspi_io.UpdateAgent(address, timeout=300)
        return agent.update_from_local(update_package, update_path)


class JoinWirelessNetwork(RaspiOperate):
    def _operate(self, index: int, address: str, network: dict):
        wireless = raspi_io.Wireless(address)
        return wireless.join_network(**network)


class LeaveWirelessNetwork(RaspiOperate):
    def _operate(self, index: int, address: str, network_name: str):
        wireless = raspi_io.Wireless(address)
        if network_name not in wireless.get_networks():
            raise RuntimeError(f'Network {network_name!r} is not exist')

        return wireless.leave_network(network_name)
