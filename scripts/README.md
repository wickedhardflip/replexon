# Backup Scripts

Template backup scripts for Plex Media Server, designed for rsync to a NAS/Synology.

## Scripts

| Script | Schedule | Purpose |
|---|---|---|
| `backup-plex.sh` | Daily 3 AM | Mirror Plex data to NAS + Sunday snapshots |
| `cleanup-plex-snapshots.sh` | Sunday 4 AM | Remove old weekly snapshots beyond retention count |
| `backup-scripts.sh` | 1st of month 5 AM | Back up all scripts and configs to NAS |

## Setup

### 1. Create rsync credential file

```bash
sudo mkdir -p /etc/replexon
sudo cp rsync.secret.example /etc/replexon/rsync.secret
sudo nano /etc/replexon/rsync.secret   # Replace with your actual rsync password
sudo chmod 600 /etc/replexon/rsync.secret
```

### 2. Edit script variables

Open each script and configure the variables at the top:

- **`PLEX_DATA`** -- Path to your Plex data directory
- **`NAS_IP`** -- Your NAS/Synology IP address
- **`RSYNC_USER`** / **`RSYNC_MODULE`** -- rsync daemon credentials on your NAS
- **`RSYNC_PASSWORD_FILE`** -- Path to the credential file (default: `/etc/replexon/rsync.secret`)

### 3. Install scripts

```bash
sudo cp backup-plex.sh /usr/local/bin/
sudo cp cleanup-plex-snapshots.sh /usr/local/bin/
sudo cp backup-scripts.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/backup-plex.sh
sudo chmod +x /usr/local/bin/cleanup-plex-snapshots.sh
sudo chmod +x /usr/local/bin/backup-scripts.sh
```

### 4. SSH key setup (for cleanup script)

The cleanup script uses SSH to list and delete snapshots on the NAS. Set up key-based auth:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/nas_backup -N ""
ssh-copy-id -i ~/.ssh/nas_backup admin@YOUR_NAS_IP
```

Then add to `~/.ssh/config`:

```
Host nas
    HostName YOUR_NAS_IP
    User admin
    IdentityFile ~/.ssh/nas_backup
```

### 5. Crontab entries

```bash
sudo crontab -e
```

Add:

```cron
# RePlexOn backup schedule
0 3 * * *   /usr/local/bin/backup-plex.sh >> /var/log/plex-backup.log 2>&1
0 4 * * 0   /usr/local/bin/cleanup-plex-snapshots.sh >> /var/log/plex-backup.log 2>&1
0 5 1 * *   /usr/local/bin/backup-scripts.sh >> /var/log/plex-backup.log 2>&1
```

## NAS/Synology rsync Daemon Setup

On your Synology NAS, enable the rsync service:

1. **Control Panel > File Services > rsync** -- Enable rsync service
2. Create an rsync module in `/etc/rsyncd.conf` (or via Synology UI)
3. Set read/write permissions for your backup user

Example `/etc/rsyncd.conf` module:

```ini
[plex-backups]
    path = /volume1/plex-backups
    auth users = backupuser
    secrets file = /etc/rsyncd.secrets
    read only = false
```

## Log Format

These scripts produce log markers that RePlexOn's `log_parser.py` expects. **Do not modify the marker format:**

```
=== Plex Backup Started: Mon Feb 23 03:00:01 AM EST 2026 ===
=== Plex Backup Completed Successfully: Mon Feb 23 03:13:23 AM EST 2026 ===
=== Plex Backup FAILED with code 1: Mon Feb 23 03:00:01 AM EST 2026 ===
=== Plex Snapshot Cleanup - Sun Feb 23 04:00:01 AM EST 2026 ====
```
