# ResuMetr brand

## The mark

A gauge, not a letterform. ResuMetr measures a resume, so the sweep is the reading and the
three descending strokes inside are resume lines — the silhouette of a resume block, and
of a bar chart falling away. The filled tick sits at the arc terminus rather than pinned
at maximum, because a real reading rarely is.

## Files

| File | Use |
| --- | --- |
| `resumetr-mark.svg` | The mark on a light ground. Also shipped as `frontend/public/favicon.svg`. |
| `resumetr-mark-inverse.svg` | The mark on a dark ground. |
| `resumetr-lockup.svg` | Mark plus wordmark, light ground. |
| `resumetr-lockup-inverse.svg` | Mark plus wordmark, dark ground. |

The resume lines are `currentColor`, so when the SVG is inlined the mark inverts by
inheritance and only one file is needed. `frontend/src/components/Logo.tsx` is the React
version and takes its gradient from the design tokens. The `-inverse` files exist for
contexts that cannot set colour, such as an `<img>` tag.

## Wordmark

`Resu` in ink, `Metr` in indigo — the same split the product has: the resume, and the
measurement taken of it. Set in Manrope ExtraBold at −1 tracking.

## Colour

| Token | Value | Use |
| --- | --- | --- |
| `--colour-indigo` | `#4457C9` | Arc start, `Metr` |
| `--colour-violet` | `#7159BD` | Arc end, the reading tick |
| `--colour-ink` | `#101C34` | Resume lines, `Resu` |

## Don't

Recolour the arc outside the indigo→violet ramp, set the mark on a mid-tone where neither
variant has contrast, add a container shape, or letterspace the wordmark apart. Minimum
size is 16px; below that the resume lines merge.
