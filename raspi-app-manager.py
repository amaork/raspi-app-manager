# -*- coding: utf-8 -*-
import os
import sys
import json
import ipaddress
import threading
import collections
from PySide.QtGui import *
from PySide.QtCore import *
from typing import Optional, List, Dict, Callable, Union, Any, ClassVar

from raspi_io.utility import scan_server
from raspi_io.app_manager import AppState
from raspi_io.core import RaspiMsgDecodeError
from raspi_io import AppManager, Query, Wireless, RaspiException

import version
import resources_rc
from operate import *
from configure import *

from framework.core.uimailbox import *
from framework.core.threading import ThreadLockAndDataWrap
from framework.core.datatype import DynamicObject, DynamicObjectEncodeError, DynamicObjectDecodeError

from framework.protocol.upgrade import GogsSoftwareReleaseDesc

from framework.misc.windpi import scale_x, scale_size
from framework.misc.settings import UiLogMessage, JsonSettingsDecodeError
from framework.misc.parallel import BackgroundOperateLauncher, ConcurrentLauncher

from framework.gui.msgbox import *
from framework.gui.checkbox import CheckBoxDelegate
from framework.gui.widget import TableWidget, LogMessageWidget
from framework.gui.dialog import showFileImportDialog, showFileExportDialog, \
    MultiGroupJsonSettingsDialog, ProgressDialog, JsonSettingDialog


AppDescFormat = "App Description(*.json)"
Device = collections.namedtuple('Device', ['row', 'address'])


class RaspberryPiUpdateTools(QMainWindow):
    signalLogging = Signal(UiLogMessage)
    signalOperateLogging = Signal(UiLogMessage, int)

    signalMarkDeviceAsIdle = Signal(Device)
    signalFoundDevice = Signal(RaspberryPiInfo)
    signalUpdateProgress = Signal(int, str, object)

    signalUpdateIOSVersion = Signal(int, object)
    signalUpdateAppVersion = Signal(int, object, str)

    ACTION_GROUP = collections.namedtuple('Action', ['SCAN', 'NETWORK', 'USER_APP', 'IOS_APP', 'SYSTEM'])(*range(5))
    COLUMN = collections.namedtuple(
        'Column', ['SEL', 'REV', 'SN', 'ETH', 'WLAN', 'IOS_VER', 'APP_VER', 'APP_STATE', 'OPERATE_RESULT']
    )(*range(9))

    def __init__(self):
        self.app_config = None
        self.device_state = ThreadLockAndDataWrap(dict())
        super(RaspberryPiUpdateTools, self).__init__()
        self._initUi()
        self._initMenu()
        self._initStyle()
        self._initSignalAndSlots()
        self._initThreadAndTimer()

    def _initUi(self):
        self.ui_mail = UiMailBox(self)
        self.ui_table_content_menu = QMenu(self)
        self.ui_logging = LogMessageWidget('raspi-app-manager.log', parent=self)
        self.ui_progress = ProgressDialog(self, closeable=False, max_width=scale_x(400))

        self.ui_table = TableWidget(len(self.COLUMN), disable_custom_content_menu=True, parent=self)
        self.ui_table.setColumnHeader((
            self.tr("Sel"),
            self.tr("Revision"), self.tr("Serial Number"), self.tr("Ethernet"), self.tr("Wireless"),
            self.tr("IOS Ver"), self.tr("App Ver"), self.tr("App State"), self.tr("Operating / Result")
        ))

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.ui_table)
        layout.addWidget(self.ui_logging)
        layout.setStretchFactor(self.ui_table, 6)
        layout.setStretchFactor(self.ui_logging, 3)

        widget = QWidget(self)
        widget.setLayout(layout)
        self.setCentralWidget(widget)

    def _initMenu(self):
        self.menu_bar = QMenuBar(self)
        self.setMenuBar(self.menu_bar)

        sub_menu = collections.namedtuple('menu', ['name', 'slot', 'shortcut'])
        separator = sub_menu(name='separator', slot=None, shortcut=None)

        for menu, actions in {
            sub_menu(name=self.tr('File'), slot=None, shortcut=None): [
                sub_menu(name=self.tr('Load App Description'), shortcut='Ctrl+L', slot=self.slotLoadAppDesc),
                sub_menu(name=self.tr("Save App Description Template"), shortcut='Ctrl+S',
                         slot=self.slotSaveAppDescTemplate),
                separator,
                sub_menu(name=self.tr('Quit'), shortcut='Ctrl+Q', slot=lambda: sys.exit())
            ],

            sub_menu(name=self.tr("View"), slot=None, shortcut=None): [
                sub_menu(name=self.tr('Show Log Window'),
                         shortcut=None, slot=lambda: self.ui_logging.setVisible(True)),
                sub_menu(name=self.tr('Hidden Log Window'),
                         shortcut=None, slot=lambda: self.ui_logging.setHidden(True)),
            ],

            sub_menu(name=self.tr('RPi'), slot=None, shortcut=None): [
                sub_menu(name=self.tr('Scan'), shortcut='F5', slot=self.slotScan),
                sub_menu(name=self.tr('Reboot'), shortcut='Alt+F9', slot=self.slotRebootSystem),
                sub_menu(name=self.tr('Update IO Server'), shortcut='Alt+F2', slot=self.slotUpdateIOServer),
                sub_menu(name=self.tr('Manual Add Raspi'), shortcut='Alt+F3', slot=self.slotManualAddRaspberryPi),
                separator,
                sub_menu(name=self.tr('Install User App'), shortcut='Ctrl+Alt+I', slot=self.slotInstallUserApp),
                sub_menu(name=self.tr('Uninstall User App'), shortcut='Ctrl+Alt+U', slot=self.slotUninstallUserApp),
            ],

            sub_menu(name=self.tr('Wireless'), slot=None, shortcut=None): [
                sub_menu(name=self.tr('Join Network'), shortcut=None, slot=self.slotJoinWireless),
                sub_menu(name=self.tr('Leave Network'), shortcut=None, slot=self.slotLeaveWireless),
                # separator,
                # sub_menu(name=self.tr('Backup WPA Configure'), shortcut=None, slot=self.slotBackupWireless),
                # sub_menu(name=self.tr('Restore WPA Configure'), shortcut=None, slot=self.slotRestoreWireless),
            ],

            sub_menu(name=self.tr('App'), slot=None, shortcut=None): [
                sub_menu(name=self.tr('Local Update'), shortcut=None, slot=self.slotLocalUpdate),
                sub_menu(name=self.tr('Online Update'), shortcut=None, slot=self.slotOnlineUpdate),
                separator,
                sub_menu(name=self.tr('Upload App Configures'), shortcut=None, slot=None),
                sub_menu(name=self.tr('Download App Configure'), shortcut=None, slot=None),
                separator,
                sub_menu(name=self.tr('Backup Application and Data'), shortcut=None, slot=None),
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

        self.ui_table.setColumnMaxWidth(self.COLUMN.SEL, scale_x(40))
        self.ui_table.setItemDelegateForColumn(
            self.COLUMN.SEL, CheckBoxDelegate(stylesheet=DynamicObject(sizeFactor=2.0), parent=self)
        )

        self.setWindowIcon(QPixmap(":ico/ico/raspi.ico"))
        self.setMinimumSize(QSize(*scale_size((800, 600))))
        self.setWindowTitle(self.tr("Raspberry Pi App Manager {}".format(version.s_version)))

    def _initSignalAndSlots(self):
        self.signalLogging.connect(self.slotDisplayLogging)
        self.signalOperateLogging.connect(self.slotDisplayLogging)

        self.signalUpdateProgress.connect(self.slotUpdateProcess)

        self.signalFoundDevice.connect(self.slotFoundNewRaspberryPi)
        self.signalMarkDeviceAsIdle.connect(self.slotMarkDeviceAsIdle)

        self.signalUpdateAppVersion.connect(self.slotUpdateAppVersion)
        self.signalUpdateIOSVersion.connect(self.slotUpdateIOSVersion)

        self.ui_table.customContextMenuRequested.connect(self.slotCustomTableContentMenu)

    def _initThreadAndTimer(self):
        pass

    def getCurrentRowSN(self, row: int) -> str:
        return self.ui_table.getItemData(row, self.COLUMN.SN) if 0 <= row < self.ui_table.rowCount() else ""

    def getCurrentRowDevice(self, row: int) -> Device:
        address = self.ui_table.getItemData(row, self.COLUMN.ETH) or self.ui_table.getItemData(row, self.COLUMN.WLAN)
        return Device(row=row, address=address)

    def getCurrentDeviceInfo(self, device: Device) -> RaspberryPiInfo:
        return self.ui_table.getItemProperty(device.row, self.COLUMN.SEL)

    def markDeviceAsBusy(self, operate_name: str, operate_devices: List[Device]):
        for row, address in operate_devices:
            self.device_state.data[address] = operate_name
            self.ui_table.frozenItem(row, self.COLUMN.SEL, True)
            self.ui_table.setItemData(row, self.COLUMN.SEL, False)
            self.signalUpdateProgress.emit(row, operate_name, Qt.yellow)

    def getCurrentOperateDevice(self, row: Optional[int]) -> List[Device]:
        # From content menu
        if row is not None:
            if not row <= 0 < self.ui_table.rowCount():
                showMessageBox(self, MB_TYPE_ERR, self.tr("Invalid row number") + f" :{row}")
                return list()

            return [self.getCurrentRowDevice(row)]

        # From menu bar
        devices = [self.getCurrentRowDevice(row)
                   for row in range(self.ui_table.rowCount())
                   if self.ui_table.getItemData(row, self.COLUMN.SEL)]

        if not devices:
            showMessageBox(self, MB_TYPE_WARN, self.tr("Please select device first"))
            return list()

        return devices

    def updateSoftwareFromLocal(self, row: int, tag: str, title: str, app_name: str, callback: Callable):
        devices = self.getCurrentOperateDevice(row)
        if not devices:
            return

        update_package = showFileImportDialog(self, fmt="Tar File (*.tar)", title=title)
        if not os.path.isfile(update_package):
            return

        args = [(row, address, app_name, update_package) for row, address in devices]
        self.createConcurrentOperateThread(tag, devices, LocalUpdate, args, callback)

    def createConcurrentOperateThread(self, operate_name: str, operate_devices: List[Device],
                                      operate_cls: ClassVar, operate_args: list, callback: Callable) -> bool:
        if not issubclass(operate_cls, RaspiOperate):
            return False

        operate_cnt = len(operate_args)
        self.ui_progress.setRange(0, operate_cnt + 1)
        operate = operate_cls(self.signalOperateLogging.emit, callback)

        # Limit max works number
        max_workers = operate_cnt if operate_cnt <= 32 else 32
        launcher = ConcurrentLauncher(operate, max_workers=max_workers)
        launcher.run(operate_args)

        # Disable currently operating device
        self.markDeviceAsBusy(operate_name, operate_devices)

        return True

    def checkApp(self):
        if not isinstance(self.app_config, RaspberryPiSoftwareDescription):
            return showMessageBox(self, MB_TYPE_WARN, self.tr("Please load app description first"))

        return True

    def slotScan(self):
        if any(self.device_state.data.values()):
            return showMessageBox(self, MB_TYPE_WARN, self.tr("Please wait device operating finished"))

        self.ui_table.setRowCount(0)
        th = threading.Thread(target=self.threadScanRaspberryPi)
        th.setDaemon(True)
        th.start()

    def slotLoadAppDesc(self):
        title = self.tr("Please select app description file")
        app_desc = showFileImportDialog(self, fmt=AppDescFormat, title=title)
        if not os.path.isfile(app_desc):
            return

        try:
            app_config = RaspberryPiSoftwareDescription.load(app_desc)
            app_config.update(app_config.dict)
            self.app_config = app_config

            app = f'Current App: {self.app_config.app_name.capitalize()}'
            msg = self.tr("Load app description file success") + f": {app}"
            self.signalLogging.emit(UiLogMessage.genDefaultInfoMessage(msg))
            self.setWindowTitle(self.tr("Raspberry Pi App Manager") + f' {version.s_version}' + f' ({app})')
            self.slotScan()
        except (json.JSONDecodeError, JsonSettingsDecodeError, DynamicObjectDecodeError, DynamicObjectEncodeError) as e:
            return showMessageBox(self, MB_TYPE_ERR, f'{e}', self.tr("Load App Description Configure"))

    def slotSaveAppDescTemplate(self):
        title = self.tr("Please select 'App Description' file template save path")
        path = showFileExportDialog(self, fmt=AppDescFormat, title=title)
        if not path:
            return

        try:
            RaspberryPiSoftwareDescription.default().save(path)
            if not showQuestionBox(self,
                                   self.tr("Open App Description file") + f': {path}',
                                   self.tr("Save App Description success")):
                return

            os.system(f"start {path}")
        except (json.JSONDecodeError, JsonSettingsDecodeError, OSError) as e:
            return showMessageBox(self, MB_TYPE_ERR, self.tr("Save App Description file error") + f': {e}')

    def slotManualAddRaspberryPi(self):
        address, inputted = QInputDialog.getText(
            self, self.tr("Manual Add Raspberry Pi"), self.tr("Please input Raspberry Pi address" + " " * 20)
        )

        if not inputted or not address:
            return

        try:
            ipaddress.ip_address(address)
        except ValueError as e:
            return showMessageBox(self, MB_TYPE_ERR, f'{e}', self.tr('Input Address error'))

        if address in self.ui_table.getColumnData(self.COLUMN.ETH) + self.ui_table.getColumnData(self.COLUMN.WLAN):
            return showMessageBox(self, MB_TYPE_WARN,
                                  self.tr("Raspberry Pi") + f": {address!r} " + self.tr("already exist"))

        try:
            Query(address)
            th = threading.Thread(target=self.threadFetchRaspberryPiInfo, kwargs=dict(address=address))
            th.setDaemon(True)
            th.start()
        except RaspiException as e:
            return showMessageBox(self, MB_TYPE_ERR, self.tr("Add failed") + f': {e}', self.tr('Add RPI Failed'))

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
            self.ui_table.addRow(device_info.format_as_list(), [device_info])
        else:
            row = sn_list.index(device_info.sn)
            self.slotUpdateProcess(row, "", QColor(Qt.white))
            self.ui_table.setRowData(row, device_info.format_as_list())

        self.ui_table.frozenRow(row, True)
        self.ui_table.frozenItem(row, self.COLUMN.SEL, False)
        self.ui_table.setRowAlignment(row, Qt.AlignCenter)
        self.ui_table.openPersistentEditor(self.ui_table.item(row, self.COLUMN.SEL))

    def slotDisplayLogging(self, msg: UiLogMessage, row: Optional[int] = None):
        if row is not None:
            sn = self.getCurrentRowSN(row)
            msg.content = f"[{sn}]: {msg.content}"

        self.ui_logging.logging(msg)

    def slotRebootSystem(self, row: Optional[int] = None):
        devices = self.getCurrentOperateDevice(row)
        if not devices:
            return

        def callback(result: Union[bool, str], row_: int, address: str, *_args):
            result = result if isinstance(result, bool) else False
            self.callbackOperatingFinished(self.tr("Reboot"), result, row_, address)

        self.createConcurrentOperateThread(self.tr("Rebooting"), devices, Reboot, devices, callback)

    def slotJoinWireless(self, row: Optional[int] = None):
        devices = self.getCurrentOperateDevice(row)
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
        self.createConcurrentOperateThread(self.tr("Join Network"), devices, JoinWirelessNetwork, args, callback)

    def slotLeaveWireless(self, row: Optional[int] = None):
        devices = self.getCurrentOperateDevice(row)
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

        self.createConcurrentOperateThread(
            self.tr("Leaving Network"), devices,
            LeaveWirelessNetwork, [(row, address, network) for row, address in devices], callback
        )

    def slotShowAppState(self, row: int):
        if not self.checkApp():
            return

        devices = self.getCurrentOperateDevice(row)
        if not devices:
            return

        try:
            app_state = AppState(**self.getCurrentDeviceInfo(devices[0]).app_state)
            app_state.size /= 1024 * 1024
            JsonSettingDialog.getSettings(UiAppState.default(), app_state.dict, reset=False, parent=self)
        except (RaspiMsgDecodeError, AttributeError):
            self.createConcurrentOperateThread(
                self.tr("Fetching App State"), devices, GetAppState,
                [(row, address, self.app_config.app_name) for row, address in devices],
                lambda *args: self.ui_mail.send(CallbackFuncMail(self.callbackFetchAppState, args=args))
            )

    def slotInstallUserApp(self, row: Optional[int] = None):
        if not self.checkApp():
            return

        devices = self.getCurrentOperateDevice(row)
        if not devices:
            return

        title = self.tr("Please select will install app package")
        package = showFileImportDialog(self, fmt="Tar File (*.tar)", title=title)
        if not os.path.isfile(package):
            return

        desc = self.app_config
        self.createConcurrentOperateThread(
            self.tr("Installing App"), devices,
            InstallUserApp, [(row, address, package, desc.dict) for row, address in devices], self.callbackInstallApp
        )

    def slotUninstallUserApp(self, row: Optional[int] = None):
        if not self.checkApp():
            return

        devices = self.getCurrentOperateDevice(row)
        if not devices:
            return

        app_name = self.app_config.app_name
        self.createConcurrentOperateThread(
            self.tr("Uninstalling App"), devices,
            UninstallUserApp, [(row, address, app_name) for row, address in devices], self.callbackUninstallApp
        )

    def slotBackupWireless(self, row: Optional[int] = None):
        pass

    def slotRestoreWireless(self, row: Optional[int] = None):
        pass

    def slotUpdateIOServer(self, row: Optional[int] = None):
        self.updateSoftwareFromLocal(row, self.tr("Updating IOS"),
                                     self.tr("Please select 'Raspi IO Server' update package"),
                                     AppManager.IO_SERVER_NAME, self.callbackUpdateIOServer)

    def slotLocalUpdate(self, row: Optional[int] = None):
        if not self.checkApp():
            return

        title = self.tr("Please select") + " {!r} ".format(self.app_config.app_name) + self.tr("update package")
        self.updateSoftwareFromLocal(row, self.tr("Local Updating"), title, self.app_config.app_name,
                                     lambda *args: self.callbackUpdate(self.tr("Local Update"), *args))

    def slotOnlineUpdate(self, row: Optional[int] = None):
        title = self.tr("Online Update")

        if not self.checkApp():
            return

        try:
            auth = OnlineUpdateConfigure(**self.app_config.online_update)
            if not auth.check():
                raise ValueError("invalid online update configure")
        except (DynamicObjectDecodeError, ValueError) as e:
            msg = self.tr("App description file") + " 'online_update' " + self.tr("not configure or") + f': {e}'
            return showMessageBox(self, MB_TYPE_WARN, msg, title)

        devices = self.getCurrentOperateDevice(row)
        if not devices:
            return

        for row, _ in devices:
            self.signalUpdateProgress.emit(row, self.tr("Fetching Update"), Qt.yellow)

        try:
            auth = auth.dict
            repo = auth.pop('repo')
            manager = AppManager(devices[0].address, timeout=300)
            th = threading.Thread(target=self.threadFetchUpdate,
                                  kwargs=dict(repo=repo, auth=auth, manager=manager, devices=devices))
            th.setDaemon(True)
            th.start()
        except RaspiException as e:
            return showMessageBox(self, MB_TYPE_ERR, f"Fetch online update failed: {e}", title)

    def slotCustomTableContentMenu(self, pos: QPoint):
        content_menu = QMenu(self)
        item = self.ui_table.itemAt(pos)
        if isinstance(item, QTableWidgetItem):
            device = self.getCurrentRowDevice(item.row())
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
                (QAction(self.tr("Get App State"), self), lambda: self.slotShowAppState(item.row())),
                (QAction(self.tr("Online Update"), self), lambda: self.slotOnlineUpdate(item.row())),
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

                if self.app_config is None and group == self.ACTION_GROUP.USER_APP:
                    continue

                content_menu.addAction(action)

            content_menu.addSeparator()

        content_menu.popup(self.ui_table.viewport().mapToGlobal(pos))

    def slotUpdateIOSVersion(self, row: int, ver: Union[str, float]):
        self.ui_table.setItemData(row, self.COLUMN.IOS_VER, str(ver))

    def slotUpdateAppVersion(self, row: int, ver: Union[str, float], state: str):
        self.ui_table.setItemData(row, self.COLUMN.APP_VER, str(ver))
        self.ui_table.setItemData(row, self.COLUMN.APP_STATE, state)
        # App uninstalled remote app state info form device info
        if not str(ver) or state == self.tr("Uninstall"):
            device_info = self.ui_table.getItemProperty(row, self.COLUMN.SEL)
            device_info.app_state = dict()
            self.ui_table.setItemProperty(row, self.COLUMN.SEL, device_info)

    def slotUpdateProcess(self, row: int, process: str, color: Union[Qt.GlobalColor, QColor]):
        self.ui_table.setItemData(row, self.COLUMN.OPERATE_RESULT, process)
        self.ui_table.setItemBackground(row, self.COLUMN.OPERATE_RESULT, QBrush(color))

    def callbackUpdate(self, tag: str, result: Any, row: int, address: str, *_args):
        if not isinstance(result, dict):
            msg = f'{tag} ' + self.tr("failed") + f" : {result}"
            self.signalOperateLogging.emit(UiLogMessage.genDefaultErrorMessage(msg), row)
            self.signalUpdateProgress.emit(row, f'{tag} ' + self.tr("Failed"), Qt.red)
        else:
            self.signalUpdateProgress.emit(row, f'{tag} ' + self.tr("Success"), Qt.green)
            self.signalUpdateAppVersion.emit(row, result.get("version"), self.tr("Rebooting"))

        self.signalMarkDeviceAsIdle.emit(Device(row, address))

    def callbackInstallApp(self, result: Any, row: int, address: str, *_args):
        if not isinstance(result, dict):
            msg = self.tr('App install failed') + f': {result}'
            self.signalOperateLogging.emit(UiLogMessage.genDefaultErrorMessage(msg), row)
            self.signalUpdateProgress.emit(row, self.tr("App Install Failed"), Qt.red)
        else:
            self.signalUpdateAppVersion.emit(row, result.get("version"), self.tr("Rebooting"))
            self.signalUpdateProgress.emit(row, self.tr("App Install Success"), Qt.green)

        self.signalMarkDeviceAsIdle.emit(Device(row, address))

    def callbackUninstallApp(self, result: Any, row: int, address: str, *_args):
        if not isinstance(result, bool) or not result:
            msg = self.tr('Uninstall app failed') + f': {result}'
            self.signalOperateLogging.emit(UiLogMessage.genDefaultErrorMessage(msg), row)
            self.signalUpdateProgress.emit(row, self.tr("Uninstall App Failed"), Qt.red)
        else:
            self.signalUpdateAppVersion.emit(row, "", self.tr("Uninstall"))
            self.signalUpdateProgress.emit(row, self.tr("Uninstall App Success"), Qt.green)

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

    def callbackFetchAppState(self, result: Any, row: int, address: str, *_args):
        self.signalMarkDeviceAsIdle.emit(Device(row, address))

        def error_handle(error: str):
            self.signalUpdateProgress.emit(row, self.tr("Get App State Failed"), Qt.red)
            showMessageBox(self, MB_TYPE_ERR, self.tr('Get app state failed') + f': {error}', self.tr("Get App State"))

        if not isinstance(result, dict):
            error_handle(result)
        else:
            try:
                app_state = AppState(**result)
                app_state.size /= 1024 * 1024
                JsonSettingDialog.getSettings(UiAppState.default(), app_state.dict, reset=False, parent=self)
            except (RaspiMsgDecodeError, AttributeError) as e:
                error_handle(e)

    def callbackFetchUpdateInfo(self, auth: dict, devices: List[Device],
                                repo_release: dict, software_release: GogsSoftwareReleaseDesc):
        title = self.tr("Online Update")

        # Single device ask user to confirm
        if len(devices) == 1:
            try:
                app_state = AppState(**self.getCurrentDeviceInfo(devices[0]).app_state)
            except RaspiMsgDecodeError:
                self.signalUpdateProgress.emit(devices[0].row, self.tr("Fetch Update Error"), Qt.red)
                return showMessageBox(self, MB_TYPE_ERR,
                                      self.tr("Get app state error, make sure app is installed"), title)

            if software_release.version <= app_state.version:
                self.signalUpdateProgress.emit(devices[0].row, self.tr("No Need Update"), Qt.green)
                return showMessageBox(self, MB_TYPE_INFO, self.tr("Current app is newest, do not need update"), title)

        # Multi devices directly update
        args = [(row, address, auth, repo_release, self.app_config.app_name) for row, address in devices]
        self.createConcurrentOperateThread(
            self.tr("Online Updating"), devices, OnlineUpdate, args,
            lambda *results: self.callbackUpdate(self.tr("Online Update"), *results)
        )

    def threadScanRaspberryPi(self, timeout: float = 0.05):
        for address in scan_server(timeout=timeout):
            th = threading.Thread(target=self.threadFetchRaspberryPiInfo, kwargs=dict(address=address))
            th.setDaemon(True)
            th.start()

    def threadFetchRaspberryPiInfo(self, address: str):
        try:
            query = Query(address)

            ethernet, wireless = address, ''
            _, revision, sn = query.get_hardware_info()
            ifc_list = query.get_iface_list()

            for interface in ifc_list:
                if 'eth0' == interface:
                    ethernet = query.get_ethernet_addr(interface)
                else:
                    wireless = query.get_ethernet_addr(interface)

            ethernet = ethernet or address

            try:
                manager = AppManager(address)
                app_state = manager.get_app_state(self.app_config.app_name)
            except (RaspiException, AttributeError):
                app_state = dict()

            device = RaspberryPiInfo(revision=revision, sn=sn,
                                     ethernet=ethernet, wireless=wireless,
                                     ios_version=query.get_version().get("server"), app_state=app_state)
            self.signalFoundDevice.emit(device)
            self.signalLogging.emit(UiLogMessage.genDefaultDebugMessage(f'{address}: {device}'))
        except Exception as e:
            self.signalLogging.emit(UiLogMessage.genDefaultErrorMessage(f'Fetch {address!r} info error: {e}'))

    def threadFetchUpdate(self, repo: str, auth: dict, manager: AppManager, devices: List[Device]):
        error = ""

        try:
            repo_release, software_release = manager.fetch_update(auth, repo)
            software_release = GogsSoftwareReleaseDesc(**software_release)

            if not isinstance(software_release, GogsSoftwareReleaseDesc):
                error = self.tr("Fetch release failed")
                return

            kwargs = dict(auth=auth, devices=devices, repo_release=repo_release, software_release=software_release)
            self.ui_mail.send(CallbackFuncMail(self.callbackFetchUpdateInfo, kwargs=kwargs))
        except (TypeError, ValueError, RaspiException, DynamicObjectDecodeError) as e:
            error = f'{e}'
        finally:
            if error:
                self.ui_mail.send(MessageBoxMail(MB_TYPE_ERR, f"{error}", title=self.tr("Fetch update failed")))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    QTextCodec.setCodecForTr(QTextCodec.codecForName("UTF-8"))
    windows = RaspberryPiUpdateTools()
    windows.show()
    sys.exit(app.exec_())
