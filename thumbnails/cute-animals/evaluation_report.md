# Thumbnail Evaluation — 可爱动物图鉴

- Generated: 2026-08-29
- Method: direct SVG composition with Pillow; no image-generation model was used
- Dimensions: 1792 × 1024
- Reference mode: direct asset composition
- Sources and licenses: [references/source_manifest.md](references/source_manifest.md)

| # | Candidate | Variant | Brand Fit /10 | Text Legibility /10 | Recommendation |
|---|---|---|---:|---:|---|
| 1 | `candidate_01_four_cards_warm.png` | Warm editorial row | 9.2 | 8.8 | Friendly and balanced; strongest for a light editorial page. The small animal labels become secondary at 300px, while the title remains clear. |
| 2 | `candidate_02_four_cards_split.png` | Blue split grid | 8.9 | 9.3 | **Top pick.** The dedicated blue title panel preserves hierarchy at thumbnail size, and the 2×2 animal grid stays easy to scan. |
| 3 | `candidate_03_four_cards_dark.png` | Dark pop row | 9.0 | 9.0 | Strongest social option. High contrast and numbered cards hold up well at small sizes, though the mood is less gentle than candidates 1–2. |

## Recommendations

- Web/article header: `candidate_02_four_cards_split.png`
- Email/mobile: `candidate_02_four_cards_split.png`
- Social sharing: `candidate_03_four_cards_dark.png`
- Softer editorial alternative: `candidate_01_four_cards_warm.png`

## Production notes

- The Chinese headline remains readable in all three 300px previews.
- English animal labels are intentionally secondary and become very small at 300px; remove them if the final placement is consistently below that width.
- Original SVG silhouettes were recoloured and placed directly. Their shapes were not regenerated or traced.
- All text was rendered locally with Microsoft YaHei, avoiding AI-generated spelling artefacts.

## Direct composition specifications

No image-generation prompts were used because this composition directly reuses the selected CC0 SVG assets.

### Candidate 1 — Warm editorial row

1792×1024 article thumbnail. Warm cream background `#F7F1E7`. Large dark navy geometric Chinese headline `可爱动物图鉴` in the upper left. Four tall rounded cards in muted coral, blue, yellow, and mint. One original animal silhouette centred in each card, recoloured dark navy. Minimal flat design, generous whitespace, bilingual labels, small blue `SVG / CC0` badge. Avoid gradients, shadows, textures, and decorative clutter.

### Candidate 2 — Blue split grid

1792×1024 article thumbnail. Left third is solid blue `#2563EB` with large white headline split into two lines and a short light-blue subheading. Right side contains a clean 2×2 grid of rounded pastel cards. One original dark navy animal silhouette per card with bilingual labels. Minimal editorial layout, high contrast, clear mobile hierarchy. Avoid gradients, shadows, textures, and crowded typography.

### Candidate 3 — Dark pop row

1792×1024 social thumbnail. Deep navy background `#111827`, centred white Chinese headline, restrained blue-grey subtitle. Four saturated pastel cards across the lower two-thirds, each with a small numbered dark pill and one original dark navy animal silhouette. Bold flat design, high contrast, compact labels. Avoid gradients, shadows, textures, and low-contrast text.
