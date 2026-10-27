# Snapshot provenance

- Source: https://lidge-jun.github.io/design-isms/
- Author/repository: https://github.com/lidge-jun/design-isms (lidge-jun)
- Commit: `28d66113e9ab303b898585565e759b0ac2442088`
- Retrieved: 2026-09-19 Asia/Tokyo
- Scope: all 7 public HTML pages, favicon, and every tracked file under `assets/`: 744 files, 567,999,900 bytes. The 331 PNG originals and 331 WebP previews are included without resizing, cropping, recompression, recoloring, or regeneration.
- Acquisition: raw commit-pinned source files, each checked against the GitHub tree's Git blob SHA-1. Playwright CLI opens the live site, compares live text assets to the same hashes, and captures live/local pages for visual verification. See `verification.json` after verification completes.
- Local helper and SKILL.md are integration instructions written for this user. Everything inside `assets/upstream/` is preserved byte-for-byte. Candidate ranking executes the original `DesignFinder.score` from `finder.js` with the original `app-export.js` palette classifier; no new scoring weights are added.
- Stored images are the site's AI-generated mockups/guides, not screenshots of the externally linked example brands. Complete working applications for every mockup are not part of the upstream collection. The published live demos, CSS/JS, snippets, JSON, prompts, and development guides are retained.
- External Google Fonts and Pretendard CDN links remain unchanged. Font binaries, unrelated repository development logs, archives, and third-party example websites are outside this snapshot. Original PNG previews remain locally viewable without the CDN.
- No LICENSE/COPYING file was found in the repository tree and package metadata did not declare a license. Upstream offers personal agent-plugin installation instructions. This is a local reference snapshot with attribution, not a claim of permission to republish the collection, assets, brands, or third-party examples.

Use `node scripts/catalog.mjs stats` for counts, and `source-manifest.json` to verify every stored source file. The snapshot is pinned; it does not auto-update or auto-publish.
