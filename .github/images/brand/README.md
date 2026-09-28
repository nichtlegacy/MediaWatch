# MediaWatch logo

A ribbon **M** whose two counters are play triangles (▶ ◀): media, plus the
name. One gradient runs across it from amber through violet to cyan.

| File | Use |
| --- | --- |
| `logo.svg` | The app tile: the mark on a dark rounded square. README header, favicon (`landing/favicon.svg`), wiki logo (`docs/assets/logo.svg`). |
| `logo-mark.svg` | The mark alone, transparent, for light or dark surfaces. |
| `discord-avatar.svg` / `.png` | Full-bleed square with the mark small enough for Discord's round crop. Upload the PNG as the bot's profile picture (Developer Portal → Bot → Icon). The demo uses the SVG as `landing/avatar.svg`. |
| `logo-1024.png` | The tile as a 1024 px PNG, for places that do not take SVG. |
| `landing/logo.png` | The tile as a 512 px PNG at `https://mediawatch.nichtlegacy.com/logo.png`. The example config uses it as `dashboard.icon_url` and `footer_icon_url`: Discord embeds do not show SVG. |
| `social-preview.png` | GitHub's social preview, 1280×640: logo, name, headline and the live dashboard from the landing page demo. Set under Settings → General → Social preview; GitHub has no API for it. |
| `logo-source-tile.png`, `logo-source-transparent.png` | The AI-generated originals the vector was traced from. Kept for reference only; do not ship them. |

## How the SVGs were made

The glyph was traced from `logo-source-tile.png` with potrace (`potracer`), keeping
only the glyph contour, and filled with a real SVG gradient instead of the
bitmap's colours. The gradient runs along the glyph's own top-left to
bottom-right diagonal (`gradientUnits="userSpaceOnUse"`, 236,285 → 1018,980 in
source pixels) with stops measured from the source image:

`#ffc60a` 0 · `#fea624` .125 · `#fa737d` .25 · `#d048e0` .375 · `#8a4cfb` .5 ·
`#3d71fc` .625 · `#019cfd` .75 · `#00bffd` .875 · `#00dcff` 1

The tile is `#11111c` → `#07070c` with a 7 % white hairline, corner radius 228
of 1024, the glyph at 69 % of the tile width (the source image's proportion).
The avatar puts the glyph at 60 % so the round crop never touches it.

PNG and ICO sizes (`landing/favicon.ico`, `icon-32.png`, `apple-touch-icon.png`,
`.github/images/logo.png`) are rendered from these SVGs in a browser, since
ImageMagick's SVG renderer drops the gradient.
