# -*- coding: utf-8 -*-
import os
import sys
import ping3
import threading
import collections
from PySide.QtGui import *
from PySide.QtCore import *
from typing import Optional, List, Callable, Union, Any, ClassVar

from raspi_io.utility import scan_server
from raspi_io import UpdateAgent, Query, Wireless, RaspiException

import version
import resources_rc
from operate import *
from configure import *

from framework.core.datatype import DynamicObject
from framework.core.threading import ThreadLockAndDataWrap

from framework.misc.settings import UiLogMessage
from framework.misc.windpi import get_program_scale_factor
from framework.misc.parallel import BackgroundOperateLauncher, ConcurrentLauncher

from framework.gui.msgbox import *
from framework.gui.checkbox import CheckBoxDelegate
from framework.gui.widget import BasicWidget, TableWidget
from framework.gui.dialog import showFileImportDialog, showFileExportDialog, \
    MultiGroupJsonSettingsDialog, ProgressDialog


Device = collections.namedtuple('Device', ['row', 'address'])


class RaspberryPiUpdateTools(QMainWindow):
    signalLogging = Signal(UiLogMessage)

    signalMarkDeviceAsIdle = Signal(Device)
    signalFoundDevice = Signal(RaspberryPiInfo)
    signalUpdateProgress = Signal(int, str, object)

    signalUpdateIOSVersion = Signal(int, float)
    signalUpdateAppVersion = Signal(int, float, str)

    ACTION_GROUP = collections.namedtuple('Action', ['SCAN', 'NETWORK', 'USER_APP', 'IOS_APP', 'SYSTEM'])(*range(5))
    COLUMN = collections.namedtuple('Column', [
        'SEL', 'REV', 'SN', 'ETH', 'WLAN', 'IOS_VER', 'APP_VER', 'APP_STATE', 'OPERATE_RESULT'])(*range(9))

    def __init__(self):
        self.app_config = RaspberryPiSoftwareConfigure(
            username='python_bot',
            password='Xrj_88133810',
            host='http://frp.amaork.me:3000',
            software_repo='Outsourcing/raspi_kart',
            software_install=["raspi_kart", "/opt/kart"]
        )
        self.device_state = ThreadLockAndDataWrap(dict())
        self.scale_x, self.scale_y = get_program_scale_factor()
        self.ios_install = collections.namedtuple('APP', ['name', 'path'])(*('raspi_io_server', '/usr/local/sbin'))
        self.app_install = collections.namedtuple('APP', ['name', 'path'])(*(tuple(self.app_config.software_install)))
        super(RaspberryPiUpdateTools, self).__init__()
        self._initUi()
        self._initData()
        self._initMenu()
        self._initStyle()
        self._initSignalAndSlots()
        self._initThreadAndTimer()

    def _initUi(self):
        self.ui_address = QLineEdit()
        self.ui_table_content_menu = QMenu(self)
        self.ui_scan = QPushButton(self.tr("Scan"))
        self.ui_manual_add = QPushButton(self.tr("Manual Add"))
        self.ui_load = QPushButton(self.tr("Load User App Configure"))
        self.ui_progress = ProgressDialog(self, closeable=False, max_width=self.__scale_width(400))

        self.ui_table = TableWidget(len(self.COLUMN), disable_custom_content_menu=True, parent=self)
        self.ui_table.setColumnHeader((
            self.tr("Sel"),
            self.tr("Revision"), self.tr("Serial Number"), self.tr("Ethernet"), self.tr("Wireless"),
            self.tr("IOS Ver"), self.tr("App Ver"), self.tr("App State"), self.tr("Operate Result")
        ))

        tools_layout = QHBoxLayout()
        for item in (self.ui_scan, self.ui_load, QLabel("Address"), self.ui_address, self.ui_manual_add):
            tools_layout.addWidget(item)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.ui_table)

        widget = QWidget(self)
        widget.setLayout(layout)
        self.setCentralWidget(widget)

    def _initData(self):
        pass

    def _initMenu(self):
        self.menu_bar = QMenuBar(self)
        self.setMenuBar(self.menu_bar)

        sub_menu = collections.namedtuple('menu', ['name', 'slot', 'shortcut'])
        separator = sub_menu(name='separator', slot=None, shortcut=None)

        for menu, actions in {
            sub_menu(name=self.tr('File'), slot=None, shortcut=None): [
                sub_menu(name='Load App Desc', shortcut='Ctrl+L', slot=None),
                separator,
                sub_menu(name='Quit', shortcut='Ctrl+Q', slot=lambda: sys.exit())
            ],

            sub_menu(name=self.tr('RPi'), slot=None, shortcut=None): [
                sub_menu(name='Scan', shortcut='F5', slot=self.slotScan),
                sub_menu(name='Reboot', shortcut='Alt+F9', slot=self.slotRebootSystem),
                sub_menu(name='Update IO Server', shortcut='Alt+F2', slot=self.slotUpdateIOServer),
                separator,
                sub_menu(name='Install User App', shortcut='Ctrl+Alt+I', slot=None),
                sub_menu(name='Uninstall User App', shortcut='Ctrl+Alt+U', slot=None),
            ],

            sub_menu(name=self.tr('Wireless'), slot=None, shortcut=None): [
                sub_menu(name='Join Network', shortcut=None, slot=self.slotJoinWireless),
                sub_menu(name='Leave Network', shortcut=None, slot=self.slotLeaveWireless),
                # separator,
                # sub_menu(name='Backup WPA Configure', shortcut=None, slot=self.slotBackupWireless),
                # sub_menu(name='Restore WPA Configure', shortcut=None, slot=self.slotRestoreWireless),
            ],

            sub_menu(name=self.tr('App'), slot=None, shortcut=None): [
                sub_menu(name='Local Update', shortcut=None, slot=self.slotLocalUpdate),
                sub_menu(name='Online Update', shortcut=None, slot=self.slotOnlineUpdate),
                separator,
                sub_menu(name='Upload App Configures', shortcut=None, slot=None),
                sub_menu(name='Download App Configure', shortcut=None, slot=None),
                separator,
                sub_menu(name='Backup Application and Data', shortcut=None, slot=None),
            ]
        }.items():
            root = QMenu(self)
            root.setTitle(menu.name)
            self.menu_bar.addMenu(root)

            for child in actions:
                if child.name == "separator":
                    root.addSeparator()
                    continue

                action = QAction(child.name, self)

                if callable(child.slot):
                    action.triggered.connect(child.slot)
                else:
                    continue

                if child.shortcut:
                    action.setShortcut(child.shortcut)

                root.addAction(action)

    def _initStyle(self):
        self.ui_table.setNoSelection()
        self.ui_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.ui_table.setColumnStretchFactor((0.02, 0.08, 0.16, 0.135, 0.135, 0.08, 0.08, 0.09))

        self.ui_table.setColumnMaxWidth(self.COLUMN.SEL, self.__scale_width(40))
        self.ui_table.setItemDelegateForColumn(
            self.COLUMN.SEL, CheckBoxDelegate(stylesheet=DynamicObject(sizeFactor=2.0), parent=self)
        )

        self.setWindowIcon(QPixmap(":ico/ico/raspi.ico"))
        self.setMinimumSize(QSize(self.__scale_width(800), self.__scale_height(600)))
        self.setWindowTitle(self.tr("Raspberry Pi App Manager {}".format(version.s_version)))

    def _initSignalAndSlots(self):
        self.ui_scan.clicked.connect(self.slotScan)
        self.ui_load.clicked.connect(self.slotLoadConfigure)
        self.ui_manual_add.clicked.connect(self.slotManualAddRaspberryPi)
        self.ui_table.customContextMenuRequested.connect(self.slotCustomTableContentMenu)

        self.signalLogging.connect(lambda x: print(x))

        self.signalUpdateProgress.connect(self.slotUpdateProcess)

        self.signalFoundDevice.connect(self.slotFoundNewRaspberryPi)
        self.signalMarkDeviceAsIdle.connect(self.slotMarkDeviceAsIdle)

        self.signalUpdateAppVersion.connect(self.slotUpdateAppVersion)
        self.signalUpdateIOSVersion.connect(self.slotUpdateIOSVersion)

    def _initThreadAndTimer(self):
        pass

    def __scale_width(self, width: int) -> int:
        return int(self.scale_x * width)

    def __scale_height(self, height: int) -> int:
        return int(self.scale_y * height)

    def __getCurrentRowSN(self, row: int) -> str:
        return self.ui_table.getItemData(row, self.COLUMN.SN) if  0 <= row < self.ui_table.rowCount() else ""

    def __getCurrentRowDevice(self, row: int) -> Device:
        address = self.ui_table.getItemData(row, self.COLUMN.ETH) or self.ui_table.getItemData(row, self.COLUMN.WLAN)
        return Device(row=row, address=address)

    def __markDeviceAsBusy(self, operate_name: str, operate_devices: List[Device]):
        for row, address in operate_devices:
            self.device_state.data[address] = operate_name
            self.ui_table.frozenItem(row, self.COLUMN.SEL, True)
            self.signalUpdateProgress.emit(row, operate_name, Qt.yellow)

    def __getCurrentOperateDevice(self, row: Optional[int]) -> List[Device]:
        # From content menu
        if row is not None:
            if not row <= 0 < self.ui_table.rowCount():
                showMessageBox(self, MB_TYPE_ERR, self.tr("Invalid row number") + f" :{row}")
                return list()

            return [self.__getCurrentRowDevice(row)]

        # From menu bar
        devices = [self.__getCurrentRowDevice(row)
                   for row in range(self.ui_table.rowCount())
                   if self.ui_table.getItemData(row, self.COLUMN.SEL)]

        if not devices:
            showMessageBox(self, MB_TYPE_ERR, self.tr("Please select device first"))
            return list()

        return devices

    def __updateSoftware(self, row: int, tag: str, title: str, update_path: str, callback: Callable):
        devices = self.__getCurrentOperateDevice(row)
        if not devices:
            return

        update_package = showFileImportDialog(self, fmt="Tar File (*.tar)", title=title)
        if not os.path.isfile(update_package):
            return

        args = [(row, address, update_package, update_path) for row, address in devices]
        self.__createConcurrentOperateThread(tag, devices, LocalUpdate, args, callback)

    def __createConcurrentOperateThread(self, operate_name: str, operate_devices: List[Device],
                                        operate_cls: ClassVar, operate_args: list, callback: Callable) -> bool:
        if not issubclass(operate_cls, RaspiOperate):
            return False

        operate_cnt = len(operate_args)
        self.ui_progress.setRange(0, operate_cnt + 1)
        operate = operate_cls(self.signalLogging.emit, callback)

        # Limit max works number
        max_workers = operate_cnt if operate_cnt <= 32 else 32
        launcher = ConcurrentLauncher(operate, max_workers=max_workers)
        launcher.run(operate_args)

        # Disable currently operating device
        self.__markDeviceAsBusy(operate_name, operate_devices)

        return True

    def slotScan(self):
        if any(self.device_state.data.values()):
            return showMessageBox(self, MB_TYPE_WARN, self.tr("Please wait device operating finished"))

        self.ui_table.setRowCount(0)
        th = threading.Thread(target=self.threadScanRaspberryPi)
        th.setDaemon(True)
        th.start()

    def slotLoadConfigure(self):
        pass

    def slotManualAddRaspberryPi(self):
        pass

    def slotMarkDeviceAsIdle(self, device: Device):
        self.ui_table.frozenItem(device.row, self.COLUMN.SEL, False)
        self.ui_table.setItemData(device.row, self.COLUMN.SEL, False)
        if device.address in self.device_state.data:
            self.device_state.data[device.address] = ""

    def slotFoundNewRaspberryPi(self, device_info: RaspberryPiInfo):
        if not isinstance(device_info, RaspberryPiInfo):
            return

        sn_list = self.ui_table.getColumnData(self.COLUMN.SN)

        if device_info.sn not in sn_list:
            row = self.ui_table.rowCount()
            self.ui_table.addRow(device_info.format_as_list())
        else:
            row = sn_list.index(device_info.sn)
            self.slotUpdateProcess(row, "", QColor(Qt.white))
            self.ui_table.setRowData(row, device_info.format_as_list())

        self.ui_table.frozenRow(row, True)
        self.ui_table.frozenItem(row, self.COLUMN.SEL, False)
        self.ui_table.setRowAlignment(row, Qt.AlignCenter)
        self.ui_table.openPersistentEditor(self.ui_table.item(row, self.COLUMN.SEL))

    def slotRebootSystem(self, row: Optional[int] = None):
        devices = self.__getCurrentOperateDevice(row)
        if not devices:
            return

        def callback(result: Union[bool, str], row_: int, address: str, *_args):
            result = result if isinstance(result, bool) else False
            self.callbackOperatingFinished(self.tr("Reboot"), result, row_, address)

        self.__createConcurrentOperateThread(self.tr("Rebooting"), devices, RebootOperate, devices, callback)

    def slotJoinWireless(self, row: Optional[int] = None):
        devices = self.__getCurrentOperateDevice(row)
        if not devices:
            return

        # Ask input network info
        network = MultiGroupJsonSettingsDialog.getData(UiJoinNetwork.default(), dict(), parent=self)
        if not network:
            return

        # Check network info
        if any([not network.get(x) for x in UiJoinNetwork.REQUIRED_OPTIONS]):
            names = ", ".join([UiJoinNetwork.default().dict.get(x).get('name')
                               for x in UiJoinNetwork.REQUIRED_OPTIONS])
            return showMessageBox(self, MB_TYPE_WARN, f'{names!r} ' + self.tr("are required"))

        network['scan_ssid'] = int(network['scan_ssid'])

        def callback(result: Union[bool, str], row_: int, address: str, *_args):
            result = result if isinstance(result, bool) else False
            self.callbackOperatingFinished(self.tr("Join") + f' {network["ssid"]!r}', result, row_, address)

        # Prepare parallel operate args list
        args = [(row, address, network) for row, address in devices]
        self.__createConcurrentOperateThread(self.tr("Join Network"), devices, JoinWirelessNetwork, args, callback)

    def slotLeaveWireless(self, row: Optional[int] = None):
        devices = self.__getCurrentOperateDevice(row)
        if not devices:
            return

        if len(devices) == 1:
            # Single device choose from device network list
            try:
                wireless = Wireless(devices[0].address)
                networks = wireless.get_networks()

                if not networks:
                    self.signalUpdateProgress.emit(row, self.tr('Network is empty'), Qt.green)
                    return

                network, selected = QInputDialog.getItem(
                    self, self.tr("Leave Wireless"), self.tr("Please select will leave network" + " " * 20), networks
                )

                if not selected or not network:
                    return
            except RaspiException as e:
                return showMessageBox(self, MB_TYPE_ERR, f"Get networks failed: {e}")
        else:
            # Multi device get network name from input
            network, inputted = QInputDialog.getText(
                self, self.tr("Leave Wireless"), self.tr("Please input will leave network ssid" + " " * 20)
            )

            if not inputted or not network:
                return

        def callback(result: Union[bool, str], row_: int, address: str, *_args):
            result = result if isinstance(result, bool) else False
            self.callbackOperatingFinished(self.tr("Left") + f' {network!r}', result, row_, address)

        self.__createConcurrentOperateThread(
            self.tr("Leaving Network"), devices,
            LeaveWirelessNetwork, [(row, address, network) for row, address in devices], callback
        )

    def slotBackupWireless(self, row):
        pass

    def slotRestoreWireless(self, row):
        pass

    def slotUpdateIOServer(self, row: Optional[int] = None):
        self.__updateSoftware(row, self.tr("Updating IOS"),
                              self.tr("Please select 'Raspi IO Server' update package"),
                              self.ios_install.path, self.callbackUpdateIOServer)

    def slotOnlineUpdate(self, row):
        pass

    def slotLocalUpdate(self, row: Optional[int] = None):
        title = self.tr("Please select") + " {!r} ".format(self.app_install.name) + self.tr("update package")
        self.__updateSoftware(row, self.tr("Local Updating"), title,self.app_install.path, self.callbackLocalUpdate)

    def slotCustomTableContentMenu(self, pos: QPoint):
        content_menu = QMenu(self)
        item = self.ui_table.itemAt(pos)
        if isinstance(item, QTableWidgetItem):
            device = self.__getCurrentRowDevice(item.row())
            if self.device_state.data.get(device.address):
                return

        for group, actions in {
            self.ACTION_GROUP.SCAN: [
                (QAction(self.tr("Scan"), self), self.slotScan)
            ],

            self.ACTION_GROUP.NETWORK: [
                (QAction(self.tr("Join Wireless"), self), lambda: self.slotJoinWireless(item.row())),
                (QAction(self.tr("Leave Wireless"), self), lambda: self.slotLeaveWireless(item.row())),
                # (QAction(self.tr("Backup Wireless"), self), lambda: self.slotBackupWireless(item.row())),
            ],

            self.ACTION_GROUP.USER_APP: [
                (QAction(self.tr("Update From Local"), self), lambda: self.slotLocalUpdate(item.row())),
            ],

            self.ACTION_GROUP.IOS_APP: [
                (QAction(self.tr("Update Raspi IO Server"), self), lambda: self.slotUpdateIOServer(item.row()))
            ],

            self.ACTION_GROUP.SYSTEM: [
                (QAction(self.tr("Reboot Raspberry Pi System"), self), lambda: self.slotRebootSystem(item.row()))
            ]
        }.items():
            for action, slot in actions:
                action.triggered.connect(slot)
                action.setProperty("group", group)

                if group != self.ACTION_GROUP.SCAN and item is None:
                    continue

                content_menu.addAction(action)

            content_menu.addSeparator()

        content_menu.popup(self.ui_table.viewport().mapToGlobal(pos))

    def slotUpdateIOSVersion(self, row: int, ver: float):
        self.ui_table.setItemData(row, self.COLUMN.IOS_VER, str(ver))

    def slotUpdateAppVersion(self, row: int, ver: float, state: str):
        self.ui_table.setItemData(row, self.COLUMN.APP_VER, str(ver))
        self.ui_table.setItemData(row, self.COLUMN.APP_STATE, state)

    def slotUpdateProcess(self, row: int, process: str, color: Union[Qt.GlobalColor, QColor]):
        self.ui_table.setItemData(row, self.COLUMN.OPERATE_RESULT, process)
        self.ui_table.setItemBackground(row, self.COLUMN.OPERATE_RESULT, QBrush(color))

    def callbackLocalUpdate(self, result: Any, row: int, address: str, *_args):
        if not isinstance(result, dict):
            self.signalUpdateProgress.emit(row, self.tr("Local Update Failed"), Qt.red)
        else:
            self.signalUpdateProgress.emit(row, self.tr("Local Update Success"), Qt.green)
            self.signalUpdateAppVersion.emit(row, result.get("version"), self.tr("Rebooting"))

        self.signalMarkDeviceAsIdle.emit(Device(row, address))

    def callbackUpdateIOServer(self, result: Any, row: int, address: str, *_args):
        if not isinstance(result, dict):
            self.signalUpdateProgress.emit(row, self.tr("IOS Update Failed"), Qt.red)
        else:
            self.signalUpdateIOSVersion.emit(row, result.get("version"))
            self.signalUpdateProgress.emit(row, self.tr("IOS Update Success"), Qt.green)

        self.signalMarkDeviceAsIdle.emit(Device(row, address))

    def callbackOperatingFinished(self, operate: str, result: bool, row: int, address: str):
        self.signalMarkDeviceAsIdle.emit(Device(row, address))
        result_str = self.tr('Success') if result else self.tr("Failed")
        self.signalUpdateProgress.emit(row, f'{operate} {result_str}', Qt.green if result else Qt.red)

    def threadScanRaspberryPi(self, timeout: float = 0.05):
        for address in scan_server(timeout=timeout):
            th = threading.Thread(target=self.threadFetchRaspberryPiInfo, kwargs=dict(address=address))
            th.setDaemon(True)
            th.start()

    def threadFetchRaspberryPiInfo(self, address: str):
        try:
            query = Query(address)
            agent = UpdateAgent(address)

            ethernet, wireless = address, ''
            _, revision, sn = query.get_hardware_info()
            ifc_list = query.get_iface_list()

            for interface in ifc_list:
                if 'eth0' == interface:
                    ethernet = query.get_ethernet_addr(interface)
                else:
                    wireless = query.get_ethernet_addr(interface)

            ethernet = ethernet or address
            device = RaspberryPiInfo(revision=revision, sn=sn,
                                     ethernet=ethernet, wireless=wireless,
                                     ios_version=query.get_version().get("server"),
                                     software_version=agent.get_software_version(*self.app_install))
            self.signalFoundDevice.emit(device)
        except Exception as e:
            print("Fetch info error: {}".format(e))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    QTextCodec.setCodecForTr(QTextCodec.codecForName("UTF-8"))
    windows = RaspberryPiUpdateTools()
    windows.show()
    sys.exit(app.exec_())
