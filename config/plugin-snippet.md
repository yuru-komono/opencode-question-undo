# Plugin registration snippet

Add this repository's directory to the `plugins` array of your global config `~/.config/opencode/opencode.json` (or `.jsonc`):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  // ... keep your existing settings ...
  "plugins": ["C:/path/to/question-undo-public"]
}
```

- A local plugin must be a directory (a path to a single file is ignored)
- If a `plugins` array already exists, append `"C:/path/to/question-undo-public"` (the array is applied in order, not merged)
- No build step is required (only `npm install`; the server-side part reads the ESM sources directly)
- Apply: restart the server (`opencode service restart`) or save the config file (the config watcher reloads)
- Verify: `opencode api get /api/command` lists `undo-answer`, `undo-answer-apply` and `undo-answer-cancel`; `/undo-answer` autocompletes in the input box on all three surfaces (Desktop, Web UI, TUI)
- Disable: add `"-question-undo"` to `"plugins"` (the id follows the Extensions > Plugins display; if it differs, prefix that id with `-`. The Extensions toggle switches OFF only in the Desktop UI)
