# One engine, many packs

There is one copy of the editor: this repository. Everything else is a pack.

| | Engine (this repo) | Pack repo (private) |
| --- | --- | --- |
| Holds | Cutting, rendering, the first-pass gate, delivery, power tools, generic skills, style library, generic presets | Client presets, brand packs, owner rules, private skills (council, posting, covers), client templates |
| Changes when | A tool gets better or a bug is fixed | A client, a look, or a rule changes |
| Who gets it | Anyone | Paying customers, or just you |

A fix made in a pack's copy of a tool is lost: the next thread starts from the engine and
rebuilds it. That is how the same renderer came to exist in two repositories with different bugs fixed in each.

## Setting up a pack repo

1. Add an `engine.json` at the pack's root:

   ```json
   {
     "source": "https://github.com/<owner>/<engine repo>",
     "keep": ["README.md", "CLAUDE.md", "AGENTS.md", "package.json", "package-lock.json"]
   }
   ```

   `keep` lists files the pack owns even though the engine has one with the same name. An entry
   ending in `/` covers a folder. Files the engine does not ship need no entry.

2. Pull the engine in from a checkout of it:

   ```
   npm run engine:sync -- ../free-editor
   npm run sync:skills
   npm test
   ```

   This copies every engine file, and writes `engine.lock.json` with the engine commit and a
   checksum per file. Commit the result.

3. Run `npm run engine:check` in the pack's tests. It works offline and fails
   when an engine file was edited in the pack.

## Rules

- **Fix tools in the engine.** Open the pull request here, merge it, then sync the pack.
- **Put looks in presets.** A client's fonts, colours, pacing and banned things are a JSON file
  in `presets/`, not an edit to a renderer.
- **A pack skill wraps, it does not copy.** If a private skill needs an engine script with a
  different default, import the engine script and change the default (see
  `DEFAULT_LOOK` in `talking_head.py`), in a file of a few lines.
- **Sync on a fixed beat.** After each engine merge, or before a batch. The lock file says
  which engine a batch was made with, so a render can be reproduced.
- **Nothing private goes upstream.** Client names, footage, presets with a client's name and
  owner rules stay in the pack.

## Selling it

The engine is the free product. A pack is the paid product: the same `engine.json`, plus the
presets, brand packs, rules and skills that took the revisions to get right. A buyer clones
the pack, runs `npm run setup`, and has both.
