# Fonts

All four are licensed under the SIL Open Font License 1.1 (see `OFL.txt`).

| File | Font | Source | Notes |
| --- | --- | --- | --- |
| `Geist-Variable.woff2`, `GeistMono-Variable.woff2` | Geist, Geist Mono (Vercel) | copied from the AstroBar site | page type |
| `NotoSans-Variable.woff2` | Noto Sans (Google) | fontsource, latin subset | stands in for Discord's gg sans |
| `SourceCodePro-Variable.woff2` | Source Code Pro (Adobe) | `adobe-fonts/source-code-pro`, `VF/SourceCodeVF-Upright.ttf` | subset with pyftsubset to Latin, Latin-1, Latin Extended-A, punctuation, arrows, box drawing, block elements and geometric shapes, so the bot's `└─`, `▓░` and `■ ▶` render in the same font as the text |

Rebuild the Source Code Pro subset:

```bash
pyftsubset SourceCodeVF-Upright.ttf \
  --unicodes="U+0020-007E,U+00A0-017F,U+2010-2027,U+2030-205E,U+2190-21FF,U+2500-259F,U+25A0-25FF" \
  --layout-features='*' --flavor=woff2 --output-file=SourceCodePro-Variable.woff2
```
