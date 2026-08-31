# -*- coding: utf-8 -*-
"""
fake_usb.py
===========
pyusb (usb.core.Device / usb.util) の形だけを模したテスト用フェイク。
実機やlibusbバックエンドを一切必要とせずに bridge.py / hardening.py を
検証するために使う。

設計方針:
  hardening.py の関数群は usb_util を「引数として受け取る」設計になっている
  (build_device_descriptor(dev, usb_util, ...) 等)ため、本物のusb.utilの
  代わりにこのモジュールのFakeUsbUtilを渡すだけでテストできる。
  bridge.py は `import usb.util as usb_util` をモジュールレベルで行っている
  ため、テスト側は `monkeypatch.setattr(bridge_module, "usb_util",
  FakeUsbUtil())` のように差し替える(pytestの標準的な手法)。

  本物のusb.util.claim_interface/release_interface/dispose_resourcesは
  `device._ctx`(実際のlibusbバックエンドコンテキスト)を必要とし、
  素朴なフェイクオブジェクトでは動かない。get_string()も実際にcontrol
  transferを発行して文字列ディスクリプタを読みに行く。そのため、
  「本物のusb.utilを使い、フェイクデバイス側にlibusb相当の挙動を
  実装する」のではなく、「usb_util自体を軽量なフェイクに差し替える」
  アプローチを採る。find_descriptor/endpoint_type/endpoint_directionは
  本物同様、対象オブジェクトの属性を見るだけの純粋なロジックなので、
  フェイク側もほぼ同じ実装で足りる。
"""


class FakeEndpoint:
    def __init__(self, address, ep_type, max_packet_size=64):
        self.bEndpointAddress = address
        self.bmAttributes = ep_type  # FakeUsbUtilの定数と同じ値をそのまま使う(下位2bit)
        self.wMaxPacketSize = max_packet_size


class FakeInterface:
    def __init__(self, number, alternate=0, interface_class=0xFF, subclass=0x00, protocol=0x00,
                 endpoints=None, name_index=0):
        self.bInterfaceNumber = number
        self.bAlternateSetting = alternate
        self.bInterfaceClass = interface_class
        self.bInterfaceSubClass = subclass
        self.bInterfaceProtocol = protocol
        self.iInterface = name_index
        self._endpoints = list(endpoints or [])

    def __iter__(self):
        return iter(self._endpoints)


class FakeConfiguration:
    def __init__(self, value=1, interfaces=None, name_index=0):
        self.bConfigurationValue = value
        self.iConfiguration = name_index
        self._interfaces = list(interfaces or [])

    def __iter__(self):
        return iter(self._interfaces)


class FakeDevice:
    """1つの物理デバイスを模す。configurationsは
    [(configA_alt0, configA_alt1, ...はまとめて1つのFakeConfigurationのinterfaces内で表現)]
    ではなく、素朴に「FakeConfigurationのリスト」として渡す
    (同一インターフェース番号の複数alternateは、そのFakeConfigurationの
    interfacesリストに複数のFakeInterface(同じbInterfaceNumber、異なる
    bAlternateSetting)を並べることで表現する)。"""

    def __init__(self, vendor_id, product_id, configurations=None, strings=None,
                 device_class=0x00, device_subclass=0x00, device_protocol=0x00,
                 bcd_usb=0x0200, bcd_device=0x0100,
                 manufacturer_index=0, product_index=0, serial_index=0):
        self.idVendor = vendor_id
        self.idProduct = product_id
        self.bDeviceClass = device_class
        self.bDeviceSubClass = device_subclass
        self.bDeviceProtocol = device_protocol
        self.bcdUSB = bcd_usb
        self.bcdDevice = bcd_device
        self.iManufacturer = manufacturer_index
        self.iProduct = product_index
        self.iSerialNumber = serial_index
        self.strings = dict(strings or {})

        self._configurations = list(configurations or [FakeConfiguration(1, [])])
        self._active_configuration_value = self._configurations[0].bConfigurationValue if self._configurations else None

        self.claimed = set()
        self.reset_count = 0
        self.cleared_halts = []

        # テストがtransferの挙動を差し替えられるようにするためのフック。
        # 既定は「常に空バイト列/成功」の単純な応答。
        self.on_read = None    # (endpoint, length, timeout) -> bytes
        self.on_write = None   # (endpoint, data, timeout) -> int (bytesWritten)
        self.on_ctrl_transfer = None  # (bmRequestType, bRequest, wValue, wIndex, data_or_length, timeout) -> bytes|int

    def __iter__(self):
        return iter(self._configurations)

    def get_active_configuration(self):
        for cfg in self._configurations:
            if cfg.bConfigurationValue == self._active_configuration_value:
                return cfg
        raise ValueError("no active configuration")

    def set_configuration(self, configuration=None):
        value = configuration
        if value is None:
            value = self._configurations[0].bConfigurationValue
        if not any(c.bConfigurationValue == value for c in self._configurations):
            raise ValueError(f"no such configuration: {value}")
        self._active_configuration_value = value

    def set_interface_altsetting(self, interface=None, alternate_setting=None):
        cfg = self.get_active_configuration()
        match = [i for i in cfg if i.bInterfaceNumber == interface and i.bAlternateSetting == alternate_setting]
        if not match:
            raise ValueError(f"no such interface/alternate: {interface}/{alternate_setting}")

    def read(self, endpoint, size_or_buffer, timeout=None):
        if self.on_read is not None:
            return self.on_read(endpoint, size_or_buffer, timeout)
        return b""

    def write(self, endpoint, data, timeout=None):
        if self.on_write is not None:
            return self.on_write(endpoint, data, timeout)
        return len(bytes(data))

    def ctrl_transfer(self, bmRequestType, bRequest, wValue=0, wIndex=0, data_or_wLength=None, timeout=None):
        if self.on_ctrl_transfer is not None:
            return self.on_ctrl_transfer(bmRequestType, bRequest, wValue, wIndex, data_or_wLength, timeout)
        if bmRequestType & 0x80:  # IN
            return b""
        return len(bytes(data_or_wLength)) if data_or_wLength else 0

    def reset(self):
        self.reset_count += 1

    def clear_halt(self, ep):
        self.cleared_halts.append(ep)


class FakeUsbUtil:
    """usb.util の代わりに bridge.py / hardening.py へ渡すフェイク。
    定数値は実際のUSB仕様どおり(bmAttributesの下位2bit、bEndpointAddressの
    最上位bit)にしてあるので、実データを扱うテストコードとの相性もよい。"""

    ENDPOINT_TYPE_CTRL = 0x00
    ENDPOINT_TYPE_ISO = 0x01
    ENDPOINT_TYPE_BULK = 0x02
    ENDPOINT_TYPE_INTR = 0x03
    ENDPOINT_IN = 0x80
    ENDPOINT_OUT = 0x00

    @staticmethod
    def get_string(dev, index):
        if not index:
            return None
        return dev.strings.get(index)

    @staticmethod
    def endpoint_type(bm_attributes):
        return bm_attributes & 0x03

    @staticmethod
    def endpoint_direction(address):
        return address & 0x80

    @staticmethod
    def find_descriptor(desc, find_all=False, custom_match=None, **args):
        def matches(d):
            for key, val in args.items():
                if getattr(d, key, None) != val:
                    return False
            return custom_match is None or custom_match(d)

        results = [d for d in desc if matches(d)]
        if find_all:
            return results
        return results[0] if results else None

    @staticmethod
    def claim_interface(dev, interface_number):
        dev.claimed.add(interface_number)

    @staticmethod
    def release_interface(dev, interface_number):
        dev.claimed.discard(interface_number)

    @staticmethod
    def dispose_resources(dev):
        pass


def make_simple_device(vendor_id=0x1234, product_id=0x5678, product_name="Test Device",
                        manufacturer_name="Test Vendor", serial=None,
                        interface_class=0xFF, num_endpoints_bulk=(1, 1), extra_interfaces=None):
    """よく使う「1 configuration・1 interface・IN/OUTのbulkエンドポイント各1本」
    という形のデバイスを手早く作るヘルパー。num_endpoints_bulk=(in_ep_num, out_ep_num)。"""
    in_num, out_num = num_endpoints_bulk
    endpoints = [
        FakeEndpoint(in_num | 0x80, FakeUsbUtil.ENDPOINT_TYPE_BULK),
        FakeEndpoint(out_num, FakeUsbUtil.ENDPOINT_TYPE_BULK),
    ]
    interfaces = [FakeInterface(0, 0, interface_class=interface_class, endpoints=endpoints, name_index=4)]
    if extra_interfaces:
        interfaces.extend(extra_interfaces)
    cfg = FakeConfiguration(1, interfaces, name_index=5)
    strings = {1: manufacturer_name, 2: product_name, 4: "Bulk Interface", 5: "Default Config"}
    if serial:
        strings[3] = serial
    return FakeDevice(
        vendor_id, product_id, configurations=[cfg], strings=strings,
        manufacturer_index=1, product_index=2, serial_index=3 if serial else 0,
    )
