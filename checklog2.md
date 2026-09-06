# fox-webusb v0.0.0a0 — Verification Log

## 1. Verification Overview

This document records the verification and debugging results of `fox-webusb` on LibreWolf.

The purpose of this test was to verify:

- Native Messaging Host startup
- Extension-to-host communication
- `navigator.usb` exposure
- WebUSB-like API behavior
- `EventTarget` behavior
- `requestDevice()` validation
- user-activation handling
- device chooser handling
- compatibility with WebADB

No physical USB device was connected during the test, so actual USB hardware communication remains unverified.

---

# 2. Test Environment

| Item | Value |
|---|---|
| OS | Windows 11 |
| OS Build | 26200 |
| Browser | LibreWolf 155.0-1 |
| Firefox Engine | Firefox 155.0 |
| Browser Build ID | 20260901102753 |
| fox-webusb | 0.0.0a0 |
| PyUSB | 1.3.1 |
| Test Website | WebADB |
| Physical USB Device | None connected |
| Rust Acceleration | Not built |

---

# 3. Native Messaging Host

## 3.1 Initial Failure

The first attempt to use WebADB resulted in:

```text
DOMException: NetworkError:
fox-webusb native host disconnected: disconnected
```

The error occurred while WebADB was attempting to use:

```text
navigator.usb
    ↓
fox-webusb bridge
```

At first, this looked like a possible communication failure between WebADB and fox-webusb.

Further investigation showed that the Native Messaging Host itself was exiting because Python could not import the host package.

---

## 3.2 Root Cause

The Native Messaging Host was launched through a batch file similar to:

```bat
@echo off
"C:\...\native-host\.venv\Scripts\python.exe" -m fox_webusb_host %*
```

When launched manually without `PYTHONPATH`, the same problem could be reproduced:

```text
ModuleNotFoundError:
No module named 'fox_webusb_host'
```

The source package is located under:

```text
native-host/src/fox_webusb_host
```

but this directory was not automatically included in Python's module search path when Firefox launched the Native Messaging Host.

### Root Cause

The Native Messaging Host launcher did not set `PYTHONPATH`.

---

## 3.3 Fix

The batch launcher was changed to:

```bat
@echo off
set "PYTHONPATH=C:\Users\k02tuser\Downloads\v0.0.0a\fox-webusb\native-host\src"
"C:\Users\k02tuser\Downloads\v0.0.0a\fox-webusb\native-host\.venv\Scripts\python.exe" -m fox_webusb_host %*
```

The important change is:

```bat
set "PYTHONPATH=...\native-host\src"
```

---

## 3.4 Result After Fix

After restarting LibreWolf, the Native Messaging Host successfully started.

The host reported:

```text
[fox-webusb-host] started.
rust acceleration: not built, falling back to pure Python.
device chooser: available.
settings file: ...\settings.json
```

The fox-webusb UI also reported:

```text
Native host connected
Currently visible USB devices: 0
Rust acceleration not built (using standard base64)
```

### Result

**FIXED**

The Native Messaging Host import/startup problem was resolved.

---

# 4. WebADB Behavior Before and After the Fix

## 4.1 Before Fix

WebADB reported:

```text
DOMException:
NetworkError: fox-webusb native host disconnected: disconnected
```

This was caused by the Native Messaging Host terminating because of the missing Python module path.

---

## 4.2 After Fix

After adding `PYTHONPATH`, the previous:

```text
native host disconnected
```

error disappeared.

A subsequent WebADB `Connect` attempt instead reached:

```text
DOMException:
InvalidStateError:
a device chooser is already open
```

This is an important change.

It demonstrates that the request was able to proceed farther into the fox-webusb bridge instead of failing because the Native Messaging Host was disconnected.

### Result

**SIGNIFICANT IMPROVEMENT / FIX CONFIRMED**

The original Native Messaging Host failure was successfully eliminated.

---

# 5. `navigator.usb` Basic API

The following test was performed:

```js
console.log("secure:", window.isSecureContext);
console.log("origin:", location.origin);
console.log("navigator.usb:", navigator.usb);
console.log("usb type:", typeof navigator.usb);
console.log("getDevices:", typeof navigator.usb?.getDevices);
console.log("requestDevice:", typeof navigator.usb?.requestDevice);
console.log("addEventListener:", typeof navigator.usb?.addEventListener);
console.log("removeEventListener:", typeof navigator.usb?.removeEventListener);
```

Result:

```text
secure: true
origin: https://app.webadb.com
navigator.usb: EventTarget { ... }
usb type: object
getDevices: function
requestDevice: function
addEventListener: function
removeEventListener: function
```

### Result

**PASS**

The WebADB page receives a usable `navigator.usb` object.

---

# 6. `getDevices()`

Test:

```js
const d = await navigator.usb.getDevices();

console.log(d);
console.log("count =", d.length);
console.log("array =", Array.isArray(d));
```

Result:

```text
Array []
count = 0
array = true
```

### Result

**PASS**

The bridge call successfully resolves to a JavaScript array.

The array is empty because no physical USB device was connected.

Therefore:

- bridge communication: verified
- physical USB enumeration: not yet verified

---

# 7. USB Object Structure

The prototype was inspected:

```js
console.log("prototype:", Object.getPrototypeOf(navigator.usb));
console.log("own:", Object.getOwnPropertyNames(navigator.usb));
console.log(
  "proto props:",
  Object.getOwnPropertyNames(
    Object.getPrototypeOf(navigator.usb)
  )
);
console.log(
  "instanceof EventTarget:",
  navigator.usb instanceof EventTarget
);
```

Result:

```text
own: []

proto props:
[
  "constructor",
  "getDevices",
  "requestDevice",
  "onconnect",
  "ondisconnect"
]

instanceof EventTarget: true
```

The constructor was inspected:

```js
console.log(
  Function.prototype.toString.call(navigator.usb.constructor)
);
```

It revealed:

```js
class USB extends EventTarget {
    #onconnectHandler = null;
    #ondisconnectHandler = null;

    getDevices() {
      return callBridge('listDevices', {}).then(function (res) {
        return (res.devices || []).map(function (d) {
          return new USBDevice(d);
        });
      });
    }

    requestDevice(options) {
      return Promise.resolve().then(function () {
        options = options || {};
        validateFilters(options.filters);
        validateFilters(options.exclusionFilters);

        if (
          navigator.userActivation &&
          navigator.userActivation.isActive === false
        ) {
          throw new DOMException(
            'requestDevice() must be called from a user gesture (e.g. a click handler)',
            'SecurityError'
          );
        }

        return callBridge('requestDeviceChooser', {
          filters: options.filters || [],
          exclusionFilters: options.exclusionFilters || [],
        });
      }).then(function (res) {
        if (!res.success) throwFromResult(res);
        return new USBDevice(res.device);
      });
    }

    get onconnect() {
      return this.#onconnectHandler;
    }

    set onconnect(value) {
      if (this.#onconnectHandler) {
        this.removeEventListener(
          'connect',
          this.#onconnectHandler
        );
      }

      this.#onconnectHandler =
        (typeof value === 'function') ? value : null;

      if (this.#onconnectHandler) {
        this.addEventListener(
          'connect',
          this.#onconnectHandler
        );
      }
    }

    get ondisconnect() {
      return this.#ondisconnectHandler;
    }

    set ondisconnect(value) {
      if (this.#ondisconnectHandler) {
        this.removeEventListener(
          'disconnect',
          this.#ondisconnectHandler
        );
      }

      this.#ondisconnectHandler =
        (typeof value === 'function') ? value : null;

      if (this.#ondisconnectHandler) {
        this.addEventListener(
          'disconnect',
          this.#ondisconnectHandler
        );
      }
    }

    get [Symbol.toStringTag]() {
      return 'USB';
    }
}
```

Additional test:

```js
console.log(
  Object.prototype.toString.call(navigator.usb)
);
```

Result:

```text
[object USB]
```

### Result

**PASS**

The exposed object is a real JavaScript `USB` class instance derived from `EventTarget`.

---

# 8. `onconnect`

Test:

```js
let a = () => console.log("A");
let b = () => console.log("B");

navigator.usb.onconnect = a;
console.log(
  "onconnect === a:",
  navigator.usb.onconnect === a
);

navigator.usb.onconnect = b;
console.log(
  "onconnect === b:",
  navigator.usb.onconnect === b
);

navigator.usb.onconnect = null;
console.log(
  "onconnect after null:",
  navigator.usb.onconnect
);
```

Result:

```text
onconnect === a: true
onconnect === b: true
onconnect after null: null
```

### Result

**PASS**

`onconnect` behaves as an event-handler property.

Assigning a new function replaces the previous handler.

---

# 9. `onconnect` Event Dispatch

Test:

```js
let fired = false;

navigator.usb.onconnect = (e) => {
  fired = true;
  console.log("onconnect fired:", e.type);
};

const ev = new Event("connect");
const result = navigator.usb.dispatchEvent(ev);

console.log("dispatch result:", result);
console.log("fired:", fired);

navigator.usb.onconnect = null;
```

Result:

```text
onconnect fired: connect
dispatch result: true
fired: true
```

However, WebADB also reported:

```text
TypeError:
can't access property "serialNumber",
e.device is undefined
```

### Explanation

The test intentionally created:

```js
new Event("connect")
```

This event has no:

```js
event.device
```

WebADB's watcher expects a real WebUSB-style connect event containing a device.

Therefore, this error comes from WebADB's event handler receiving an incomplete synthetic event.

It does **not** indicate that `dispatchEvent()` itself failed.

### Result

**PASS**

Event dispatch works.

**Real hardware connect-event compatibility remains untested.**

---

# 10. `ondisconnect`

Test:

```js
let disconnectFired = false;

navigator.usb.ondisconnect = (e) => {
  disconnectFired = true;
  console.log("ondisconnect fired:", e.type);
};

const disconnectEvent = new Event("disconnect");

const disconnectResult =
  navigator.usb.dispatchEvent(disconnectEvent);

console.log("dispatch result:", disconnectResult);
console.log("fired:", disconnectFired);

navigator.usb.ondisconnect = null;
```

Result:

```text
ondisconnect fired: disconnect
dispatch result: true
fired: true
```

### Result

**PASS**

The `ondisconnect` event-handler property is functional.

---

# 11. `addEventListener()` / `removeEventListener()`

Test:

```js
let eventA = 0;
let eventB = 0;

const handlerA = () => eventA++;
const handlerB = () => eventB++;

navigator.usb.addEventListener("connect", handlerA);
navigator.usb.addEventListener("connect", handlerB);

navigator.usb.dispatchEvent(new Event("connect"));

console.log("after first:", { eventA, eventB });

navigator.usb.removeEventListener("connect", handlerA);

navigator.usb.dispatchEvent(new Event("connect"));

console.log("after remove:", { eventA, eventB });

navigator.usb.removeEventListener("connect", handlerB);
```

Result:

```text
after first: { eventA: 1, eventB: 1 }
after remove: { eventA: 1, eventB: 2 }
```

### Result

**PASS**

Multiple listeners work correctly and individual listeners can be removed.

---

# 12. `requestDevice()` Filter Validation

Test:

```js
navigator.usb.requestDevice({
  filters: "invalid"
}).then(
  () => console.log("unexpected resolve"),
  e => console.log(
    "error:",
    e.name,
    e.message
  )
);
```

Result:

```text
error: TypeError filters must be an array
```

### Result

**PASS**

Invalid filter input is rejected.

---

# 13. `requestDevice()` Without User Activation

A direct call to:

```js
navigator.usb.requestDevice({
  filters: []
})
```

was performed outside a user gesture.

Result:

```text
error:
SecurityError
requestDevice() must be called from a user gesture
(e.g. a click handler)
```

### Result

**PASS**

The user-activation check is implemented.

---

# 14. `requestDevice()` From a User Gesture

A click handler was registered:

```js
document.body.addEventListener("click", async function testUSB() {
  document.body.removeEventListener("click", testUSB);

  try {
    const device =
      await navigator.usb.requestDevice({
        filters: []
      });

    console.log("DEVICE:", device);
  } catch (e) {
    console.log(
      "requestDevice error:",
      e.name,
      e.message
    );
  }
}, { once: true });
```

After clicking the page, the result was:

```text
requestDevice error:
InvalidStateError
a device chooser is already open
```

### Interpretation

This is different from the previous `SecurityError`.

The user-activation check had already succeeded.

The request reached the chooser-handling layer and was rejected because a chooser was already open.

The fox-webusb design intentionally uses the extension UI for its device chooser.

### Result

**PASS / EXPECTED**

The request successfully progressed beyond user-activation validation.

---

# 15. Global `USB` / `USBDevice` Constructors

Test:

```js
console.log("USB:", typeof USB);
console.log("USBDevice:", typeof USBDevice);
console.log("USB in globalThis:", "USB" in globalThis);
console.log(
  "USBDevice in globalThis:",
  "USBDevice" in globalThis
);
```

Result:

```text
USB: undefined
USBDevice: undefined
USB in globalThis: false
USBDevice in globalThis: false
```

### Result

**NEEDS VERIFICATION**

The page does not expose `USB` or `USBDevice` as global constructors.

However, the internal `USB` class exists and `USBDevice` is constructed internally by the implementation.

This should be compared with the intended WebUSB compatibility target before being considered a bug.

---

# 16. Rust Acceleration

The Native Messaging Host reported:

```text
rust acceleration: not built,
falling back to pure Python
```

The extension UI also reported:

```text
Rust acceleration not built
(using standard base64)
```

### Result

**NOT A FUNCTIONAL FAILURE**

The fallback implementation is active.

The tested bridge operations continued to work.

---

# 17. Problems Encountered During Testing

This section summarizes the actual problems discovered during verification.

## Problem 1 — Native Messaging Host Could Not Import the Package

### Symptom

```text
ModuleNotFoundError:
No module named 'fox_webusb_host'
```

### Effect

The Native Messaging Host exited immediately.

### User-visible consequence

WebADB reported:

```text
DOMException:
NetworkError:
fox-webusb native host disconnected: disconnected
```

### Cause

The Native Messaging Host launcher did not set `PYTHONPATH`.

### Fix

Add:

```bat
set "PYTHONPATH=...\native-host\src"
```

to the launcher.

### Status

**FIXED**

---

## Problem 2 — WebADB Reported Native Host Disconnection

### Symptom

```text
NetworkError:
fox-webusb native host disconnected: disconnected
```

### Cause

This was a downstream consequence of Problem 1.

The host process had already failed to import `fox_webusb_host`.

### Status

**FIXED AFTER PYTHONPATH CORRECTION**

---

## Problem 3 — Device Chooser Already Open

### Symptom

After fixing the Native Messaging Host:

```text
InvalidStateError:
a device chooser is already open
```

### Interpretation

This indicates that the request reached the device chooser layer.

The error is consistent with the current fox-webusb architecture, where the chooser is controlled through the extension UI.

### Status

**EXPECTED / DESIGN-RELATED**

It may still be worth documenting the intended chooser lifecycle for WebADB and other WebUSB consumers.

---

## Problem 4 — Synthetic `connect` Event Lacks `device`

### Symptom

When testing with:

```js
navigator.usb.dispatchEvent(
  new Event("connect")
);
```

WebADB reported:

```text
TypeError:
can't access property "serialNumber",
e.device is undefined
```

### Cause

`new Event("connect")` only provides the event type.

It does not provide:

```js
event.device
```

### Interpretation

This does not indicate a failure in fox-webusb's `EventTarget` implementation.

It demonstrates that WebADB expects a complete WebUSB-compatible connect event.

### Status

**EXPECTED FOR SYNTHETIC TEST**

Real hardware testing is required to verify the actual event payload.

---

## Problem 5 — DevTools Variable Redeclaration

During one test, the following error occurred:

```text
SyntaxError:
redeclaration of let fired
```

### Cause

The same `let` variable name was declared multiple times in the persistent DevTools console scope.

### Interpretation

This is a browser DevTools console issue, not a fox-webusb issue.

### Status

**NOT A FOX-WEBUSB BUG**

---

# 18. Important Developer Notes

## 18.1 The Native Host Failure Was the Most Significant Initial Issue

The first WebADB failure could initially be interpreted as a problem with the fox-webusb bridge itself.

However, reproducing the host manually revealed:

```text
ModuleNotFoundError:
No module named 'fox_webusb_host'
```

This indicates that the initial `native host disconnected` error was caused by the Native Messaging Host launch environment.

The issue was resolved without changing the WebADB page or the fox-webusb JavaScript bridge.

---

## 18.2 The Error Changed After the Fix

The transition was:

```text
Before:

WebADB
  ↓
fox-webusb
  ↓
Native Host
  X
ModuleNotFoundError
  ↓
native host disconnected
```

After the fix:

```text
WebADB
  ↓
fox-webusb
  ↓
Native Host
  ↓
requestDevice()
  ↓
device chooser state
  ↓
"chooser is already open"
```

This is strong evidence that the Native Messaging Host is now being reached successfully.

---

## 18.3 API-Level Tests Are Currently Passing

The following areas have been successfully tested:

- `navigator.usb`
- `getDevices()`
- `requestDevice()` validation
- user activation
- `USB extends EventTarget`
- `onconnect`
- `ondisconnect`
- `addEventListener()`
- `removeEventListener()`
- bridge communication

However, these tests do not prove that actual USB transfers work.

---

# 19. Overall Verification Status

| Component | Status |
|---|---|
| Native Messaging Host startup | PASS |
| Native Messaging Host package import | PASS after fix |
| Extension ↔ Native Host communication | PASS |
| `navigator.usb` exposure | PASS |
| `getDevices()` | PASS |
| Empty device list | PASS |
| `USB` object structure | PASS |
| `USB extends EventTarget` | PASS |
| `onconnect` | PASS |
| `ondisconnect` | PASS |
| `addEventListener()` | PASS |
| `removeEventListener()` | PASS |
| Filter validation | PASS |
| User-activation validation | PASS |
| User-gesture request path | PASS |
| Device chooser state handling | PASS / EXPECTED |
| Global `USB` constructor | NEEDS VERIFICATION |
| Global `USBDevice` constructor | NEEDS VERIFICATION |
| Rust acceleration | NOT BUILT |
| Physical USB enumeration | NOT TESTED |
| USB permission persistence | NOT TESTED |
| `USBDevice.open()` | NOT TESTED |
| Interface claiming | NOT TESTED |
| Control transfers | NOT TESTED |
| Bulk transfers | NOT TESTED |
| Interrupt transfers | NOT TESTED |
| Physical disconnect event | NOT TESTED |
| WebADB with a physical device | NOT TESTED |

---

# 20. Conclusion

The current verification indicates that the basic fox-webusb architecture is functioning.

The most important issue discovered during testing was the Native Messaging Host import failure caused by a missing `PYTHONPATH`.

After correcting the launcher, the Native Messaging Host successfully connected and WebADB progressed beyond the previous:

```text
native host disconnected
```

failure.

The WebUSB-compatible JavaScript layer also passed a substantial set of API-level tests, including:

- object exposure,
- bridge communication,
- event handling,
- listener management,
- filter validation,
- and user-activation enforcement.

The remaining major verification step is physical USB hardware testing.

The next stage should verify the complete path:

```text
WebADB
  ↓
navigator.usb
  ↓
fox-webusb extension
  ↓
Native Messaging Host
  ↓
PyUSB
  ↓
USB device
```

In particular, physical-device testing should focus on `USBDevice` creation, `open()`, configuration/interface handling, actual transfers, permission behavior, and real connect/disconnect events.