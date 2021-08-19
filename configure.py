# -*- coding: utf-8 -*-
from typing import List
from PySide.QtGui import *
from framework.misc.settings import *
from raspi_io.wireless import JoinNetwork
from framework.core.datatype import DynamicObject
__all__ = ['RaspberryPiInfo', 'RaspberryPiSoftwareConfigure', 'UiJoinNetwork']


class RaspberryPiInfo(DynamicObject):
    _properties = {'revision', 'sn', 'ethernet', 'wireless', 'ios_version', 'software_version'}

    def format_as_list(self) -> List[str]:
        return [False, self.revision, self.sn,
                self.ethernet, self.wireless, self.ios_version,
                self.software_version.get("version"), self.software_version.get("state"), ""]


class RaspberryPiSoftwareConfigure(DynamicObject):
    _properties = {'host', 'username', 'password', 'software_repo', 'software_install'}


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
                32, "").dict,

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
