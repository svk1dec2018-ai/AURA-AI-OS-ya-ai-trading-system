# AURA local knowledge corpus

Put only material you are allowed to use here: your own notes/files, public-domain
books, explicitly open-licensed material, official open publications, or transcripts
you are authorized to process. AURA does not download books or video transcripts.

Copy `manifest.example.jsonl` to `manifest.jsonl`, add one JSON object per line, and
place each referenced `.md` or `.txt` file below this directory. Allowed `license`
values are:

- `public_domain`
- `cc_by_4_0`
- `cc_by_sa_4_0`
- `official_open`
- `user_provided`

Allowed `source_type` values include `book`, `video_transcript`, `research_paper`,
`regulator`, `exchange`, `macro`, `news`, and `internal`.

At runtime, files are path-confined, size-limited, chunked, hashed, trust-gated and
retrieved only when relevant and point-in-time eligible. Unlisted or invalid files
never enter an agent prompt.
