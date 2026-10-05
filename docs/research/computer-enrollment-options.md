# Simpler computer enrollment for Helios

Research date: 2026-10-05. These are proposals, not implemented commands or endpoints. The objective is to register several computers once, then let only one run `pnpm pi` against the shared control target at a time.

For the complete existing workflow, see [current computer registration](computer-registration-current.md).

Start with an administrator-generated, single-use enrollment token and an interactive CLI registration command. This removes server access and manual credential-file copying from each computer's setup. Browser approval is the strongest next step for a polished experience across laptops and headless Raspberry Pis. Connection exclusivity is a separate backend requirement whichever enrollment flow is chosen.

## What the current model already supports

`DeviceCredential.device` is a many-to-one relationship, so several independently revocable credentials can already represent computers connecting to the same logical `Device`. `provision_device --device-id` issues another credential for an existing device. Credentials currently lack a computer name or separate machine identity. `connect_pi` replaces the existing connection unconditionally. These are repository facts, not behavior supplied by an enrollment standard. Sources: [models](../../apps/backend/control/models.py), [provisioning command](../../apps/backend/control/management/commands/provision_device.py), [connection service](../../apps/backend/control/services.py).

Recommended model: keep `Device` as the logical control target and register each computer as a named `Machine` with its own credentials, creation/revocation dates and last connection time. Credential rotation should preserve the machine identity. Enrollment authorizes a machine; connecting acquires the active slot. Several registered machines remain valid while offline. Do not copy one permanent bearer credential to every computer: that prevents independent identification and revocation.

Scope assumption: the computers are alternative runners for the same Helios target. If the intended rule is one runner across the entire backend even when computers belong to different `Device` rows, use a shared backend-wide slot; locking each device separately would not enforce that rule.

## Enrollment options

The effort and suitability assessments below are design judgments for this repository.

| Option | Proposed user experience | Advantages | Costs and limitations |
| --- | --- | --- | --- |
| Single-use enrollment token | Admin clicks Add computer, copies a token, then pastes it into an interactive CLI prompt on that computer. | Smallest change; works over SSH and without a local browser; no permanent secret copied manually. | Still requires one copy/paste and new issuance/redemption endpoints. |
| Browser approval with a device code | CLI displays a URL and short code; user opens the URL on any computer or phone, signs in and approves. CLI saves its credential automatically. | Good experience for headless Pis and laptops; user never handles the permanent credential. | Requires pending requests, approval UI, expiration, polling and abuse controls. |
| Browser login with loopback callback | CLI opens the local browser; user approves; browser returns to a temporary listener on the same computer. | Few steps on a desktop; established native-app OAuth pattern. | Awkward over SSH because the browser and CLI may be on different machines; callback handling and PKCE add work. |
| Managed provisioning over SSH | An administrator runs a script or configuration-management job that installs a distinct credential and config on each machine. | Useful for machines already managed centrally; little work at the target keyboard. | Requires SSH access and secret-handling automation; less suitable for self-service registration. |

### Single use token

Tailscale provides a useful first-party precedent: preauthentication keys enroll nodes without browser login; one-off keys are consumed after use, while enrolled node identity has a separate lifetime. This is an architectural example, not a suggestion to install Tailscale or reuse its API. [Tailscale auth keys](https://tailscale.com/docs/features/access-control/auth-keys).

Proposed Helios flow:

1. An authorized administrator selects the logical target and clicks Add computer.
2. The backend issues a random enrollment token, scoped to that target and a short validity period, for example ten minutes. This duration is a proposed product choice.
3. On the new computer, run a proposed `pnpm pi register` command. It asks for the trusted backend URL, computer name and token. Use a hidden prompt rather than a secret command-line argument.
4. The CLI redeems the token over HTTPS. One transaction consumes the token and creates the machine and credential. Two simultaneous redemptions must not both succeed.
5. The CLI saves its credential in a private file and writes its backend configuration automatically. The server stores the credential hash, as the current credential implementation already does.
6. Later runs use `pnpm pi` without another registration. Revocation targets that machine alone.

The token is a bootstrap secret, not the permanent connection credential. Use a high-entropy token for this flow; a short human code needs additional rate limiting and guessing protections. Show the enrollment token once, store a hash, enforce expiry and single use, and authorize issuance separately from ordinary control access. Handle an interrupted redemption response or failed local save by offering a fresh registration and allowing the unused credential to be revoked. Tailscale specifically documents the shell-history exposure of command-line auth keys. [Secure auth-key handling](https://tailscale.com/docs/features/access-control/auth-keys/how-to/secure-auth-keys).

### Browser approval

RFC 8628 defines a device authorization flow using a private device code, user-visible verification code, browser approval and outbound polling. It supports devices without a browser or incoming connectivity; polling must obey the server interval and handle pending, slowdown, denial and expiry. [RFC 8628](https://www.rfc-editor.org/rfc/rfc8628.html). GitHub documents this pattern for headless CLI applications. [GitHub device flow](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps#device-flow).

Proposed Helios flow:

1. First run of `pnpm pi`, or explicit registration, asks for the backend and a computer name.
2. The CLI displays an approval URL and short code. The CLI keeps the private request secret locally.
3. The user signs into Helios in a browser, verifies the code/name, selects the target and approves enrollment with an appropriately authorized account.
4. The CLI polls, receives its machine credential only after approval, saves it and confirms registration.
5. Future starts reuse that credential and compete for the same active slot.

This can reuse the existing browser session for the approval screen. If only borrowing the interaction pattern while issuing Helios credentials, describe it as custom device pairing; do not claim RFC-compliant OAuth without implementing the required protocol. Make requests expire, rate-limit approval attempts and polling, and show enough request context for the user to reject an unexpected request. These protections and code confirmation follow the risks described in RFC 8628 sections 5–6.

### Loopback browser login

RFC 8252 describes native applications opening an external browser and receiving an authorization code through a loopback IP callback. Public native clients must use PKCE. [RFC 8252](https://www.rfc-editor.org/rfc/rfc8252.html).

For Helios this would mean a temporary listener on `127.0.0.1`, browser approval and a code exchange before saving the machine credential. It is a good optional desktop path if an OAuth authorization service is introduced. It is not my first choice for the common SSH-to-Pi case: a browser on the operator's laptop returns to that laptop, not automatically to the Pi running the CLI.

### Automated provisioning

A modest script could wrap today's provisioning command, transfer each machine's private credential and write the local configuration. Ansible's copy module supports remote placement, explicit file permissions and automatic decryption of vaulted files. [Ansible copy module](https://docs.ansible.com/projects/ansible/13/collections/ansible/builtin/copy_module.html).

This is a reasonable operational shortcut if SSH inventory already exists. It retains privileged server access and secret distribution responsibilities, so it does not improve self-service registration as much as token redemption or browser approval. Keep credentials distinct per computer and exclude secret values from job output.

## Enforcing one active runner

The following is a proposed design, independent of enrollment:

1. Authenticate the connecting machine and confirm it is enabled.
2. Lock the shared control-slot row in a database transaction. For one logical target this can be the existing `Device` row; for backend-wide exclusivity use one shared row that every runner must acquire.
3. If an unexpired connection owns the slot, reject the newcomer. Do not invalidate the incumbent, alter its command state or revoke the newcomer's registration.
4. Otherwise record the new machine, unique connection ID and liveness deadline atomically, then issue setup. Claim the slot before setup is delivered so simultaneous starts cannot both pass admission.
5. Renew only for the matching connection ID. Release on normal disconnect only if that ID still owns the slot. After a crashed or partitioned client times out, fence its old ID from telemetry, command acknowledgments and dispatch before admitting another runner.
6. Fail closed when the backend cannot establish ownership. Keep the existing local heartbeat watchdog; a backend lease alone cannot prove that disconnected hardware has physically stopped.

This fits the existing database serialization approach. Django documents that `select_for_update()` locks rows until the transaction ends and does nothing on SQLite; concurrency validation must use the actual PostgreSQL behavior. [Django row locking](https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update). The current browser-user `ControlLease` is a different resource from the computer connection slot.

### Error and process behavior

Proposed error text: `Cannot start: another computer (lab-pi) is already connected. Stop it, then run pnpm pi again.` Use a stable machine-readable reason such as `machine_already_connected` and a documented nonzero exit status. Treat it as terminal, bypassing the reconnect loop; preserve retries for transient network failures. Keep the new machine registered so it can run later.

Do not rely on calling `close(code=4409)` before WebSocket acceptance to deliver the reason. ASGI requires a preaccept close to become an HTTP 403 denial; only a postaccept close sends the WebSocket close code. [ASGI WebSocket close semantics](https://asgi.readthedocs.io/en/latest/specs/www.html#close-send-event). One design is to authenticate first, attempt atomic admission, then accept an authenticated rejected socket solely to send a structured conflict error and close before any setup or control traffic. Add this error shape to the contract and teach the client to handle it while waiting for setup. The application close-code meaning must be documented; 4409 is not an HTTP status.

A supervised service must also stay stopped on this error. Configure its conflict exit status in `RestartPreventExitStatus=`; changing only the Python reconnect loop is insufficient with an unconditional restart policy. This setting prevents selected main-process statuses from triggering automatic restart even when `Restart=` would otherwise do so. Verify that any shell, pnpm or uv wrapper preserves the status seen by systemd. [Official systemd service manual source](https://raw.githubusercontent.com/systemd/systemd/main/man/systemd.service.xml).

## Acceptance criteria for implementation

- Two named computers can register independently, remain registered offline and be revoked independently.
- The first connection stays active; a second gets a readable terminal error and exits nonzero without retrying or disrupting the first.
- Simultaneous starts through different backend workers admit exactly one runner.
- A second process on the same machine is also rejected; reconnects do not silently replace a live connection.
- Normal disconnect permits the next run; a crash permits it only after the liveness deadline and old-connection fencing.
- Late disconnects and messages from an old connection cannot release or affect its replacement.
- Used or expired enrollment tokens fail; simultaneous redemption creates only one machine; secrets do not appear in logs or process arguments.
- The configured service supervisor preserves the fatal conflict behavior.

No enrollment code, connection policy or service configuration was changed during this research.
