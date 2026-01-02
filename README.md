# macOS Voice Memos Exporter

Python project to export audio files from macOS Voice Memos app with right
filename and date created ![Screenshot](screenshot.png)

Since Apple has forgotten to implement a serious export function to the Voice
Memos app, this project will help you. You can export all or selected memos as
audio files. The names of the files correspond to the labels of the memos. The
recording date of the memos can be found in the creation date of the files and
can be also added to the file name.

## Requirements

- **Python 3.10+** (uses standard library only, no installation needed)
- **Full Disk Access** (optional) to read the Voice Memos database

Go to System Settings > Privacy & Security > Full Disk Access and add your
terminal application.

Alternatively, copy the entire `Recordings` folder to a temporary location and
run this tool with `--db-path` pointing to the database file inside the copy.
The audio files (`.m4a`) must remain alongside the database file since the
database references them by relative path.

The `pyproject.toml` is only for development tooling (type checking, linting)
and is not required to run the script.

## Parameters

### Database File Path

Use `-d` or `--db-path` to specify the path to the database Voice Memo App uses
to store information about the memos.

Default (macOS Sonoma 14+): `~/Library/Group
Containers/group.com.apple.VoiceMemos.shared/Recordings/CloudRecordings.db`

Default (macOS Ventura and earlier): `~/Library/Application
Support/com.apple.voicememos/Recordings/CloudRecordings.db`

If you don't use iCloud Sync for Voice Memos, this path could be also
interesting for you: `~/Library/Application
Support/com.apple.voicememos/Recordings/Recordings.db` (not verified)

### Export Folder Path

Use `-e` or `--export-path` to change the export folder path.

Default: `~/Voice Memos Export`

### Export All Memos

Add the flag `-a` or `--all` to export all memos at once instead of deciding
for each memo whether it should be exported or not.

### Add Date to File Name

Add the flag `--date-in-name` to add the recording date at the beginning of the
file name.

### Date Format for File Name

If you use the flag `--date-in-name` you can modify the date format with
`--date-in-name-format`.

Default: `%Y-%m-%d-%H-%M-%S_` ➔ `2019-12-06-22-31-11_`

### Prevent to Open Finder

Use the flag `--no-finder` to avoid opening a finder window to view exported
memos.

### Example

```python
python main.py -e ~/Music/memos -a --date-in-name --date-in-name-format "%Y-%m-%d "
```

## Disclaimer

No liability for damage to the memo database, library folder, or anywhere else
in the file system. Create a backup (in particular of `~/Library`) before using
this tool.
