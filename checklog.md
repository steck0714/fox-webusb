# fox-webusb / LibreWolf Check Log

## 1. Test Environment

- OS: Windows
- Browser: LibreWolf
- Python: 3.14.4
- PyUSB: 1.3.1
- fox-webusb: v0.0.0
- Installation source: GitHub ZIP archive
- Source directory:
  `C:\Users\k02tuser\Downloads\v0.0.0\fox-webusb`
- Native Host source directory:
  `C:\Users\k02tuser\Downloads\v0.0.0\fox-webusb\native-host`

## 2. Installation / Host Setup

### Python package tools

Installed successfully:

- pip 26.2.1
- setuptools 84.0.0
- wheel 0.48.0

Result: **PASS**

### PyUSB

Command:

```powershell
python -c "import usb; print(usb.__version__)"
```

Result:

```text
1.3.1
```

Result: **PASS**

### fox_webusb_host import without package installation

Command:

```powershell
python -c "import sys; sys.path.insert(0, 'src'); import fox_webusb_host; print('OK')"
```

Result:

```text
OK
```

Result: **PASS**

### Native Messaging Host registration

`python install.py` completed successfully.

Created:

```text
C:\Users\k02tuser\AppData\Roaming\fox-webusb\fox-webusb-host.bat
C:\Users\k02tuser\AppData\Roaming\fox-webusb\org.fox_webusb.host.json
```

Allowed extension ID:

```text
fox-webusb@local
```

Result: **PASS**

### Native Host startup

The generated launcher started successfully and reported:

```text
[fox-webusb-host] started.
rust acceleration: not built, falling back to pure Python.
device chooser: available.
settings file: C:\Users\k02tuser\AppData\Roaming\fox-webusb\settings.json
```

Result: **PASS**

A later standalone launch ended with:

```text
[fox-webusb-host] fatal error reading from stdin, exiting:
cannot read more than 33554432 bytes
```

This occurred during standalone execution without Firefox Native Messaging input and was not treated as a direct LibreWolf failure.

## 3. LibreWolf / WebUSB API Checks

Testing site:

```text
https://adb.andro.plus/
```

### Secure Context

Result:

```text
true
```

Result: **PASS**

### Origin

Result:

```text
https://adb.andro.plus
```

Result: **PASS**

### `navigator.usb`

Result:

```text
Object { onconnect: null, ondisconnect: null }
```

Result: **PASS**

### `navigator.usb` methods

The following were confirmed as functions:

```text
getDevices()
requestDevice()
addEventListener()
removeEventListener()
```

Result: **PASS**

### USB event properties

The following properties exist:

```text
onconnect
ondisconnect
```

Result: **PASS**

### USB prototype

Prototype properties:

```text
constructor
getDevices
requestDevice
addEventListener
removeEventListener
```

Result: **PASS**

### USB own properties

Own properties:

```text
onconnect
ondisconnect
```

Result: **PASS**

### `getDevices()`

Command:

```javascript
const x = await navigator.usb.getDevices();
console.log(x);
console.log(Array.isArray(x), x?.length);
```

Result:

```text
Array []
true 0
```

Result: **PASS**

Interpretation:

- The call returned a Promise that fulfilled successfully.
- The fulfilled value was an Array.
- Array length was 0 because no authorized physical USB device was available during the test.

## 4. Security / User Gesture Checks

### `requestDevice()` without user gesture

Test:

```javascript
try {
  await navigator.usb.requestDevice({ filters: [] });
} catch (e) {
  console.log(e.name, e.message);
}
```

Result:

```text
SecurityError
requestDevice() must be called from a user gesture (e.g. a click handler)
```

Result: **PASS**

Interpretation:

- The implementation enforces a user gesture requirement for `requestDevice()`.
- The test was intentionally executed from DevTools, not from a click handler.

### `requestDevice()` from an actual site UI

WebADB's Connect action invoked the WebUSB request path. The request reached the fox-webusb polyfill and then failed with:

```text
NetworkError: fox-webusb native host disconnected: disconnected
```

The recorded stack included:

```text
page_polyfill.js: requestDevice
backend.js: requestDevice
connect.tsx
```

Result: **FAIL**

Interpretation:

- The request was not rejected by the user-gesture guard.
- The failure occurred later in the Native Messaging / Native Host path.
- This does not demonstrate successful physical USB device selection.

## 5. Event API Checks

### `addEventListener("connect", ...)`

A handler was registered successfully.

Result:

```text
listener registered: true
```

Result: **PASS**

### `removeEventListener("connect", ...)`

Registration and removal were executed successfully.

Result:

```text
listener removed
```

Result: **PASS**

### `addEventListener("disconnect", ...)` / `removeEventListener("disconnect", ...)`

The combined add/remove test completed successfully.

Result: **PASS**

### Event assignment

Assignments to:

```text
onconnect
ondisconnect
```

were accepted and restored successfully.

Result: **PASS**

### Actual event firing

No physical USB device was available.

Result: **NOT TESTED**

## 6. Global WebUSB Constructors

The following were not exposed as global constructors in the tested page:

```text
USB
USBDevice
USBConfiguration
USBInterface
USBAlternateInterface
USBEndpoint
USBConnectionEvent
USBInTransferResult
USBOutTransferResult
USBIsochronousInTransferResult
USBIsochronousOutTransferResult
USBIsochronousInTransferPacket
USBIsochronousOutTransferPacket
```

Result: **NOT EXPOSED GLOBALLY**

Important:

This result does **not** prove that the corresponding device-side interfaces are unimplemented. No authorized `USBDevice` instance was available to inspect.

## 7. USBDevice Instance / Transfer Checks

No authorized physical USB device was available, so the following were not executed against an actual `USBDevice` instance:

```text
open()
close()
selectConfiguration()
claimInterface()
releaseInterface()
selectAlternateInterface()
controlTransferIn()
controlTransferOut()
transferIn()
transferOut()
clearHalt()
reset()
isochronousTransferIn()
isochronousTransferOut()
```

Result: **NOT TESTED**

Also not tested:

- USB configuration object behavior
- USB interface object behavior
- USB alternate setting behavior
- USB endpoint object behavior
- Transfer result objects
- Actual endpoint I/O

## 8. Same-Origin iframe Check

A same-origin iframe test was performed.

Result:

```text
navigator.usb missing
```

Result: **FAIL**

Interpretation:

- In the tested iframe context, `navigator.usb` was not exposed.
- This is an observed runtime result.
- The test did not establish whether this is intentional behavior, an extension injection limitation, or another iframe-specific condition.

## 9. Worker Check

A worker test reported:

```text
hasNavigator: true
hasUSB: false
usbType: "undefined"
```

Result: **NOT VERIFIED**

No conclusion of full Worker support or lack of support is made from this test alone.

## 10. Permissions Policy Check

The tested page did not expose the Permissions Policy API used by the checker.

Result:

**NOT VERIFIED**

No conclusion about WebUSB Permissions Policy behavior is made from this result alone.

## 11. Multi-Site Testing

At least two different WebUSB-capable sites were tested:

- WebUSB test site
- WebADB (`https://adb.andro.plus/`)

On WebADB, the following were confirmed:

```text
navigator.usb                 PASS
requestDevice                 PASS (method exists)
getDevices                    PASS (method exists)
getDevices()                  PASS
```

The WebADB Connect action reached `requestDevice()` and then failed with:

```text
NetworkError: fox-webusb native host disconnected: disconnected
```

This indicates that the observed `requestDevice()` failure was reproduced in an actual WebADB workflow, not only by a console call.

## 12. CSS / Font Warnings

The LibreWolf console contained many page-level warnings related to:

```text
Meiryo
Noto Sans JP
BIZ UDGothic
MS Mincho
Yu Mincho
Selawik
-moz-osx-font-smoothing
-moz-focus-inner
-ms-high-contrast
padding-top / padding-right / padding-bottom parsing
```

These were treated as **site CSS / font compatibility warnings**, not as fox-webusb failures.

## 13. Overall Result

### Confirmed working

- Python environment
- pip / setuptools / wheel installation
- PyUSB import
- `fox_webusb_host` import
- Native Messaging Host registration
- Native Host startup
- LibreWolf extension loading
- Secure Context
- Origin reporting
- `navigator.usb`
- `getDevices()`
- `requestDevice()` method presence
- `addEventListener()`
- `removeEventListener()`
- `onconnect`
- `ondisconnect`
- USB prototype structure
- USB own properties
- `getDevices()` Promise -> Array behavior
- User gesture enforcement
- Event listener registration/removal
- `onconnect` / `ondisconnect` assignment

### Confirmed failing

- `requestDevice()` during actual WebADB Connect workflow:
  `NetworkError: fox-webusb native host disconnected: disconnected`
- Same-origin iframe:
  `navigator.usb` not exposed

### Not tested / not verified

- Physical USB device selection
- `USBDevice` instance methods
- Opening a physical device
- Interface claiming/releasing
- Endpoint access
- Control transfers
- Bulk/interrupt transfers
- Isochronous transfers
- Actual `connect` / `disconnect` event firing
- Worker WebUSB support
- Permissions Policy behavior

## 14. Current Conclusion

The LibreWolf test successfully demonstrates that fox-webusb can expose a WebUSB-like API surface to a top-level web page and that several basic API behaviors work.

The most significant current failure is the `requestDevice()` native path, which reaches the fox-webusb request logic but ends with a Native Host disconnection.

Physical USB communication has not been demonstrated because no physical USB device was available during this test.

The iframe result is also a confirmed runtime limitation in the tested environment.

## 15. Next Hardware Test

When a test USB device becomes available, the next validation stage should focus on:

```text
requestDevice()
    ->
USBDevice
    ->
open()
    ->
selectConfiguration()
    ->
claimInterface()
    ->
transfer / control operations
    ->
close()
```

The existing SKIP / NOT TESTED items should then be replaced with measured results rather than inferred results.
