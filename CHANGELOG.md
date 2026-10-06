# Changelog

## [0.13.0] - 2026-10-06

### Features
- feat(auth): opt-in OAuth 2.1 for the streamable-http transport (8d3a817)

### Documentation
- docs(resources): verify and correct shipped rules, guides and prompts (7224e0f)


## [0.12.2] - 2026-10-03

### Bug Fixes
- fix(deps): require fastmcp 4.0.10 for MCP 2026-07-28 (a3a6495)

### Documentation
- docs: complete STE-100 pass; tighten MCP 2026-07-28 wording (c095c55)
- docs: claim MCP 2026-07-28 support; AEO/SEO and STE-100 pass (825de6e)


## [0.12.1] - 2026-09-28

### Bug Fixes
- fix: close the closing-review findings on 0.12.0 (f653b53)


## [0.12.0] - 2026-09-27

### Refactoring
- refactor: shared annotation aliases and two small helpers in the tool module (f6a1723)
- refactor: inline one-caller client methods into their tools (6524678)
- refactor: drop unused mypy config and three one-caller helpers (8f6684a)

### Documentation
- docs: record the test-confidence and error-contract spec (1c18286)

### Chores
- chore: housekeeping remainder from the review pass (605c4a8)

### Other
- build: fix the derive script after the manifest change (4c1782d)
- build: derive the whole Gemini manifest from server.json (48ca1b0)
- build: derive gemini-extension.json and llms.txt instead of hand-maintaining them (4f547c2)
- deps: fastmcp 4.0.10 (8061107)


## [0.11.0] - 2026-09-26

### Features
- feat: report bugs as tool errors, keep the API envelope for expected failures (6d0c04a)


## [0.10.3] - 2026-09-25

### Tests
- test: pin the wire request, the failure envelope and the registry per tool (11ef4f7)
- test: share the through-Client fixtures and close every client (b1367ab)

### Chores
- chore: ignore the .internal tracker directory (4b6dc25)

### Other


## [0.10.2] - 2026-09-20

### Tests
- test: pin the HTML guard on the raw response path (8a3236a)

### Other


## [0.10.1] - 2026-09-20

### Bug Fixes
- fix: stop link checks reddening unrelated PRs, and unify project-URL parsing (611d5ae)


## [0.10.0] - 2026-09-20

### Bug Fixes
- fix: surface GitLab paging headers so list tools stop truncating silently (d68b3ee)

### Refactoring
- refactor: share response-body decoding between both request paths (ba79996)


## [0.9.7] - 2026-09-20

### Bug Fixes
- fix(deps): bump click to clear PYSEC-2026-2132 (a126341)


## [0.9.6] - 2026-09-20

### Chores
- chore(deps): bump anyio in the uv group across 1 directory (92af51b)


## [0.9.5] - 2026-09-20

### Bug Fixes
- fix(ci): changelog classified commits by whole message, not subject (418527e)

### Chores
- chore(deps): bump cryptography in the uv group across 1 directory (ce94c53)


## [0.9.4] - 2026-09-20

### Bug Fixes
- fix: correct error masking in merge sequence, tighten docs and messages (7b43094)

### Documentation
- docs: consolidate GEMINI.md into AGENTS.md (bcfb75f)

### Chores
- chore: ignore local 1Password plugin state (8d0b554)


## [0.9.3] - 2026-08-22

### Chores
- chore(deps): bump mcp in the uv group across 1 directory (fcf3ec8)


## [0.9.2] - 2026-07-08

### Chores
- chore(ci): bump actions/checkout from 6 to 7 (c32bdfb)
- chore(deps): bump pydantic-settings in the uv group across 1 directory (41a233e)


## [0.9.1] - 2026-06-16

### Documentation
- docs: fix doc drifts and bump server.json/gemini-extension.json in release workflow (458c169)


## [0.9.0] - 2026-06-16

### Features
- feat: accept full GitLab URLs in project_id and group_id params (3ef4c5a)

### Documentation
- docs: front-load actions and return values in tool descriptions (d36cde3)

### Chores
- chore(deps): bump python-dotenv from 1.2.1 to 1.2.2 (2637e5a)
- chore(deps): bump authlib from 1.6.8 to 1.6.12 (5ae17fc)
- chore(deps): bump cryptography from 46.0.5 to 48.0.1 (c465c53)
- chore(deps-dev): bump pytest from 9.0.2 to 9.0.3 (8ae0d3b)
- chore(deps): bump starlette from 0.52.1 to 1.3.1 (9701556)
- chore(deps): bump idna from 3.11 to 3.15 (472ce05)
- chore(deps): bump fastmcp from 3.0.1 to 3.2.0 (500c1b7)
- chore(ci): bump codecov/codecov-action from 5 to 7 (6337fa0)
- chore(deps): bump pyjwt from 2.12.0 to 2.13.0 (5749f9a)
- chore(deps): bump pygments from 2.19.2 to 2.20.0 (273640e)
- chore(deps): bump python-multipart from 0.0.22 to 0.0.31 (3a9fef7)
- chore(ci): bump softprops/action-gh-release from 2 to 3 (194e2c2)
- chore(deps): bump pyjwt from 2.11.0 to 2.12.0 (9c9ddd3)

### Other


## [0.8.0] - 2026-03-05

### Features
- feat: slim pipeline and job responses (#44) (f52a665)


## [0.7.1] - 2026-03-05

### Documentation
- docs: add Documentation Freshness rule to AGENTS.md (#43) (e06baa2)


## [0.7.0] - 2026-03-03

### Features
- feat: MR approval tools, startup logging, approval resources (#41) (c4bcf19)


## [0.6.11] - 2026-02-27

### Bug Fixes
- fix: shorten server.json description to <=100 chars for MCP Registry (#38) (f0b7456)


## [0.6.10] - 2026-02-27

### Bug Fixes
- fix: correct broken MCP Registry URLs (#37) (f170046)


## [0.6.9] - 2026-02-27

### Chores
- chore: improve SEO and discoverability (#36) (f9ed76d)


## [0.6.8] - 2026-02-27

### Bug Fixes
- fix: harden resource/prompt loading and add URL support (#34) (0e493ea)


## [0.6.7] - 2026-02-27

### Features
- feat: add MCP Registry auto-publish on release (977d699)


## [0.6.6] - 2026-02-25

### Bug Fixes
- fix: update installation gateway URLs to SPA route (#33) (df8e6cb)


## [0.6.5] - 2026-02-25

### Chores
- chore(ci): bump actions/checkout from 4 to 6 (#32) (bd0bf9b)
- chore(ci): bump astral-sh/setup-uv from 5 to 7 (#31) (c5c64a9)
- chore(ci): bump codecov/codecov-action from 4 to 5 (#30) (8542487)
- chore: add Dependabot for Python deps and GitHub Actions (#29) (a0d64ec)


## [0.6.4] - 2026-02-24

### Features
- feat: add Gemini CLI extension manifest and context (#28) (d048429)


## [0.6.3] - 2026-02-24

### Documentation
- docs: sync README structure across MCP repos (#27) (9088736)


## [0.6.2] - 2026-02-24

### Features
- feat: support GITLAB_PERSONAL_ACCESS_TOKEN and GITLAB_API_TOKEN env vars (#26) (4e7a80f)

### Other


## [0.6.1] - 2026-02-24

### Bug Fixes
- fix: disable FastMCP startup banner (#24) (e6f1d47)


## [0.6.0] - 2026-02-24

### Features
- feat(#22): add 5 MCP prompts for multi-tool workflows (#23) (1b136d0)


## [0.5.0] - 2026-02-24

### Features
- feat(server): MCP Builder compliance — immediate fixes (#20) (dc58850)

### Documentation
- docs: update AGENTS.md — add release workflow, fix stale info (9e6e4ea)

### Other


## [0.4.0] - 2026-02-23

### Other


## [0.3.1] - 2026-02-23

### Bug Fixes
- fix(ci): use temp files for blob creation to avoid ARG_MAX (#16) (5ffab9d)
- fix(ci): include uv.lock and CHANGELOG.md in release commits (#15) (0cb22e0)

