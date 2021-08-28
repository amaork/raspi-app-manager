# -*- coding: utf-8 -*-
from typing import List
from PySide.QtGui import *

from raspi_io.wireless import JoinNetwork
from raspi_io.app_manager import AppState

from framework.misc.settings import *
from framework.misc.windpi import scale_size
from framework.core.datatype import DynamicObject
__all__ = ['RaspberryPiInfo', 'RaspberryPiSoftwareDescription', 'OnlineUpdateConfigure',
           'UiJoinNetwork', 'UiAppState']


class RaspberryPiInfo(DynamicObject):
    _properties = {'revision', 'sn', 'ethernet', 'wireless', 'ios_version', 'app_state'}

    def format_as_list(self) -> List[str]:
        return [False, self.revision, self.sn,
                self.ethernet, self.wireless, self.ios_version,
                self.app_state.get("version") or "", self.app_state.get("state") or "", ""]


class OnlineUpdateConfigure(JsonSettings):
    _properties = {'repo', 'host', 'username', 'password'}

    def check(self) -> bool:
        return all([self.dict.get(x) for x in self.properties()]) and 'http' in self.host

    @classmethod
    def default(cls) -> DynamicObject:
        return OnlineUpdateConfigure(
            repo='Gogs update server repository name',
            host='Gogs server url',
            username='Gogs server username(The user should have permission to visit the update repository)',
            password='Gogs server password'
        )


class RaspberryPiSoftwareDescription(JsonSettings):
    _properties = {'app_name', 'exe_name', 'boot_args', 'autostart', 'log_file', 'conf_file', 'online_update'}
    _check = {
        'app_name': lambda x: isinstance(x, str) and len(x) < 32,
        'exe_name': lambda x: isinstance(x, str),
        'boot_args': lambda x: isinstance(x, str),
        'autostart': lambda x: isinstance(x, bool),
        'log_file': lambda x: isinstance(x, str),
        'conf_file': lambda x: isinstance(x, str),
        'online_update': lambda x: isinstance(x, dict),
    }

    @classmethod
    def default(cls) -> DynamicObject:
        return RaspberryPiSoftwareDescription(
            app_name='App name, must be unique (Required)',
            exe_name='Main executable programs name (Required)',
            autostart='Automatically start app when system boot (Required)',

            log_file='App log file name (Optional)',
            conf_file='App configure file name (Optional)',
            boot_args='Main executable programs boot args (Optional)',
            online_update=OnlineUpdateConfigure.default().dict
        )


class UiJoinNetwork(JsonSettings):
    _properties = JoinNetwork.properties()
    REQUIRED_OPTIONS = {'ssid', 'psk', 'key_mgmt'}

    @classmethod
    def default(cls) -> DynamicObject:
        return UiJoinNetwork(
            ssid=UiTextInput(QApplication.translate(
                "BasicJsonSettingDialog", "Network", None, QApplication.UnicodeUTF8),
                32, "").dict,

            psk=UiTextInput(QApplication.translate(
                "BasicJsonSettingDialog", "Password", None, QApplication.UnicodeUTF8),
                32, "", password=True).dict,

            key_mgmt=UiSelectInput(QApplication.translate(
                "BasicJsonSettingDialog", "Security", None, QApplication.UnicodeUTF8),
                (
                    QApplication.translate("BasicJsonSettingDialog", "WPA-PSK",
                                           None, QApplication.UnicodeUTF8),
                    QApplication.translate("BasicJsonSettingDialog", "WPA-EAP",
                                           None, QApplication.UnicodeUTF8),
                    QApplication.translate("BasicJsonSettingDialog", "NONE",
                                           None, QApplication.UnicodeUTF8),
                ), 'WPA-PSK').dict,

            priority=UiIntegerInput(QApplication.translate(
                "BasicJsonSettingDialog", "Priority (Increase)", None, QApplication.UnicodeUTF8), 0, 100, 0
            ).dict,

            scan_ssid=UiCheckBoxInput(QApplication.translate(
                "BasicJsonSettingDialog", "Hidden Network", None, QApplication.UnicodeUTF8),
                label_left=True,
            ).dict,

            id_str=UiTextInput(QApplication.translate(
                "BasicJsonSettingDialog", "Annotate of Network", None, QApplication.UnicodeUTF8),
                32, "").dict,

            required_group=UiLayout(name=QApplication.translate(
                "BasicJsonSettingDialog", "Required", None, QApplication.UnicodeUTF8),
                layout=['ssid', 'psk', 'key_mgmt']
            ),

            optional_group=UiLayout(name=QApplication.translate(
                "BasicJsonSettingDialog", "Optional", None, QApplication.UnicodeUTF8),
                layout=['scan_ssid', 'priority', 'id_str']
            ),

            layout=UiLayout(name=QApplication.translate(
                "BasicJsonSettingDialog", "Wireless Network", None, QApplication.UnicodeUTF8),
                margins=(0, 0, 0, 0),
                layout=['required_group', 'optional_group']
            )
        )


class UiAppState(JsonSettings):
    _properties = AppState.properties()

    @classmethod
    def default(cls) -> DynamicObject:
        return UiAppState(
            app_name=UiTextInput(QApplication.translate(
                "BasicJsonSettingDialog", "Name", None, QApplication.UnicodeUTF8),
                32, "", readonly=True
            ).dict,

            version=UiTextInput(QApplication.translate(
                "BasicJsonSettingDialog", "Version", None, QApplication.UnicodeUTF8),
                32, "", readonly=True
            ).dict,

            state=UiTextInput(QApplication.translate(
                "BasicJsonSettingDialog", "State", None, QApplication.UnicodeUTF8),
                32, "", readonly=True
            ).dict,

            size=UiTextInput(QApplication.translate(
                "BasicJsonSettingDialog", "Size (M)", None, QApplication.UnicodeUTF8),
                32, "", readonly=True
            ).dict,

            md5=UiTextInput(QApplication.translate(
                "BasicJsonSettingDialog", "App Exe MD5", None, QApplication.UnicodeUTF8),
                32, "", readonly=True
            ).dict,

            release_date=UiTextInput(QApplication.translate(
                "BasicJsonSettingDialog", "Release Date", None, QApplication.UnicodeUTF8),
                64, "", readonly=True
            ).dict,

            layout=UiLayout(name=QApplication.translate(
                "BasicJsonSettingDialog", "App State", None, QApplication.UnicodeUTF8),
                margins=(0, 0, 0, 0), stretch=(2, 8), min_size=scale_size((320, 160)),
                layout=['app_name', 'version', 'state', 'size', 'release_date', 'md5']
            )
        )
