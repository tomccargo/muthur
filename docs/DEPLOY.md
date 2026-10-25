# Deploying muthur on a Synology NAS

For DSM 7.2.1 or later with Container Manager (it brings `docker compose`; [release notes](https://www.synology.com/en-uk/releaseNote/ContainerManager)). Commands that start with `sudo` run on the NAS over SSH; the rest run on your own computer.

## 1. Two users, two jobs

| User | Group | What it's for |
|---|---|---|
| `muthur-deploy` | administrators | Signs in over SSH with a key to install and update the container. Docker on DSM needs root, so this user is powerful: no password login, key only. |
| `muthur` | users | The account the **container runs as**. Not an administrator, so even a bug in muthur can only touch what this user may touch. |

In DSM: **Control Panel → User & Group → Create**.

- `muthur-deploy`: a long random password (it's never typed after this), member of **administrators**.
- `muthur`: a long random password, member of **users** only. Permissions:
  - the media shared folder (the one holding `torrent-output`, `TV`, `Film`): **Read/Write**. muthur 0.2 mounts it read-only anyway; write access is for later versions.
  - the `docker` shared folder: **Read/Write**.
  - Applications: deny everything (it never signs in).

Also make sure **Control Panel → User & Group → Advanced → Enable user home service** is on: SSH keys live in the user's home folder.

## 2. Key-only SSH for `muthur-deploy`

1. **Control Panel → Terminal & SNMP → Enable SSH service**.
2. On your computer, make a key (once):
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/muthur_nostromo -C "muthur-deploy"
   ```
3. Sign in once with the password and install the key. DSM creates home folders with permissions that sshd refuses for key logins, so those are fixed too ([Synology KB](https://kb.synology.com/en-uk/DSM/tutorial/How_to_log_in_to_DSM_with_key_pairs_as_admin_or_root_permission_via_SSH_on_computers), [forum](https://www.synology-forum.de/threads/ssh-login-fuer-non-root-user-mit-key.81695)):
   ```bash
   ssh muthur-deploy@NAS "mkdir -p ~/.ssh && chmod 755 ~ && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" < ~/.ssh/muthur_nostromo.pub
   ```
4. Check that the key works without a password:
   ```bash
   ssh -i ~/.ssh/muthur_nostromo -o PasswordAuthentication=no muthur-deploy@NAS "id"
   ```

## 3. Find the IDs for `compose.yaml`

```bash
ssh muthur-deploy@NAS "id muthur"
```

It prints something like `uid=1027(muthur) gid=100(users)`. Those numbers are `PUID` and `PGID`.

## 4. Install

Send the committed files only (no `node_modules`, no `.env`, no local reports):

```bash
ssh muthur-deploy@NAS "mkdir -p /volume1/docker/muthur/config /volume1/docker/muthur/app"
git archive HEAD | ssh muthur-deploy@NAS "tar -x -C /volume1/docker/muthur/app"
```

Make `/volume1/docker/muthur/app/.env` from `.env.example`:

```bash
PUID=1027
PGID=100
MEDIA_SHARE=/volume1/YourMediaShare
CONFIG_DIR=/volume1/docker/muthur/config
TMDB_READ_TOKEN=          # or enter it later in muthur's Settings
```

Give `muthur` its config folder, then build and start:

```bash
ssh muthur-deploy@NAS "sudo chown -R muthur:users /volume1/docker/muthur/config"
ssh muthur-deploy@NAS "cd /volume1/docker/muthur/app && sudo docker compose up -d --build"
```

The first build takes several minutes on a small NAS. Then open `http://NAS:8580`.

## 5. Update

```bash
git archive HEAD | ssh muthur-deploy@NAS "tar -x -C /volume1/docker/muthur/app"
ssh muthur-deploy@NAS "cd /volume1/docker/muthur/app && sudo docker compose up -d --build"
```

## 6. Check the guardrails

```bash
ssh muthur-deploy@NAS "sudo docker stats muthur --no-stream"
```

Memory should be well under the 256 MB limit (about 50 MB idle). If DSM warns that the kernel doesn't support swap limits, that's expected: the memory limit still applies.

## 7. Turn SSH off again (optional)

When nothing needs deploying, **Control Panel → Terminal & SNMP → Enable SSH service** can be switched off. Container Manager keeps muthur running.
