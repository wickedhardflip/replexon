# Backing up to a NAS

Two ways, pick one:

| | rsync daemon | Mounted share |
|---|---|---|
| Set up on the NAS | Enable rsync, create a module and user | An SMB or NFS share |
| Set up in RePlexOn | Destination "A NAS over rsync" | Mount the share at `/backups`, destination "A folder" |
| Snapshots | Made and pruned on the NAS over rsync | Made and pruned in the folder |

The rsync daemon is usually faster and needs no mounts. A mounted share is easier if
you already have one.

## Option A: rsync daemon

### On the NAS

**Synology DSM**

1. Control Panel > File Services > rsync: enable the rsync service (port 873).
2. Create a shared folder, e.g. `plex-backups`.
3. Give an rsync user read/write access to it. On DSM the shared folder name is the
   rsync module name.

**Any Linux box** (`/etc/rsyncd.conf`):

```ini
[plex-backups]
    path = /srv/plex-backups
    uid = backup
    gid = backup
    read only = no
    auth users = backupuser
    secrets file = /etc/rsyncd.secrets
```

`/etc/rsyncd.secrets` (chmod 600) has one line, `backupuser:***`. Then
`sudo systemctl enable --now rsync`.

### In RePlexOn

Use the normal `compose.yml` (the `/backups` mount can go). In Settings > Where
backups go, pick **A NAS over rsync** and fill in the address, user, module and
password. The password is stored encrypted.

Bare-metal installs can use a password file instead: leave the password blank and put
it in `/etc/replexon/rsync.secret` (chmod 600, password only).

## Option B: mounted share

Mount the share on the Docker host, or let Docker mount it as a volume; see
[`compose.nas.yml`](../compose.nas.yml) for SMB/CIFS and NFS examples. Then pick
**A folder** with `/backups`.

The share must be writable by RePlexOn's `PUID`/`PGID` (for CIFS, set `uid=` and `gid=`
in the mount options).

## What ends up on the NAS

```
plex-backups/
  plex-current/          # latest backup, mirrored each run
  plex-snapshots/
    2026-08-10/          # dated copy made after each successful Sunday backup
    2026-08-17/
```

The cleanup job keeps the newest N snapshots (Settings > Weekly snapshots) and removes
older ones, on the NAS too. No SSH access is needed.

## Troubleshooting

Check the latest run under Logs, or `docker logs replexon`.

- **connection refused / timed out**: the NAS is not reachable or rsync is off.
  From the host, `rsync rsync://192.168.1.50/` should list the modules.
- **auth failed on module**: wrong user or password, or the user has no access to that
  module.
- **permission denied**: the rsync user (or `uid` in rsyncd.conf) cannot write to the
  folder.
