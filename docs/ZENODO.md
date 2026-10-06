# Connecting SkyShift to Zenodo (step by step)

Zenodo archives each GitHub **release** and gives it a DOI, a permanent identifier that papers can
cite. The repository is already prepared; this page covers the steps that need your own accounts.

**Before you start, know three things:**
1. **Zenodo only sees public repositories** and only archives releases published *after* you
   switch the repository on. Order matters: public, then switch on, then release.
2. **Metadata comes from `.zenodo.json`,** which `scripts/release_check.py --write` generates from
   `CITATION.cff`. Edit `CITATION.cff`, never `.zenodo.json` by hand.
3. **A DOI is permanent.** You can fix metadata later and publish new versions, but a published
   record cannot be deleted. Get the author list right first.

## Step 0: one-time accounts (about 10 minutes)
- [ ] **ORCID** for each author: https://orcid.org/register. Put the IDs in `CITATION.cff` as
      `orcid: "https://orcid.org/0000-0000-0000-0000"`.
- [ ] **Zenodo**: go to https://zenodo.org and choose *Log in*, then *Log in with GitHub*
      (account Mahadi5577). In Zenodo's profile settings, also link ORCID.
- [ ] Optional rehearsal: https://sandbox.zenodo.org is a full copy of Zenodo whose DOIs are fake.
      Running steps 3-4 there first is a safe way to see what the record will look like.

## Step 1: finish the metadata
- [ ] The team signs `AUTHORS.md`.
- [ ] In `CITATION.cff`, replace every `TODO` with real names, affiliations and ORCIDs, and set
      `version: 0.1.0` and `date-released:` to the release day.
- [ ] Generate Zenodo's metadata, then commit and push:
      ```
      pip install -r requirements-dev.txt
      python scripts/release_check.py 0.1.0 --write
      git add .zenodo.json CITATION.cff AUTHORS.md
      git commit -m "Release metadata for 0.1.0"
      git push
      ```

## Step 2: make the repository public
```
gh repo edit Mahadi5577/skyshift --visibility public --accept-visibility-change-consequences
```
(or on GitHub: Settings, then General, then Danger Zone, then Change visibility)

## Step 3: switch the repository on in Zenodo
1. Open https://zenodo.org/account/settings/github/
2. Click **Sync now** if `skyshift` isn't listed.
3. Flip the switch next to **Mahadi5577/skyshift** to **On**.

## Step 4: check, then release
```
python scripts/release_check.py 0.1.0
```
It must end with **Ready**. Then run the command it prints:
```
gh release create v0.1.0 --title "SkyShift 0.1.0" --notes-file cache/release-notes-0.1.0.md
```
Within a few minutes the repository appears at https://zenodo.org/account/settings/github/
with a DOI. If it shows an error instead, open the repository there to read the message. Usually
it is a metadata problem: fix it, then publish a new release such as `v0.1.1`.

## Step 5: after the DOI exists
Zenodo gives two DOIs:
- the **concept DOI**, which always points to the newest version (use it in the README badge and
  in `CITATION.cff`), and
- a **version DOI** for exactly this release (use it in a paper's methods section).

- [ ] Add the concept DOI to `CITATION.cff` as `doi: 10.5281/zenodo.NNNNNNN`.
- [ ] Add the badge Zenodo shows (the record page has a "DOI badge" button) to the top of
      `README.md`.
- [ ] Commit and push. A new release is not needed for this.
- [ ] Optional: add the record to a Zenodo community (record page, then "Communities").

## Later versions
Update `version` and `date-released` in `CITATION.cff`, add a section to `CHANGELOG.md`, run
`release_check.py X.Y.Z --write`, commit, push, then `gh release create vX.Y.Z ...`.
Zenodo adds a new version under the same concept DOI.
