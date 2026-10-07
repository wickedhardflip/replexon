# Plex in Docker

Most people run Plex as a container (`linuxserver/plex` or `plexinc/pms-docker`).
RePlexOn runs next to it and reads the same config folder.

## Find your Plex config folder

It is the host folder your Plex container mounts at `/config`:

```bash
docker inspect plex --format '{{ range .Mounts }}{{ .Source }} -> {{ .Destination }}{{ "\n" }}{{ end }}'
```

Mount that host folder into RePlexOn at `/plex`, read-only. RePlexOn finds the
`Library/Application Support/Plex Media Server` folder inside it, so you do not need
the full path.

## Same user and group

The Plex config folder is owned by the user Plex runs as. Give RePlexOn the same IDs
so it can read it:

- linuxserver/plex: use the container's `PUID` / `PGID`.
- plexinc/pms-docker: use its `PLEX_UID` / `PLEX_GID`.
- Not sure: `stat -c '%u:%g' /path/to/plex/config`.

## One compose file for both

```yaml
services:
  plex:
    image: lscr.io/linuxserver/plex:latest
    container_name: plex
    network_mode: host
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=America/New_York
    volumes:
      - /srv/plex/config:/config
      - /srv/media:/media
    restart: unless-stopped

  replexon:
    image: ghcr.io/wickedhardflip/replexon:latest
    container_name: replexon
    environment:
      - PUID=1000                 # same as Plex
      - PGID=1000
      - TZ=America/New_York       # same as Plex
    volumes:
      - replexon-data:/data
      - /srv/plex/config:/plex:ro # Plex's /config, read-only
      - /srv/backups/plex:/backups
      # - /var/run/docker.sock:/var/run/docker.sock   # only for "Pause Plex during the copy"
    ports:
      - "9847:9847"
    restart: unless-stopped

volumes:
  replexon-data:
```

RePlexOn only needs the files, not a network path to Plex, so it does not matter
whether Plex uses host networking. If you put both on a shared user-defined network
for a reverse proxy, that works too.

## Pausing Plex during the database copy

The default **Safe copy** mode is fine for nearly everyone and needs nothing extra.
If you want Plex fully still while its databases are copied, mount
`/var/run/docker.sock`, choose **Pause Plex during the copy** under Settings, and set
the Plex container name (`plex` above). Streams freeze for a few seconds. Mounting
the Docker socket gives RePlexOn control over Docker on that host; see
[configuration.md](configuration.md#database-safety).

## Health

The image has a `HEALTHCHECK` on `/health`, so `docker ps` shows `healthy` once the
app is up. Use `http://replexon:9847/health` for uptime monitors.

## Restoring

Stop Plex, copy `plex-current/` (or a dated snapshot) back over the Plex config
folder's `Library/Application Support/Plex Media Server`, fix ownership to the Plex
PUID/PGID, and start Plex. Full steps: [restore.md](restore.md) and the Restore page in
the app.
