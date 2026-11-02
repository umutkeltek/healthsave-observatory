# Observatory Care

Observatory Care is a licence for people who run HealthSave Observatory on their own hardware and want it looked after: encrypted off-site backups on a schedule, restore drills that prove a backup works, and a one-command rollback when an update goes wrong.

Everything else in Observatory is free and stays free, and nothing you can do today goes behind the licence. The licence is a small signed file that Observatory checks on your machine. It never phones home.

## What is free and what Care adds

| | Free | Care |
|---|---|---|
| Capture, Observatory web, findings and Body Briefs, the v2 API, Grafana, Home Assistant | yes | yes |
| `healthsave backup`: a plain `.tar` of the database, `.env` and `config.yaml` | yes | yes |
| `healthsave restore FILE`, including encrypted backups | yes | yes |
| `healthsave update`, with a backup taken first | yes | yes |
| `healthsave backup --encrypt`: an encrypted backup file | | yes |
| `healthsave backup --offsite REMOTE`: an encrypted copy to your own storage, through rclone | | yes |
| `healthsave backup --schedule daily\|weekly`: encrypted backups on a timer | | yes |
| `healthsave restore --drill FILE`: test-restore a backup into a throwaway database | | yes |
| `healthsave update --rollback`: go back to the release before the last update | | yes |

When a licence ends, Care commands keep working for 14 more days, then stop. Your encrypted backups still restore without a licence, and `healthsave backup --schedule off` still removes a scheduled job.

## Activate a licence

After a purchase you get a 24-character licence code. On the machine that runs Observatory:

```bash
healthsave license activate <code>
healthsave license status
```

`activate <code>` downloads the licence file for that code, checks it, and installs it as `healthsave.license` next to `config.yaml`, readable only by you. If you already have the file (for example, downloaded on another device), install it without any network use:

```bash
healthsave license activate healthsave-license.txt
```

`healthsave license status` shows the tier, the expiry date and the features. Without a licence it says you are on Observatory Community, the free edition. Set `HEALTHSAVE_LICENSE_FILE` to keep the file somewhere else.

To renew, activate the new file or fetch the same code again.

## How the licence is checked (no phone-home)

A licence file has two parts: the licence details and an Ed25519 signature over them. The details are the tier, a customer id, a SHA-256 hash of the purchase email (not the email itself), the seat count, the feature names, the issue and expiry times, and a random value.

Observatory checks the signature against a public key built into its code, on your machine. Nothing is sent anywhere to check a licence: no licence server, no telemetry, no usage counting. A licensed Observatory works the same offline or air-gapped.

`healthsave license activate <code>` (also available as `healthsave license fetch <code>`) is the only licence command that uses the network, and only when you run it. It makes one HTTPS request that sends the code and nothing else. Your health data is never part of it.

## Encrypted, off-site and scheduled backups

Encrypted backups use a passphrase you choose. Add it to `.env`, and keep a copy in your password manager: without it, an encrypted backup cannot be opened.

```bash
echo "BACKUP_PASSPHRASE=$(openssl rand -base64 32)" >> .env
```

Then:

```bash
healthsave backup --encrypt                              # backups/healthsave-backup-<time>.tar.enc
healthsave backup --offsite b2:my-bucket/healthsave      # encrypt, then copy with rclone
healthsave backup --schedule daily --offsite b2:my-bucket/healthsave          # print the job
healthsave backup --schedule daily --offsite b2:my-bucket/healthsave --yes    # install it
healthsave backup --schedule off                         # remove it
```

- **Encryption.** AES-256 through `openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -md sha256`, readable by OpenSSL and by LibreSSL on macOS. The unencrypted file only exists briefly in a private temporary folder. The backup records a SHA-256 checksum of the database dump, and a restore refuses a dump that does not match it.
- **Off-site.** `--offsite` copies the encrypted file with [rclone](https://rclone.org/install/) to any remote you set up with `rclone config`: S3, Backblaze B2, a NAS over SFTP, and many more. The storage and its account are yours. Off-site copies are always encrypted first, and the local file is kept.
- **Schedule.** `--schedule` runs `healthsave backup --encrypt` (with the same `--out` and `--offsite`) at 03:15 every day, or every Sunday. On macOS it is a launchd agent (`~/Library/LaunchAgents/com.healthsave.observatory.backup.plist`), which runs while you are logged in and Docker is running. Elsewhere it is a crontab line. Set `HEALTHSAVE_SCHEDULER=cron` or `launchd` to choose. Output goes to `backups/scheduled-backup.log`.

Restore an encrypted backup like any other: `healthsave restore backups/healthsave-backup-<time>.tar.enc`. On a new machine whose `.env` does not have the passphrase yet, pass it for that one command: `BACKUP_PASSPHRASE='...' healthsave restore FILE`. You can also decrypt by hand:

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -md sha256 \
  -in healthsave-backup-<time>.tar.enc -out healthsave-backup-<time>.tar
```

## Restore drills

A backup you have never restored is a hope. A drill turns it into a fact without touching your Observatory:

```bash
healthsave restore --drill backups/healthsave-backup-<time>.tar.enc
```

The drill starts a throwaway TimescaleDB container with no network, restores the backup into it the same way a real restore does, and compares the row count of every table with the counts recorded when the backup was made:

```text
  TABLE                                                 IN BACKUP     RESTORED
  public.heart_rate                                         50000        50000  ok
  public.hrv                                                  600          600  ok
  public.schema_migrations                                     27           27  ok

RESULT: PASS - 43 tables and 50627 rows restored in 1s, matching the backup; 27 migrations.
```

It prints `RESULT: FAIL` and exits with status 1 if any table is missing or has a different count, or if the migration count differs. The container and its data are deleted when the drill ends, including after Ctrl-C. Your running database is never read or changed.

The drill uses `TIMESCALE_IMAGE` from `.env`, or the image `docker-compose.yml` uses; pass `--image` to choose another. Backups made before this feature existed have no row counts, so a drill on them fails with that reason. Make a new backup and drill that one.

## Update rollback

Every `healthsave update` records the release it came from, which services were running and where its pre-update backup is. If the new release misbehaves:

```bash
healthsave update --rollback
```

This checks out the previous release and restarts the same services. It leaves the database as it is: migrations only add tables and columns, so the previous release reads the data written since. If the data itself needs to go back too, the rollback prints the pre-update backup to restore.

A rollback undoes one update, once. If the checkout has moved since that update, it refuses and tells you how to go back by hand.

## Troubleshooting

- **"Checking a licence needs Docker ... or Python 3.11+ with the cryptography package."** The CLI checks licences with the host's Python when it can, otherwise inside the Observatory API image. Start Docker, or install a recent Python with `cryptography`.
- **"Encrypted backups need a passphrase"**: add `BACKUP_PASSPHRASE` to `.env` as shown above.
- **"Off-site copies use rclone, which is not installed"**: install rclone and run `rclone config` to add a remote, then try again. The backup is not taken until rclone is available.
- **A scheduled backup did not run**: check `backups/scheduled-backup.log`. A licence that ended more than 14 days ago stops scheduled backups; the log says so.

## See also

- [Backups & migrations](backup-and-migrations.md) for the free backup and restore.
- [Security model](security.md) for where secrets live.
