# Preferred sign-in experience: Codex, Claude and Agy

The owner approved the successful six-profile Agy dialog and explicitly extended
that preference to **all three providers** on 13 October 2026.

- Check status first and reuse valid sessions. Handle isolated profiles sequentially.
- Show the provider's fresh URL as selectable text with a **Copy URL** button.
  The owner opens it manually; never rely on automatic browser opening.
- When a provider returns an authorization code, use an ordinary masked Windows
  text field supporting Ctrl+V, with Submit/Enter and Cancel/Escape.
- Codex device authorization has the opposite code direction: show its device
  code for entry in the browser. Do not ask for an invented callback code.
- Verify authentication after the interaction, then verify worker cleanup.
  No credential copying, raw console key handling or native TUI navigation.
- Keep sign-in separate from deployment and finish any necessary owner input at
  the beginning. Never prompt after declaring the unattended portion started.

The Agy adapter has actual six-profile Windows acceptance; the user's preference
does not itself establish equivalent host acceptance of a new Codex or Claude
dialog adapter. Existing verified Codex/Claude sessions are reused for R6.

See [the Agy implementation and host evidence](AGY_SIGNIN_2026-10-13.md).
