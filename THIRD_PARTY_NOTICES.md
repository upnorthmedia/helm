# Third-party notices

Helm includes or is derived from the third-party material below.

## openharness cable frame (MIT)

From [autonomous-ai/openharness](https://github.com/autonomous-ai/openharness) at commit `a441303f550cd8c15fc34d64f453f662d113b635`.

| Path in Helm | Relation to openharness |
| --- | --- |
| `tests/vectors/cable_frame.txt` | copied unchanged from `cli/src/cable/vectors/cable_frame.txt` |
| `helm/wire/frame.py` | Python port of `devices/harness-pro/firmware/main/cable/cable_frame.h` and `cable_frame.c` |
| `firmware/core/helm_frame.c`, `firmware/core/helm_frame.h` | C reimplementation of the same frame, matching `helm/wire/frame.py` byte for byte |

These files are used under the following license.

```
MIT License

Copyright (c) 2026 Autonomous, Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Logo lettering: Outfit

The word "helm" in the logo (`case/logo/logo-h1-wheel-helm.svg` and `.dxf`) is set in the [Outfit](https://fonts.google.com/specimen/Outfit) typeface, licensed under the SIL Open Font License 1.1, and turned to outlines. No font files are included.
