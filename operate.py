# -*- coding: utf-8 -*-
import abc
import time
import ping3
import raspi_io
from typing import Callable, Optional
from framework.misc.settings import UiLogMessage
from framework.misc.parallel import ParallelOperate
from framework.network.utility import wait_device_reboot
__all__ = ['RaspiOperate', 'InstallUserApp', 'UninstallUserApp', 'Reboot', 'GetAppState',
           'LocalUpdate', 'OnlineUpdate', 'JoinWirelessNetwork', 'LeaveWirelessNetwork']


class RaspiOperate(ParallelOperate):
    def __init__(self, logging: Optional[Callable[[UiLogMessage], None]] = None, callback: Optional[Callable] = None):
        super(RaspiOperate, self).__init__(logging, callback)
        self.current_row = -1

    @abc.abstractmethod
    def _operate(self, *args, **kwargs):
        pass

    def _format_log(self, msg: str):
        return msg

    def logging(self, msg: UiLogMessage):
        """Show message on gui

        :param msg: msg content
        :return:
        """
        if callable(self._logging) and isinstance(msg, UiLogMessage):
            self._logging(msg, self.current_row)

    def run(self, *args, **kwargs):
        try:
            self.current_row = args[0]
            result = self._operate(*args, **kwargs)
        except Exception as e:
            result = f'{e}'
            print(f'{self.__class__.__name__!r} operate error: {e}')
            self.errorLogging(f'{self.__class__.__name__!r} operate error: {e}')

        self.callback(result, *args)
        return result


class Reboot(RaspiOperate):
    def _operate(self, index: int, address: str) -> bool:
        query = raspi_io.Query(address)
        query.reboot_system(delay=3)
        time.sleep(3)
        return all(wait_device_reboot(address))


class GetAppState(RaspiOperate):
    def _operate(self, index: int, address: str, app_name: str) -> dict:
        manager = raspi_io.AppManager(address, timeout=300)
        return manager.get_app_state(app_name)


class LocalUpdate(RaspiOperate):
    def _operate(self, index: int, address: str, app_name: str, update_package: str) -> dict:
        manager = raspi_io.AppManager(address, timeout=300)
        if app_name not in manager.get_app_list():
            raise RuntimeError(f"App {app_name!r} is not installed, please install app first")
        return manager.local_update(update_package, app_name)


class OnlineUpdate(RaspiOperate):
    def _operate(self, index: int, address: str, auth: dict, release: dict, repo: str) -> dict:
        manager = raspi_io.AppManager(address, timeout=300)
        return manager.online_update(auth, release, repo)


class InstallUserApp(RaspiOperate):
    def _operate(self, index: int, address: str, package: str, desc: dict) -> dict:
        manager = raspi_io.AppManager(address, timeout=300)
        return manager.install(package, **desc)


class UninstallUserApp(RaspiOperate):
    def _operate(self, index: int, address: str, app_name: str) -> bool:
        manager = raspi_io.AppManager(address, timeout=300)
        return manager.uninstall(app_name)


class JoinWirelessNetwork(RaspiOperate):
    def _operate(self, index: int, address: str, network: dict) -> bool:
        wireless = raspi_io.Wireless(address)
        return wireless.join_network(**network)


class LeaveWirelessNetwork(RaspiOperate):
    def _operate(self, index: int, address: str, network_name: str) -> bool:
        wireless = raspi_io.Wireless(address)
        if network_name not in wireless.get_networks():
            raise RuntimeError(f'Network {network_name!r} is not exist')

        return wireless.leave_network(network_name)
