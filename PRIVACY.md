# Privacy

long-image-to-x runs entirely on your own machine.

- **What it reads:** the image or PDF files you ask it to slice.
- **What it writes:** image files in the output folder you choose (by default `x-post/` in the current working directory), plus temporary preview images.
- **What it sends:** nothing. The script makes no network requests and has no telemetry, analytics or logging service.
- **What it stores:** nothing beyond the output files above. It keeps no account, history or profile.
- **Third parties:** on first run, `uv` downloads Pillow, NumPy and, if needed, Python from their usual package sources. That download is made by `uv`, not by this plugin, and carries none of your files or conversation content.

The plugin does not post to X or to any other service. You upload the images yourself.

Questions: open an issue at https://github.com/MacchaCat/long-image-to-x/issues
