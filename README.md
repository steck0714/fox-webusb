# fox-webusb

⚠️ **Experimental (v0.0.0)**: The core implementation connecting down to actual USB communication is complete. However, this is an initial pre-release and has **not yet been verified with physical devices**. Use with caution.

## About
An experimental port of [Mock-webusb](https://github.com/steck0714/mock-webusb), aimed at creating a new WebUSB API mock implementation. 

Unlike purely visual or superficial polyfills, `fox-webusb` is architected to handle the entire pipeline down to real underlying USB communication.

## Quick Start (v0.0.0)

Once `fox-webusb` polyfill is loaded, it provides the standard `navigator.usb` interface:

```html
<!-- Load the library -->
<script src="https://jsdelivr.net"></script>

<script>
(async () => {
  // Check if fox-webusb successfully provided navigator.usb
  if (!navigator.usb) {
    throw new Error("fox-webusb is not initialized");
  }

  console.log("fox-webusb:", navigator.usb);

  // Fetch connected USB devices via actual underlying communication
  const devices = await navigator.usb.getDevices();
  console.log("USB devices:", devices);
})();
</script>
```

## Current Status & Roadmap
- [x] Create repository 
- [x] Technical research & design
- [x] Implement initial mock logic
- [x] Minimal working demo (Complete core pipeline to actual USB)
- [ ] Physical device verification & hardware testing 🧪 (Next step)
- [ ] API stabilization

## Credits & License
Derived from [steck0714/Mock-webusb](https://github.com/steck0714/mock-webusb) under the MIT License
