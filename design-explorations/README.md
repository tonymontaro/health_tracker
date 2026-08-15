# Health Autopilot design explorations

Field Notes is the selected static design direction for Health Autopilot.
It uses mock data, does not call the Health Autopilot API, and does not modify production data.

See [`DESIGN-NOTES.md`](DESIGN-NOTES.md) for the evaluation of the current interface and the selected direction.

Open [`index.html`](index.html) directly in a browser, or serve this directory locally:

```bash
cd design-explorations
python3 -m http.server 4173
```

Then visit `http://localhost:4173`.

## Selected design

**Field Notes** is an editorial daybook that makes the plan feel calm, considered, and personal.

## Field Notes production guidance

- [`Field Notes design system`](../docs/design/field-notes-design-system.md)
- [`Field Notes migration agent prompt`](../docs/design/field-notes-migration-agent-prompt.md)

The prototype includes desktop and mobile responsive layouts plus mock interactions such as switching sections, opening detail views, recording completion, and continuing the AI coach conversation.
