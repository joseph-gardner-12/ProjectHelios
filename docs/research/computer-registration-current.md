# Current computer registration and connection process

Verified against repository source on October 5, 2026. This describes the checked-out code, not a verified production deployment. No credentials were created and no services were changed during this research. See [enrollment alternatives](computer-enrollment-options.md) for proposed improvements.

## What registration currently means

The backend stores a `Device` and any number of `DeviceCredential` rows for it. A credential is an ID plus a random secret; only the secret's password hash is stored in the database. There is no named computer inventory, enrollment endpoint, or browser pairing flow. Django admin can revoke credentials but cannot add them. `pnpm pi:setup` saves local settings; it does not contact the backend or prove that authentication works.

For interchangeable computers serving the same Helios installation, reuse one logical device UUID and issue a separate credential to each computer. Creating a separate device for every computer would create separate connection slots; the demo browser login also uses only `CONTROL_DEMO_DEVICE_ID`.

Sources: [models](../../apps/backend/control/models.py), [credential issuance and connection handling](../../apps/backend/control/services.py), [admin](../../apps/backend/control/admin.py), [demo sign-in](../../apps/backend/control/views.py), [CLI setup](../../apps/localization/src/helios_localization/__main__.py).

## Standalone computer connecting to an existing production backend

Prerequisite: the backend is already deployed with control migrations, PostgreSQL, Redis, Daphne, and the control worker. Initial infrastructure setup is covered separately in [backend deployment](../backend-deployment.md) and [control setup](../control-setup.md). The following commands are instructions, not commands executed by this research.

1. **Prepare the computer.** Install Git, Node.js 24+, pnpm 11.2.2, and uv. Clone the project using its repository URL, enter its root, and run:

   ```sh
   pnpm install --frozen-lockfile
   pnpm setup:localization
   ```

   The localization project requires Python 3.14; uv manages the project environment. This computer does not need a local PostgreSQL or Redis server to connect to production.

2. **Choose the existing logical device UUID.** Obtain the device selected by the backend's `CONTROL_DEMO_DEVICE_ID` or inspect Devices in Django admin. Reuse that UUID for additional interchangeable computers. If setting up the first device, create it in step 3 and use the UUID printed by that command.

3. **Issue a unique credential on the backend server.** SSH to the configured server. From a privileged shell, enter the deployment user's shell:

   ```sh
   sudo -iu helios-deploy
   ```

   Then load the production environment and create a private staging directory:

   ```sh
   set -a
   source /etc/helios/backend.env
   set +a
   cd /srv/helios/current/apps/backend
   umask 077
   mkdir -p "$HOME/helios-enrollment"
   chmod 700 "$HOME/helios-enrollment"
   ```

   For an additional computer, replace `DEVICE_UUID` and use a new filename:

   ```sh
   .venv/bin/python manage.py provision_device \
     --device-id DEVICE_UUID \
     --credential-file "$HOME/helios-enrollment/laptop-a.credential"
   ```

   For the first logical device only, use this instead:

   ```sh
   .venv/bin/python manage.py provision_device \
     --name "Helios control" \
     --credential-file "$HOME/helios-enrollment/laptop-a.credential"
   ```

   Both variants print `CONTROL_DEMO_DEVICE_ID=<uuid>`. The credential file must not already exist, and its parent directory must exist. The file is created with mode 0600. `--name` names a new logical device, not the computer; it has no effect when `--device-id` is supplied. Issuing another credential does not revoke earlier credentials.

4. **For first-time browser control setup, configure the server.** Set `CONTROL_DEMO_DEVICE_ID` to the printed UUID and `CONTROL_PASSWORD_HASH` to a Django password hash in `/etc/helios/backend.env`. Preserve an already working configuration when adding a computer. To generate a hash interactively in the production environment above:

   ```sh
   .venv/bin/python manage.py shell -c 'from getpass import getpass; from django.contrib.auth.hashers import make_password; print(make_password(getpass("Demo password: ")))'
   ```

   Store the hash as a single-quoted environment value so shell sourcing preserves its dollar signs. From a privileged shell, restart the configured services if environment values changed:

   ```sh
   systemctl restart helios.service helios-control.service
   ```

   The demo password is the browser login gate, separate from the computer's credential. Adding another credential for the existing device does not itself require a service restart.

5. **Transfer the credential to the computer.** On that computer, use the SSH key/account configured for backend access; replace `SERVER` and the identity path as appropriate:

   ```sh
   mkdir -p "$HOME/.config/helios"
   chmod 700 "$HOME/.config/helios"
   scp -i ~/.ssh/helios_ed25519 \
     helios-deploy@SERVER:/home/helios-deploy/helios-enrollment/laptop-a.credential \
     "$HOME/.config/helios/pi.credential"
   chmod 600 "$HOME/.config/helios/pi.credential"
   ```

   If the computer has no authorized SSH access, an authorized administrator must securely transfer the file to it. Do not reuse one credential across computers. Remove the temporary server copy after verifying transfer; keep the computer's copy. A lost credential must be replaced, since the backend stores its hash.

6. **Save the connection configuration.** In the repository root on the computer:

   ```sh
   pnpm pi:setup
   ```

   Answer the three prompts:

   - Backend WSS URL: `wss://api.projecthelios.dev/ws/v1/pi/` (Enter accepts this default).
   - Provisioned device UUID: the UUID from step 2 or 3.
   - Credential file path: `~/.config/helios/pi.credential`.

   This writes `~/.config/helios/localization.json` with mode 0600. It saves the credential's absolute path, not its secret. Setup validates UUID syntax, URL, and file existence; authentication happens only when connecting. CLI flags override environment variables, which override saved settings. Clear stale `HELIOS_*` overrides if a saved configuration appears to be ignored.

7. **Stop any other client targeting this logical device, then start:**

   ```sh
   pnpm pi
   ```

   It currently runs the dummy simulator, not the future hardware runtime. Look for `Connected device=... connection=... source=dummy` and position messages. The client sends its bearer credential in the WebSocket Authorization header; the backend derives identity from the credential, assigns a connection ID, and sends `setup`. The client validates setup, sends `ready`, and publishes positions at 5 Hz.

8. **Verify end to end.** Sign in at the deployed frontend `/control` using the configured demo password and a Clemson-format email. Confirm live dummy positions, send a target when holding the browser control turn, and verify acknowledgment and arrival. Ctrl+C stops the CLI. Each later run only needs `pnpm pi`.

9. **Repeat for more computers.** Repeat credential issuance, secure transfer, and local setup with the same device UUID and a different credential file for each computer. Maintain a manual mapping from credential ID to computer until named registration is implemented. To revoke a computer, set that credential's `revoked_at` in Django admin. Do not disable the shared Device unless all its computers should lose access.

Sources: [provisioning command](../../apps/backend/control/management/commands/provision_device.py), [CLI](../../apps/localization/src/helios_localization/__main__.py), [transport](../../apps/localization/src/helios_localization/transport.py), [backend service](../../deploy/helios.service), [bootstrap account and directory configuration](../../deploy/bootstrap.sh), [localization README](../../apps/localization/README.md), [root commands](../../package.json).

## Local all-in-one development shortcut

1. Install Node.js, pnpm, uv, PostgreSQL 16, and Redis as described in the root README.
2. Run `pnpm install --frozen-lockfile` in the repository root.
3. Run `pnpm dev`, or load `solo.yml` in Solo and start its processes. Use one launcher at a time.
4. The launcher creates local services, migrates the database, creates/reuses a local device and credential, sets the demo login, and starts the dummy client automatically. Data stays in ignored `.helios/dev/`.
5. Open `http://127.0.0.1:5173/control` and use a Clemson-format email and `SeniorDesign`.

This is a separate local database and local credential; it does not enroll this computer in production. A standalone computer outside loopback must use WSS: the CLI rejects plain `ws://` to a LAN host. See [dev launcher](../../scripts/dev.py) and [control setup](../control-setup.md).

## Current conflict behavior and required change

`connect_pi()` locks the Device row but unconditionally invalidates the previous connection before assigning a new one. The older socket can receive close code 4409; the CLI catches connection errors and retries indefinitely with jittered backoff capped at 30 seconds. Thus two clients can repeatedly replace each other. This does not meet the requested first-connection-wins behavior.

The desired implementation should preserve multiple registered computers while atomically rejecting a new session whenever the shared control slot is live, including its initial handshake. The rejected `pnpm pi` must print an actionable conflict and exit nonzero without retrying; it must not interrupt the active machine or its command. Old disconnect handlers must only release their own session. Dead sessions need heartbeat expiry and session-ID fencing so a machine with a lost network connection cannot block the slot forever or send commands after replacement. The current implementation uses a 5-second liveness window and a 6-second Redis presence TTL; those are separate from the browser's control-turn lease.

With all computers assigned to one logical Device, its row is a natural place to serialize admission. If the requirement includes different Device records, use a shared backend-wide slot rather than a per-device lock. Redis failure must not be interpreted as an available slot. Missing presence after Redis restart needs an explicit recovery/fencing policy. The machine should remain idle until admission succeeds.

The Pi systemd template currently has `Restart=always`. A terminal conflict exit must also be excluded from service restarts, otherwise systemd will restart a correctly exiting client. Enrollment, wire-level conflict reporting, CLI exit behavior, and service restart behavior must be changed together. See the [alternatives and implementation recommendation](computer-enrollment-options.md).
