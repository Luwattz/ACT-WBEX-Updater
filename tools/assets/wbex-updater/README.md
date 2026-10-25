# WBEX updater app icon

Created with the built-in imagegen tool on 2026-10-24. Blue rounded square, white
plugin package and clockwise update arrow; transparent outside the icon. This is
the updater's application identity, independent of Full/Lite extension metadata.

- `updater-master.png`: original generated RGBA image.
- `updater.png`: 512 × 512 PNG for preview and reuse.
- `updater.ico`: 16, 20, 24, 32, 40, 48, 64, 96, 128 and 256 pixel representations.

Only the ICO is staged into releases. It supplies both the EXE resource and the
Tk window/titlebar icon. Pillow is used only to export icon formats during asset
preparation; it is not an updater runtime dependency.

Window icons use Windows LoadImageW and WM_SETICON at the system DPI's small
and large icon sizes. Tk's ICO loader resamples the image before supplying its
class icons, producing blurred taskbar artwork even when the ICO includes an
exact-size frame. Native handles are reapplied when Tk maps a new wrapper or
Toplevel and released when the root window is destroyed.

## Generation prompt

Use case: logo-brand. Asset type: production Windows desktop app icon for
LumiDyna ACT WBEX plugin updater. Design one finished, elegant, Apple-inspired
app icon: a vivid cobalt-to-azure blue softly rounded square, centered on a truly
transparent square canvas, occupying about 90% of the canvas with even small
transparent margins. Inside the square, a large simple white isometric software
package/cube combined with one clean clockwise circular update arrow surrounding
the package, clear gap and arrowhead at upper-right. The package and arrow form
one balanced, recognizable pictogram with generous spacing. Bold simple silhouette
and thick enough forms to remain clear at 16, 24, 32 and 48 pixels. Restrained blue
gradient with a very subtle soft inner highlight, crisp beautifully antialiased
contours. Flat near-vector precision, lightly dimensional, calm professional
utility-app aesthetic consistent with white panels and blue controls. No text,
no letters, no numbers, no Apple logo, no watermark, no icon grid, no desktop
mockup, no frame outside the icon, no surrounding glow, no checkerboard pattern,
no large drop shadow. Square high resolution PNG with actual alpha transparency
outside rounded square.
