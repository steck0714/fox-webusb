// Type definitions for the navigator.usb surface provided by fox-webusb
// (and, unchanged in shape, by its sibling project pyside6-webusb).
//
// This file describes the *resulting* `navigator.usb` API as seen from
// page-side JavaScript/TypeScript -- it says nothing about how the polyfill
// is transported under the hood (QWebChannel in pyside6-webusb; a Firefox
// extension + native-messaging host in fox-webusb), because that's an
// implementation detail the page never sees. That's also why this file did
// not need any changes when porting pyside6-webusb to fox-webusb: the JS
// surface is identical by design (see README.md, "Spec compliance notes").
//
// Modeled on the WICG WebUSB draft: https://wicg.github.io/webusb/
// This is a community polyfill, not a browser vendor's implementation --
// see the two projects' README.md files for exactly which parts of the
// spec are (and are not yet) covered, and for the security model that
// differs from a native browser implementation (a native-messaging host
// process instead of the browser's own permission broker).

type USBDirection = 'in' | 'out';
type USBEndpointType = 'bulk' | 'interrupt' | 'isochronous';
type USBTransferStatus = 'ok' | 'stall' | 'babble';
type USBRequestType = 'standard' | 'class' | 'vendor';
type USBRecipient = 'device' | 'interface' | 'endpoint' | 'other';

interface USBEndpoint {
  readonly endpointNumber: number;
  readonly direction: USBDirection;
  readonly type: USBEndpointType;
  readonly packetSize: number;
}

interface USBAlternateInterface {
  readonly alternateSetting: number;
  readonly interfaceClass: number;
  readonly interfaceSubclass: number;
  readonly interfaceProtocol: number;
  readonly interfaceName: string | null;
  readonly endpoints: ReadonlyArray<USBEndpoint>;
}

interface USBInterface {
  readonly interfaceNumber: number;
  readonly alternate: USBAlternateInterface;
  readonly alternates: ReadonlyArray<USBAlternateInterface>;
  readonly claimed: boolean;
}

interface USBConfiguration {
  readonly configurationValue: number;
  readonly configurationName: string | null;
  readonly interfaces: ReadonlyArray<USBInterface>;
}

interface USBDeviceFilter {
  vendorId?: number;
  productId?: number;
  classCode?: number;
  subclassCode?: number;
  protocolCode?: number;
  serialNumber?: string;
}

interface USBDeviceRequestOptions {
  filters: USBDeviceFilter[];
  exclusionFilters?: USBDeviceFilter[];
}

interface USBControlTransferParameters {
  requestType: USBRequestType;
  recipient: USBRecipient;
  request: number;
  value: number;
  index: number;
}

interface USBInTransferResult {
  readonly data: DataView;
  readonly status: USBTransferStatus;
}

interface USBOutTransferResult {
  readonly bytesWritten: number;
  readonly status: USBTransferStatus;
}

interface USBIsochronousInTransferPacket {
  readonly data: DataView;
  readonly status: USBTransferStatus;
}

interface USBIsochronousInTransferResult {
  readonly data: DataView;
  readonly packets: ReadonlyArray<{ length: number; status: USBTransferStatus }>;
}

interface USBIsochronousOutTransferPacket {
  readonly bytesWritten: number;
  readonly status: USBTransferStatus;
}

interface USBIsochronousOutTransferResult {
  readonly packets: ReadonlyArray<USBIsochronousOutTransferPacket>;
}

interface USBDevice {
  readonly vendorId: number;
  readonly productId: number;
  readonly manufacturerName: string | null;
  readonly productName: string | null;
  readonly serialNumber: string | null;

  readonly deviceClass: number;
  readonly deviceSubclass: number;
  readonly deviceProtocol: number;

  readonly usbVersionMajor: number;
  readonly usbVersionMinor: number;
  readonly usbVersionSubminor: number;
  readonly deviceVersionMajor: number;
  readonly deviceVersionMinor: number;
  readonly deviceVersionSubminor: number;

  readonly configurations: ReadonlyArray<USBConfiguration>;
  readonly configuration: USBConfiguration | null;
  readonly opened: boolean;

  open(): Promise<void>;
  close(): Promise<void>;
  forget(): Promise<void>;

  selectConfiguration(configurationValue: number): Promise<void>;
  claimInterface(interfaceNumber: number): Promise<void>;
  releaseInterface(interfaceNumber: number): Promise<void>;
  selectAlternateInterface(interfaceNumber: number, alternateSetting: number): Promise<void>;
  reset(): Promise<void>;
  clearHalt(direction: USBDirection, endpointNumber: number): Promise<void>;

  transferIn(endpointNumber: number, length: number): Promise<USBInTransferResult>;
  transferOut(endpointNumber: number, data: BufferSource): Promise<USBOutTransferResult>;

  controlTransferIn(setup: USBControlTransferParameters, length: number): Promise<USBInTransferResult>;
  controlTransferOut(setup: USBControlTransferParameters, data?: BufferSource): Promise<USBOutTransferResult>;

  isochronousTransferIn(endpointNumber: number, packetLengths: number[]): Promise<USBIsochronousInTransferResult>;
  isochronousTransferOut(
    endpointNumber: number, data: BufferSource, packetLengths: number[],
  ): Promise<USBIsochronousOutTransferResult>;
}

interface USBConnectionEvent extends Event {
  readonly device: USBDevice;
}

interface USB extends EventTarget {
  getDevices(): Promise<USBDevice[]>;
  requestDevice(options: USBDeviceRequestOptions): Promise<USBDevice>;

  onconnect: ((this: USB, ev: USBConnectionEvent) => any) | null;
  ondisconnect: ((this: USB, ev: USBConnectionEvent) => any) | null;

  addEventListener(
    type: 'connect' | 'disconnect',
    listener: (this: USB, ev: USBConnectionEvent) => any,
    options?: boolean | AddEventListenerOptions,
  ): void;
  addEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | AddEventListenerOptions,
  ): void;
  removeEventListener(
    type: 'connect' | 'disconnect',
    listener: (this: USB, ev: USBConnectionEvent) => any,
    options?: boolean | EventListenerOptions,
  ): void;
  removeEventListener(
    type: string,
    listener: EventListenerOrEventListenerObject,
    options?: boolean | EventListenerOptions,
  ): void;
}

interface Navigator {
  readonly usb: USB;
}
