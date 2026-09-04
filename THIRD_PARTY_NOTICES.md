# Third-Party Notices

This file records external projects reviewed or adapted while developing DripCut. DripCut's own
license remains in `LICENSE`.

## Current planning milestone

No source files or substantial source-code portions from the projects below were copied into
DripCut during the 2026-08-31 architecture audit. The listed concepts were studied and translated
into DripCut-native design proposals. If implementation later copies or modifies source code,
the applicable copyright and MIT license notice must accompany that code.

| Repository | Audited revision | License | Files/source reused | Concepts adapted | Modifications |
|---|---|---|---|---|---|
| `https://github.com/darkzOGx/youtube-automation-agent` | `260d7a9` | MIT, copyright 2025 YouTube Automation Agent Contributors | None | Workflow checkpoints, editorial approval, provenance, upload reconciliation, analytics recommendations | Reframed as tenant-aware, provider-neutral DripCut architecture |
| `https://github.com/harry0703/MoneyPrinterTurbo` | `d7d4a13` | MIT, copyright 2024 Harry | None | Script/TTS/visual/music/caption/assembly stage boundaries and batch presets | Reframed behind DripCut provider ports and workflow stages |
| `https://github.com/msitarzewski/agency-agents` | `3c95888` | MIT, copyright 2025 AgentLand Contributors | None | Specialist review, evidence gates, performance and reality checks | Used as a review methodology, not runtime code |

## Future update rule

For any later third-party implementation reuse, add:

- repository and exact revision;
- upstream file paths and DripCut destination paths;
- license and copyright notice;
- whether the source was copied, modified, or cleanly reimplemented;
- a summary of modifications;
- any additional attribution, data, model, font, media, or provider terms.

Do not copy assets, templates, model weights, or media merely because source code is permissively
licensed. Those materials may have separate terms.
