# Use of generative AI in this project

Journals, Zenodo and most conferences ask authors to disclose AI assistance. This file records
what was done, so disclosures stay accurate. **AI tools are not authors** (see AUTHORS.md).

## Tool
Claude (model Claude Opus 5.5, Anthropic), used through Claude Code in VS Code, from
5-6 October 2026.

## What the AI did
- **Background research:** the challenge rules, SPHEREx data-access documentation (IRSA, the AWS
  Open Data registry), and data-provider acknowledgement policies.
- **Concept:** proposed several project ideas, including SkyShift (the time-zoom viewer plus the
  "Hunt Planet X" game). The human team chose SkyShift.
- **Experiments (`experiments/`):** designed and wrote all scripts, ran them, and recorded the
  measured results in `experiments/FINDINGS.md`.
- **Application (`backend/`, `web/`, `scripts/`):** designed and wrote the code, and ran automated
  API and browser (Playwright/Edge) tests.
- **Documentation:** wrote the READMEs, guides and this file.

## What the human team did
- Chose the challenge, the concept, the scope and every major decision (learning sandbox first,
  then building the full app, licence, repository visibility, publication goals).
- Directed the work and reviewed results during the sessions.

## Must happen before any publication (do not skip)
- [ ] At least one human author re-runs the key experiments (`01`, `04` for Hygiea and Pluto,
      `07`) and confirms the numbers in FINDINGS.md.
- [ ] Human authors read and understand the code they will describe in a paper, especially
      `backend/spherex.py` and `backend/sequences.py`.
- [ ] Every literature reference is checked against ADS (AI-recalled references can be wrong).
- [ ] The disclosure below is adapted to the journal's own policy and placed where it asks
      (methods, acknowledgements, or cover letter).

## Template disclosure for a manuscript
> The software described here was developed with substantial assistance from a generative AI
> coding assistant (Claude Opus 5.5, Anthropic), which drafted code, analysis scripts and
> documentation under the authors' direction. The authors reviewed the code, independently re-ran
> the analyses reported in this paper, and take full responsibility for the content.

Only use this wording once the "reviewed" and "re-ran" claims are true.
