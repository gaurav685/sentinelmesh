# Downloading CADETS E3 via your own Google Drive copy

Real blocker this works around: Google Drive's **public anonymous-link quota** on the
Five Directions folder (`https://drive.google.com/drive/folders/179uDuz62Aw61Ehft6MoJCpPeBEz16VFy`,
linked from `darpa-i2o/Transparent-Computing`'s `README-E3.md`) is exhausted — confirmed
directly via `gdown` on two different files, both real "too many users have viewed or
downloaded this file recently" errors, independent of file size. Copying the files into
your own Drive gives *your* account a fresh, separate download quota for the copy.

Only the real files this plan needs (see `docs/PHASE2_PLAN.md`'s numbered list) —
**don't copy the whole folder**, it's larger than necessary:

1. CDM schema `.avsc` — Drive ID `1oGMbSIZ73lh0xs8PUg--3Bj_wtC1q85-`
2. CDM schema `.avdl` — Drive ID `1zVKApkZwuPsk3y8BnR1bWTqze929y1qp`
3. `ta1-cadets-e3-official-2.json.tar.gz` (341.6 MB) — pilot file
4. `ta1-cadets-e3-official.json.tar.gz` (558.6 MB) — full run only
5. `ta1-cadets-e3-official-1.json.tar.gz` (905.9 MB) — full run only

(The three `.bin.tar.gz` files are real DARPA data too, but PIDSMaker's own working
parser never reads them for CADETS_E3 — skip them unless something downstream turns
out to need them, which would be a real, documented surprise, not assumed now.)

## (a) "Make a copy" — the simple path, try this first

1. Open each file's direct link: `https://drive.google.com/open?id=<FILE_ID>` (substitute
   the IDs above).
2. Right-click the file in the preview → **"Make a copy"** (or the ⋮ menu → "Make a
   copy"). This creates a copy in **your own** "My Drive", owned by you, with a **new
   file ID** — Google shows it immediately, or find it later via Drive's own "Details"
   panel (⌘/Ctrl+I) on the copy.
3. Make sure the copy's sharing is set so a link can read it (Share → "Anyone with the
   link" → Viewer) — same requirement the original had, since `gdown` needs an
   anonymous-readable link.
4. Send me the 3–5 new file IDs (one per file you copied) and which real filename each
   one is (Google doesn't rename on copy, so the name should already match).

If "Make a copy" itself returns the same quota error (it can, since the copy operation
still has to *read* the original file first), skip to (c) below.

## (b) Download template, once you have your own copy's file IDs

Same `gdown` invocation as before, just pointed at your new IDs — your copy has its own
independent quota, so this should work immediately even though the original is still
blocked:

```bash
# one file
python -m gdown --no-cookies <YOUR_COPY_FILE_ID> -O data/raw/cadets_e3/<real_filename>

# or, if gdown's own quota-detection ever misfires on your copy (unlikely, fresh quota):
# curl -L -o data/raw/cadets_e3/<real_filename> \
#   "https://drive.google.com/uc?export=download&id=<YOUR_COPY_FILE_ID>"
```

`rclone` works too if you already have it configured against your own Google account
(skip if you don't — `gdown` needs no auth for a public-link copy, which is the point):

```bash
rclone copy "gdrive:<path to your copied file>" data/raw/cadets_e3/ --drive-shared-with-me
```

Tell me the real filenames once downloaded — I'll compute and record sha256s exactly
like Phase 1's `data/README.md` convention, never trusting the filename alone.

## (c) Fallback: a Colab cell, server-side copy (if "Make a copy" is itself blocked)

Google Drive's own server-to-server copy (via the Drive API, inside Colab, where you're
already authenticated as yourself) sometimes succeeds even when "Make a copy" in the
UI hits the same read-quota wall, because the API copy path doesn't necessarily re-read
the full file content through the quota-limited public-serving path. Worth trying if
(a) fails:

```python
# Run in a Google Colab notebook (colab.research.google.com), your own account.
from googleapiclient.discovery import build
from google.colab import auth
auth.authenticate_user()  # interactive Google sign-in, your account -- not something
                           # to automate or hand your credentials to anyone else for

drive = build("drive", "v3")

SOURCE_FILE_IDS = {
    "cadets_e3_schema.avsc": "1oGMbSIZ73lh0xs8PUg--3Bj_wtC1q85-",
    "cadets_e3_schema.avdl": "1zVKApkZwuPsk3y8BnR1bWTqze929y1qp",
    "ta1-cadets-e3-official-2.json.tar.gz": None,  # fill in once you know which of the
    "ta1-cadets-e3-official.json.tar.gz": None,    # 6 main IDs in download_cadets_e3.sh
    "ta1-cadets-e3-official-1.json.tar.gz": None,  # maps to which real filename
}

new_ids = {}
for name, file_id in SOURCE_FILE_IDS.items():
    if file_id is None:
        continue
    copy = drive.files().copy(
        fileId=file_id,
        body={"name": name},  # lands in your Drive root; move it in the UI after if you want
    ).execute()
    new_ids[name] = copy["id"]
    print(f"{name}: new file id = {copy['id']}")

print(new_ids)
```

If this *also* fails with a quota/permission error, the files are genuinely
unreadable right now from any account, not just anonymously — at that point waiting
for Google's own quota window (their error message says up to 24h) is the only real
option left, not something either copy method can work around.

## Mapping Drive IDs to real filenames

PIDSMaker's `dataset_preprocessing/darpa_tc/scripts/download_cadets_e3.sh` lists 6 bare
file IDs for the main CADETS_E3 archives with no names attached — Google only reveals a
file's real name via the `Content-Disposition` header on a successful fetch, which none
of our attempts have reached yet. If you open each `drive.google.com/open?id=...` link
in a browser, the real filename shows directly in the preview header — please note which
ID is which of the 6 names (`ta1-cadets-e3-official[-1|-2].{bin,json}.tar.gz`) so this
file and `docs/PHASE2_PLAN.md` can be corrected from "ID → name unconfirmed" to real,
checked pairings.
